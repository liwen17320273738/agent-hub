"""OpenAI-compatible /v1/chat/completions proxy.

Exposes the local LLM (e.g. Ollama) as a standard OpenAI-compatible
endpoint so external platforms (Feishu 智能体, OpenClaw, etc.) can call
it via a public tunnel URL.

Auth: Bearer token validated against PIPELINE_API_KEY.
"""
from __future__ import annotations

import json
import logging
import secrets as _secrets
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["openai-compat"])


def _require_bearer(request: Request) -> None:
    secret = settings.pipeline_api_key
    if not secret:
        raise HTTPException(status_code=503, detail="Gateway not configured")
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""
    if not token or not _secrets.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="Invalid API key")


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
async def openai_chat_completions(body: ChatCompletionRequest, request: Request):
    _require_bearer(request)

    from ..services.llm_router import chat_completion, chat_completion_stream

    model = body.model.strip() or settings.llm_model
    max_tokens = min(32768, body.max_tokens)
    req_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if body.stream:
        async def _stream():
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
                    yield f"data: {json.dumps({'error': inner['error']})}\n\n"
                    return
                sse = {
                    "id": req_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": inner.get("content", "")},
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
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


@router.get("/v1/models")
async def openai_list_models(request: Request):
    """List available models — proxies from upstream LLM server when possible."""
    _require_bearer(request)

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
async def openai_agent_hub_models(request: Request):
    """Alias model list for the intake bridge base path."""
    return await openai_list_models(request)


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
    _require_bearer(request)

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
