"""
DeerFlow Delegate Tool — call a running DeerFlow instance from pipeline agents.

Enables pipeline stages to delegate research, code execution, and deep analysis
to DeerFlow's LangGraph-based multi-agent system.

Environment variables:
  DEERFLOW_URL           — Unified proxy base URL (default: http://localhost:2026)
  DEERFLOW_GATEWAY_URL   — Gateway API (models, skills, memory, uploads)
  DEERFLOW_LANGGRAPH_URL — LangGraph API (threads, runs, streaming)
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 300  # 5 minutes for deep research tasks


def _resolve_urls() -> Dict[str, str]:
    base = os.environ.get("DEERFLOW_URL", "http://localhost:2026")
    return {
        "base": base,
        "gateway": os.environ.get("DEERFLOW_GATEWAY_URL", base),
        "langgraph": os.environ.get("DEERFLOW_LANGGRAPH_URL", f"{base}/api/langgraph"),
    }


async def deerflow_health() -> Dict[str, Any]:
    """Check if DeerFlow is running."""
    urls = _resolve_urls()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{urls['gateway']}/health")
            return {"ok": resp.status_code == 200, "status": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def deerflow_delegate(params: Dict[str, Any]) -> str:
    """Delegate a task to DeerFlow and return the response.

    Params:
        message: str    — The task/question to send
        mode: str       — flash|standard|pro|ultra (default: pro)
        thread_id: str  — Optional existing thread to continue
        timeout: int    — Request timeout in seconds (default: 300)
    """
    message = params.get("message", "")
    if not message:
        return json.dumps({"ok": False, "error": "message is required"})

    mode = params.get("mode", "pro")
    thread_id = params.get("thread_id")
    timeout = params.get("timeout", _TIMEOUT)
    urls = _resolve_urls()

    mode_configs = {
        "flash": {"thinking_enabled": False, "is_plan_mode": False, "subagent_enabled": False},
        "standard": {"thinking_enabled": True, "is_plan_mode": False, "subagent_enabled": False},
        "pro": {"thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": False},
        "ultra": {"thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": True},
    }
    context = mode_configs.get(mode, mode_configs["pro"])

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if not thread_id:
                resp = await client.post(
                    f"{urls['langgraph']}/threads",
                    json={},
                )
                if resp.status_code != 200:
                    return json.dumps({"ok": False, "error": f"Failed to create thread: {resp.status_code}"})
                thread_id = resp.json().get("thread_id")

            context["thread_id"] = thread_id

            resp = await client.post(
                f"{urls['langgraph']}/threads/{thread_id}/runs/stream",
                json={
                    "assistant_id": "lead_agent",
                    "input": {
                        "messages": [{
                            "type": "human",
                            "content": [{"type": "text", "text": message}],
                        }],
                    },
                    "stream_mode": ["values"],
                    "stream_subgraphs": True,
                    "config": {"recursion_limit": 1000},
                    "context": context,
                },
            )

            if resp.status_code != 200:
                return json.dumps({"ok": False, "error": f"Stream failed: {resp.status_code}", "body": resp.text[:500]})

            ai_response = _extract_ai_response(resp.text)

            return json.dumps({
                "ok": True,
                "thread_id": thread_id,
                "mode": mode,
                "response": ai_response,
            }, ensure_ascii=False)

    except httpx.TimeoutException:
        return json.dumps({"ok": False, "error": f"DeerFlow request timed out after {timeout}s"})
    except httpx.ConnectError:
        return json.dumps({"ok": False, "error": "Cannot connect to DeerFlow — is it running?"})
    except Exception as e:
        logger.error(f"[deerflow] Delegate failed: {e}")
        return json.dumps({"ok": False, "error": str(e)})


async def deerflow_list_skills(params: Dict[str, Any]) -> str:
    """List available skills from the DeerFlow instance."""
    urls = _resolve_urls()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{urls['gateway']}/api/skills")
            return resp.text
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


async def deerflow_list_models(params: Dict[str, Any]) -> str:
    """List available models from the DeerFlow instance."""
    urls = _resolve_urls()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{urls['gateway']}/api/models")
            return resp.text
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def _extract_ai_response(sse_text: str) -> str:
    """Extract the final AI response from SSE stream output."""
    last_values_data = None
    for block in sse_text.split("\n\n"):
        lines = block.strip().splitlines()
        event_type = None
        data_line = None
        for line in lines:
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_line = line[5:].strip()

        if event_type == "values" and data_line:
            last_values_data = data_line

    if not last_values_data:
        cleaned = re.sub(r"^(event|data):.*\n?", "", sse_text, flags=re.MULTILINE).strip()
        return cleaned[:5000] if cleaned else "(no response extracted)"

    try:
        parsed = json.loads(last_values_data)
        messages = parsed.get("messages", [])
        for msg in reversed(messages):
            if msg.get("type") == "ai" and msg.get("content"):
                content = msg["content"]
                if isinstance(content, list):
                    return "\n".join(
                        c.get("text", "") for c in content if c.get("type") == "text"
                    )
                return str(content)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    return "(could not parse DeerFlow response)"
