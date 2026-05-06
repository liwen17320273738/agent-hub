"""LLM proxy: unified chat endpoint routing to multiple providers."""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..security import get_current_user
from ..services.llm_router import chat_completion, chat_completion_stream
from ..services.token_tracker import record_usage

router = APIRouter(prefix="/llm", tags=["llm"])

MAX_MESSAGES = 128
MAX_BODY_CHARS = 400_000


class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = False
    agent_id: Optional[str] = None
    api_url: str = ""


def _validate_messages(messages: List[Dict[str, Any]]) -> None:
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages 须为数组")
    if len(messages) > MAX_MESSAGES:
        raise HTTPException(status_code=400, detail=f"消息条数超过上限 {MAX_MESSAGES}")
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    if total_chars > MAX_BODY_CHARS:
        raise HTTPException(status_code=400, detail="消息总长度超过上限")


@router.post("/chat")
async def chat(
    body: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _validate_messages(body.messages)

    from ..config import settings
    model = body.model.strip() or settings.llm_model
    max_tokens = min(16384, body.max_tokens)

    if body.stream:
        return StreamingResponse(
            chat_completion_stream(
                model=model,
                messages=body.messages,
                temperature=body.temperature,
                max_tokens=max_tokens,
                api_url=body.api_url,
            ),
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
        api_url=body.api_url,
    )

    if "error" in result:
        status_code = result.get("status", 502)
        raise HTTPException(status_code=status_code, detail=result["error"])

    usage = result.get("usage") or {}
    if usage.get("prompt_tokens"):
        await record_usage(
            db,
            org_id=user.org_id,
            user_id=user.id,
            agent_id=body.agent_id,
            provider=result.get("provider", "unknown"),
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=result.get("latency_ms", 0),
            endpoint="chat",
        )

    return {
        "choices": [{"message": {"content": result["content"]}}],
        "usage": usage,
        "provider": result.get("provider"),
        "latency_ms": result.get("latency_ms"),
    }


@router.post("/chat-with-tools")
async def chat_with_tools(
    body: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Execute a chat using AgentRuntime with tool calling enabled.

    When agent_id is provided, the agent's bound tools are used.
    Falls back to plain chat if the agent has no tools configured.
    """
    _validate_messages(body.messages)

    if not body.agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required for tool-enabled chat")

    from ..agents.seed import AGENT_TOOLS
    from ..models.agent import AgentDefinition

    agent = await db.get(AgentDefinition, body.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    tool_names = AGENT_TOOLS.get(body.agent_id, [])

    user_content = ""
    for msg in body.messages:
        if msg.get("role") == "user":
            user_content = msg.get("content", "")

    if not user_content:
        raise HTTPException(status_code=400, detail="No user message found")

    if not tool_names:
        from ..config import settings
        model = body.model.strip() or settings.llm_model
        result = await chat_completion(
            model=model,
            messages=body.messages,
            temperature=body.temperature,
            max_tokens=min(16384, body.max_tokens),
        )
        if "error" in result:
            raise HTTPException(status_code=502, detail=result["error"])
        return {
            "choices": [{"message": {"content": result["content"]}}],
            "usage": result.get("usage", {}),
            "provider": result.get("provider"),
            "tools_used": [],
        }

    from ..services.agent_runtime import AgentRuntime
    from ..config import settings

    model = body.model.strip() or agent.preferred_model or settings.llm_model

    runtime = AgentRuntime(
        agent_id=body.agent_id,
        system_prompt=agent.system_prompt,
        tools=tool_names,
        model_preference={"execution": model},
        max_steps=8,
        temperature=body.temperature,
    )

    result = await runtime.execute(db, task=user_content)

    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent execution failed"))

    return {
        "choices": [{"message": {"content": result["content"]}}],
        "tools_used": result.get("observations", []),
        "steps": result.get("steps", 0),
        "model": result.get("model"),
        "verification": result.get("verification"),
    }


@router.post("/chat-once")
async def chat_once(
    body: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Single-turn chat with latency measurement (for model lab)."""
    _validate_messages(body.messages)

    from ..config import settings
    model = body.model.strip() or settings.llm_model
    max_tokens = min(16384, body.max_tokens)

    result = await chat_completion(
        model=model,
        messages=body.messages,
        temperature=body.temperature,
        max_tokens=max_tokens,
        stream=False,
        api_url=body.api_url,
    )

    usage = result.get("usage") or {}
    if usage.get("prompt_tokens") and "error" not in result:
        await record_usage(
            db,
            org_id=user.org_id,
            user_id=user.id,
            agent_id=body.agent_id,
            provider=result.get("provider", "unknown"),
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=result.get("latency_ms", 0),
            endpoint="chat-once",
        )

    return {
        "content": result.get("content", ""),
        "latency_ms": result.get("latency_ms", 0),
        "usage": usage,
        "error": result.get("error"),
    }
