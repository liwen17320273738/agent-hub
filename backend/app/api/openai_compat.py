"""OpenAI-compatible /v1/chat/completions proxy.

Exposes the platform LLM router so external clients can call it via an
OpenAI-compatible URL (tunnel, Feishu, OpenClaw, etc.).

Auth: ``Authorization: Bearer`` — either ``PIPELINE_API_KEY`` (server) or a
customer **relay API key** (``ahrelay_…`` from ``POST /api/relay/keys``).
Relay usage debits ``orgs.relay_balance_usd``; configure ``RELAY_MARKUP_MULTIPLIER``.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import async_session, get_db
from ..services.relay_billing import (
    RelayAuthContext,
    debit_relay_and_record,
    require_relay_balance,
    resolve_openai_compat_bearer,
    settle_relay_stream_usage,
    touch_relay_key_used,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["openai-compat"])


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return ""
    return auth[7:].strip()


async def _openai_gateway_auth(
    request: Request,
    db: AsyncSession,
    *,
    require_balance_for_relay: bool = True,
) -> tuple[str, Optional[RelayAuthContext]]:
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing API key")
    kind, rctx = await resolve_openai_compat_bearer(db, token)
    if require_balance_for_relay and kind == "relay" and rctx:
        await require_relay_balance(db, rctx.org_id)
    return kind, rctx


class ChatCompletionRequest(BaseModel):
    model: str = ""
    messages: List[Dict[str, Any]]
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = False
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    user: Optional[str] = None


def _latest_user_text(messages: List[Dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if str(msg.get("role", "")).lower() != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
        elif isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            text = "\n".join(p.strip() for p in parts if p and str(p).strip()).strip()
            if text:
                return text
    return ""


def _task_ack_content(task_id: str, title: str) -> str:
    return (
        "已切换到 agent-hub 执行流。\n\n"
        f"任务已创建：`{title}`\n"
        f"任务 ID：`{task_id}`\n\n"
        "接下来将进入 agent-hub 的 planning / pipeline 流程继续执行。"
    )


def _openai_success_response(*, req_id: str, created: int, model: str, content: str) -> Dict[str, Any]:
    return {
        "id": req_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


def _stream_static_openai_response(*, req_id: str, created: int, model: str, content: str) -> StreamingResponse:
    async def _stream() -> Any:
        chunk = {
            "id": req_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        final = {
            "id": req_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
        }
        yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/v1/chat/completions")
@router.post("/v1/chat/completions/chat/completions")
async def openai_chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    from ..services.llm_router import chat_completion, chat_completion_stream
    from ..services.relay_billing import rough_prompt_tokens

    kind, rctx = await _openai_gateway_auth(request, db, require_balance_for_relay=True)

    model = body.model.strip() or settings.llm_model
    max_tokens = min(32768, body.max_tokens)
    req_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if body.stream:
        async def _stream():
            assistant_parts: List[str] = []
            prov = "unknown"
            t0 = time.time()
            saw_error = False
            try:
                async for chunk in chat_completion_stream(
                    model=model,
                    messages=body.messages,
                    temperature=body.temperature,
                    max_tokens=max_tokens,
                ):
                    if not chunk.startswith("data: "):
                        continue
                    payload = chunk[6:].strip()
                    if payload == "[DONE]":
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        inner = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if inner.get("error"):
                        saw_error = True
                        yield f"data: {json.dumps({'error': inner['error']})}\n\n"
                        return
                    c = inner.get("content", "")
                    if c:
                        assistant_parts.append(c)
                    if inner.get("provider"):
                        prov = str(inner["provider"])
                    sse = {
                        "id": req_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": c},
                            "finish_reason": None,
                        }],
                    }
                    yield f"data: {json.dumps(sse, ensure_ascii=False)}\n\n"
                final = {
                    "id": req_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }],
                }
                yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                if kind == "relay" and rctx and not saw_error:
                    full_text = "".join(assistant_parts)
                    latency_ms = int((time.time() - t0) * 1000)
                    try:
                        async with async_session() as s:
                            await settle_relay_stream_usage(
                                s,
                                ctx=rctx,
                                model=model,
                                messages=body.messages,
                                assistant_text=full_text,
                                provider=prov,
                                latency_ms=latency_ms,
                            )
                            await touch_relay_key_used(s, rctx.key_id)
                            await s.commit()
                    except Exception as e:
                        logger.warning("[relay] stream settlement failed: %s", e)

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = await chat_completion(
        model=model,
        messages=body.messages,
        temperature=body.temperature,
        max_tokens=max_tokens,
    )

    if result.get("error"):
        status = result.get("status", 502)
        raise HTTPException(status_code=status, detail=result["error"])

    usage = result.get("usage") or {}
    pt = int(usage.get("prompt_tokens", 0))
    ct = int(usage.get("completion_tokens", 0))
    if pt == 0 and ct == 0:
        pt = rough_prompt_tokens(body.messages)
        ct = max(1, len(result.get("content", "") or "") // 4)

    if kind == "relay" and rctx:
        await debit_relay_and_record(
            db,
            ctx=rctx,
            provider=str(result.get("provider") or "unknown"),
            model=model,
            prompt_tokens=pt,
            completion_tokens=ct,
            latency_ms=int(result.get("latency_ms", 0) or 0),
        )
        await touch_relay_key_used(db, rctx.key_id)

    return {
        "id": req_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": result.get("content", ""),
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", pt),
            "completion_tokens": usage.get("completion_tokens", ct),
            "total_tokens": usage.get("total_tokens", pt + ct),
        },
    }


@router.get("/v1/models")
async def openai_list_models(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List available models — proxies from upstream LLM server when possible."""
    await _openai_gateway_auth(request, db, require_balance_for_relay=False)

    import httpx

    upstream_base = (settings.llm_api_url or "").strip()
    if upstream_base:
        models_url = upstream_base.split("/v1/")[0] + "/v1/models" if "/v1/" in upstream_base else ""
        if models_url:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    headers = {}
                    if settings.llm_api_key:
                        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
                    resp = await client.get(models_url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict) and "data" in data:
                            return data
            except Exception as e:
                logger.debug("[openai-compat] upstream /v1/models failed: %s", e)

    model_id = settings.llm_model or "default"
    return {
        "object": "list",
        "data": [{
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "local",
        }],
    }


@router.get("/v1/agent-hub/models")
async def openai_agent_hub_models(request: Request, db: AsyncSession = Depends(get_db)):
    """Alias model list for the intake bridge base path."""
    return await openai_list_models(request, db)


@router.post("/v1/agent-hub/chat/completions")
@router.post("/v1/agent-hub/chat/completions/chat/completions")
async def openai_agent_hub_intake(
    body: ChatCompletionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """OpenAI-compatible bridge that converts chat requests into agent-hub tasks.

    This is designed for external "custom model" integrations that can only talk
    to an OpenAI-compatible `/chat/completions` endpoint, but should actually
    enter the agent-hub task/pipeline flow instead of getting a direct LLM reply.
    """
    kind, rctx = await _openai_gateway_auth(request, db)
    if kind == "relay" and rctx:
        await require_relay_balance(db, rctx.org_id)

    from ..api.gateway import (
        _commit_task_before_background,
        _create_task_from_gateway,
        _run_pipeline_background,
    )

    prompt = _latest_user_text(body.messages)
    if not prompt:
        raise HTTPException(status_code=400, detail="No user message found")

    title = prompt.splitlines()[0].strip()[:80] or "未命名任务"
    description = prompt.strip()
    task = await _create_task_from_gateway(
        db,
        title,
        description,
        source="openclaw",
        source_message_id="",
        source_user_id=(body.user or "").strip(),
    )
    await _commit_task_before_background(db, task)
    background_tasks.add_task(
        _run_pipeline_background,
        str(task.id),
        title,
        description,
    )

    if kind == "relay" and rctx:
        await touch_relay_key_used(db, rctx.key_id)

    model = body.model.strip() or settings.llm_model or "agent-hub-intake"
    req_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    content = _task_ack_content(str(task.id), title)

    if body.stream:
        return _stream_static_openai_response(
            req_id=req_id,
            created=created,
            model=model,
            content=content,
        )

    return _openai_success_response(
        req_id=req_id,
        created=created,
        model=model,
        content=content,
    )
