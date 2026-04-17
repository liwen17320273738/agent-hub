"""MCP (Model Context Protocol) client — HTTP / SSE / Streamable HTTP transport.

A pragmatic MVP that talks JSON-RPC 2.0 over HTTP to MCP servers.
Supports two transports:

  1. **streamable_http** (default, MCP 2025-03-26): single endpoint accepting
     POST application/json with optional `Accept: text/event-stream` for
     server-streamed responses. We always request JSON for simplicity.
  2. **sse** (legacy): GET /sse opens a stream; POSTs to /messages?session=...
     Used by older servers (~2024 spec). We do a minimal implementation.

What we DO NOT implement here (intentionally, v0.1):
  - stdio transport (would require subprocess management)
  - resources / prompts (focus on tools first — that's where the agent value is)
  - server → client sampling
  - notifications stream consumption (we send `initialized` then move on)

Public surface used by the rest of the codebase:
  - probe(server_url, ...)            → handshake + list_tools, returns dict
  - list_tools(server_url, ...)       → list of {name, description, parameters}
  - call_tool(server_url, name, args) → JSON-RPC result string
  - build_tool_handlers(mcp_records)  → dict of tool_name → async handler
                                         (used by AgentRuntime injection)

Each `mcp_record` is a row from `agent_mcps` (or any dict with the same shape).

All network I/O is fail-open: if MCP is unreachable, the agent simply runs
without those tools. No exceptions bubble up to break the pipeline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Transport detection + JSON-RPC helpers
# ─────────────────────────────────────────────────────────────────

PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "agent-hub", "version": "0.1"}
DEFAULT_TIMEOUT = 30.0


def _normalize_url(url: str) -> str:
    """Strip trailing slash; ensure scheme present."""
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    parts = urlsplit(u)
    path = (parts.path or "").rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _new_id() -> str:
    return uuid.uuid4().hex


def _rpc(method: str, params: Optional[Dict[str, Any]] = None, *, notif: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    if not notif:
        payload["id"] = _new_id()
    return payload


def _build_headers(config: Optional[Dict[str, Any]]) -> Dict[str, str]:
    h: Dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    config = config or {}
    api_key = config.get("api_key") or config.get("token")
    auth_header = config.get("auth_header") or "Authorization"
    if api_key:
        scheme = config.get("auth_scheme", "Bearer")
        h[auth_header] = f"{scheme} {api_key}".strip()
    extra = config.get("headers") or {}
    if isinstance(extra, dict):
        for k, v in extra.items():
            h[str(k)] = str(v)
    return h


# ─────────────────────────────────────────────────────────────────
# Streamable-HTTP transport (MCP 2025-03-26)
# ─────────────────────────────────────────────────────────────────


class _StreamableSession:
    """One-shot session over streamable HTTP. We initialize, then call methods.

    For MVP we don't keep a long-lived `Mcp-Session-Id` between calls —
    every public function opens its own client. Servers that REQUIRE
    session affinity will degrade; they're rare for read-only tool listing.
    """

    def __init__(self, server_url: str, config: Optional[Dict[str, Any]] = None):
        self.server_url = _normalize_url(server_url)
        self.config = config or {}
        self.headers = _build_headers(self.config)
        timeout = float(self.config.get("timeout", DEFAULT_TIMEOUT))
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self.session_id: Optional[str] = None
        self.protocol_version: str = PROTOCOL_VERSION

    async def __aenter__(self) -> "_StreamableSession":
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            await self.client.aclose()
        except Exception:
            pass

    async def _post_json(self, body: Dict[str, Any]) -> Dict[str, Any]:
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        rsp = await self.client.post(self.server_url, content=json.dumps(body), headers=headers)
        sid = rsp.headers.get("Mcp-Session-Id")
        if sid and not self.session_id:
            self.session_id = sid
        ctype = rsp.headers.get("content-type", "")
        if rsp.status_code >= 400:
            raise httpx.HTTPStatusError(f"MCP HTTP {rsp.status_code}: {rsp.text[:300]}",
                                        request=rsp.request, response=rsp)
        if "text/event-stream" in ctype:
            return _parse_first_sse_message(rsp.text)
        text = rsp.text.strip()
        if not text:
            return {}
        return json.loads(text)

    async def initialize(self) -> Dict[str, Any]:
        params = {
            "protocolVersion": self.protocol_version,
            "capabilities": {"tools": {}},
            "clientInfo": CLIENT_INFO,
        }
        rsp = await self._post_json(_rpc("initialize", params))
        result = rsp.get("result") or {}
        try:
            await self._post_json(_rpc("notifications/initialized", notif=True))
        except Exception as e:
            logger.debug(f"[mcp] initialized notification failed: {e}")
        return result

    async def list_tools(self) -> List[Dict[str, Any]]:
        rsp = await self._post_json(_rpc("tools/list", {}))
        return list((rsp.get("result") or {}).get("tools") or [])

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        rsp = await self._post_json(_rpc("tools/call", {"name": name, "arguments": arguments}))
        if rsp.get("error"):
            return {"isError": True, "error": rsp["error"]}
        return rsp.get("result") or {}


def _parse_first_sse_message(body: str) -> Dict[str, Any]:
    """Parse just the first complete `data:` event from an SSE response body."""
    data_lines: List[str] = []
    for line in body.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line.strip() and data_lines:
            break
    if not data_lines:
        return {}
    try:
        return json.loads("\n".join(data_lines))
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


async def probe(
    server_url: str,
    config: Optional[Dict[str, Any]] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Quick handshake against an MCP server, return tools + server info.

    Never raises — returns `{"ok": False, "error": "..."}` on any failure,
    which is what the API layer wants for an interactive probe button.
    """
    started = time.monotonic()
    cfg = dict(config or {})
    cfg.setdefault("timeout", timeout)
    try:
        async with _StreamableSession(server_url, cfg) as s:
            srv = await s.initialize()
            tools = await s.list_tools()
            return {
                "ok": True,
                "server_url": s.server_url,
                "session_id": s.session_id,
                "server_info": srv.get("serverInfo") or {},
                "protocol_version": srv.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": srv.get("capabilities") or {},
                "tools": tools,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
    except Exception as e:
        logger.info(f"[mcp.probe] {server_url}: {e}")
        return {
            "ok": False,
            "server_url": _normalize_url(server_url),
            "error": str(e),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


async def list_tools(
    server_url: str, config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    try:
        async with _StreamableSession(server_url, config) as s:
            await s.initialize()
            return await s.list_tools()
    except Exception as e:
        logger.info(f"[mcp.list_tools] {server_url}: {e}")
        return []


async def call_tool(
    server_url: str,
    name: str,
    arguments: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        async with _StreamableSession(server_url, config) as s:
            await s.initialize()
            return await s.call_tool(name, arguments)
    except Exception as e:
        logger.info(f"[mcp.call_tool] {server_url} {name}: {e}")
        return {"isError": True, "error": str(e)}


# ─────────────────────────────────────────────────────────────────
# Adaptation: convert MCP tool schemas → AgentRuntime tool defs + handlers
# ─────────────────────────────────────────────────────────────────


def _normalize_tool_name(server_label: str, tool_name: str) -> str:
    """Prefix MCP tool names with their server label so they don't collide
    with built-in tools (`mcp__github__create_issue` style).
    """
    safe_label = "".join(c if c.isalnum() else "_" for c in (server_label or "mcp")).strip("_") or "mcp"
    safe_tool = "".join(c if c.isalnum() or c in "_-" else "_" for c in (tool_name or "tool")).strip("_") or "tool"
    return f"mcp__{safe_label}__{safe_tool}"[:128]


def _flatten_call_result(result: Dict[str, Any]) -> str:
    """Turn an MCP call_tool result into a single string for the LLM."""
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, default=str)
    if result.get("isError"):
        err = result.get("error") or "unknown MCP error"
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err, ensure_ascii=False)
        return f"[MCP error] {err}"
    content = result.get("content") or []
    if isinstance(content, list) and content:
        parts: List[str] = []
        for c in content:
            if not isinstance(c, dict):
                parts.append(str(c))
                continue
            t = c.get("type")
            if t == "text":
                parts.append(str(c.get("text", "")))
            elif t == "image":
                mime = c.get("mimeType", "image")
                parts.append(f"[image {mime} base64-len={len(str(c.get('data', '')))}]")
            elif t == "resource":
                res = c.get("resource") or {}
                parts.append(f"[resource {res.get('uri', '')}]")
            else:
                parts.append(json.dumps(c, ensure_ascii=False, default=str))
        return "\n".join(parts)
    if "structuredContent" in result:
        return json.dumps(result["structuredContent"], ensure_ascii=False, default=str)
    return json.dumps(result, ensure_ascii=False, default=str)


async def build_tool_handlers(
    mcp_records: Iterable[Dict[str, Any]],
    *,
    fetch_if_empty: bool = True,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Callable[[Dict[str, Any]], Awaitable[str]]]]:
    """Build OpenAI-style tool defs + handlers from a list of MCP records.

    Each record (= one row of `agent_mcps`) should contain:
      - id, name, server_url
      - tools: cached list of {"name", "description", "inputSchema"} (preferred)
      - config: dict (auth, headers, timeout, ...)

    Args:
      mcp_records: list of dict-like records.
      fetch_if_empty: if a record has no cached `tools`, perform a live
        `list_tools()` call. Disable for hot paths where fail-open speed
        matters more than completeness.

    Returns:
      (tool_definitions_by_name, handlers_by_name)
    """
    definitions: Dict[str, Dict[str, Any]] = {}
    handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[str]]] = {}

    async def _process(rec: Dict[str, Any]) -> None:
        if not isinstance(rec, dict):
            return
        if rec.get("enabled") is False:
            return
        server_url = rec.get("server_url") or ""
        if not server_url:
            return
        label = rec.get("name") or "mcp"
        config = rec.get("config") or {}
        cached_tools: List[Dict[str, Any]] = list(rec.get("tools") or [])
        if not cached_tools and fetch_if_empty:
            cached_tools = await list_tools(server_url, config)
        for t in cached_tools:
            if not isinstance(t, dict):
                continue
            raw_name = t.get("name")
            if not raw_name:
                continue
            tool_id = _normalize_tool_name(label, raw_name)
            schema = t.get("inputSchema") or {"type": "object", "properties": {}}
            definitions[tool_id] = {
                "name": tool_id,
                "description": (t.get("description") or f"MCP tool {label}.{raw_name}")[:300],
                "parameters": schema,
            }
            handlers[tool_id] = _make_handler(server_url, raw_name, config)

    await asyncio.gather(*(_process(r) for r in mcp_records), return_exceptions=False)
    return definitions, handlers


def _make_handler(server_url: str, tool_name: str, config: Dict[str, Any]):
    async def _handler(arguments: Dict[str, Any]) -> str:
        result = await call_tool(server_url, tool_name, arguments, config)
        return _flatten_call_result(result)
    return _handler


__all__ = [
    "probe", "list_tools", "call_tool",
    "build_tool_handlers",
    "PROTOCOL_VERSION",
]
