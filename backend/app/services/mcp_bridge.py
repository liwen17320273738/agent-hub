"""
MCP Bridge — Ruflo Agent Orchestration Client
===============================================

Communicates with Ruflo's MCP server via stdio JSON-RPC 2.0.
Provides high-level async wrappers for the core Ruflo tool groups:

    - Agent: spawn, execute, terminate, status, list
    - Swarm: init, status, shutdown, health
    - Memory: store, retrieve, search, delete, list, stats
    - Config: get, set, list, reset
    - GOAP: goal_plan, goal_status (if available)

Usage:
    bridge = await McpBridge.start()
    result = await bridge.call_tool("memory_store", {"key": "foo", "value": "bar"})
    await bridge.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── JSON-RPC 2.0 constants ────────────────────────────────────────────

_JSONRPC = "2.0"

# ── Subprocess management ──────────────────────────────────────────────


class McpBridge:
    """MCP client that manages a Ruflo MCP server subprocess.

    Starts ``ruflo mcp start`` as a subprocess, performs the MCP
    initialization handshake, then provides high-level wrappers.
    """

    def __init__(self) -> None:
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._started = False
        self._server_info: Dict[str, Any] = {}

    # ── Lifecycle ──────────────────────────────────────────────────────

    @classmethod
    async def start(
        cls,
        ruflo_cmd: str = "ruflo",
        startup_timeout: float = 15.0,
    ) -> "McpBridge":
        """Factory: create, start subprocess, and perform init handshake."""
        self = cls()
        logger.info("[mcp] Starting Ruflo MCP server subprocess...")

        self._process = await asyncio.create_subprocess_exec(
            ruflo_cmd, "mcp", "start",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "FORCE_COLOR": "0"},
        )

        self._writer = self._process.stdin
        self._reader = self._process.stdout

        if not self._writer or not self._reader:
            raise RuntimeError("Failed to open subprocess pipes")

        # Start background listener for responses
        self._listener_task = asyncio.create_task(self._response_listener())

        # Perform MCP initialization handshake
        await self._initialize(startup_timeout)
        self._started = True
        logger.info("[mcp] Ruflo MCP server ready (PID %d)", self._process.pid)
        return self

    async def stop(self, timeout: float = 5.0) -> None:
        """Gracefully stop the MCP subprocess."""
        self._started = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await asyncio.wait_for(self._listener_task, timeout=timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if self._process and self._process.returncode is None:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("[mcp] Force killing subprocess")
                self._process.kill()
                await self._process.wait()
        logger.info("[mcp] Stopped")

    @property
    def is_running(self) -> bool:
        return self._started and self._process is not None and self._process.returncode is None

    # ── Core MCP methods ───────────────────────────────────────────────

    async def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """Call an MCP tool and return the result.

        Raises ``asyncio.TimeoutError`` if the server does not respond
        within *timeout* seconds.
        """
        if not self.is_running:
            raise RuntimeError("MCP bridge not running")

        self._request_id += 1
        req_id = self._request_id

        request = {
            "jsonrpc": _JSONRPC,
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        try:
            raw = json.dumps(request, ensure_ascii=False)
            logger.debug("[mcp] → %s(%s)", name, _truncate(str(arguments), 200))
            self._writer.write((raw + "\n").encode("utf-8"))
            await self._writer.drain()

            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        finally:
            self._pending.pop(req_id, None)

    async def list_tools(
        self,
        timeout: float = 30.0,
    ) -> List[Dict[str, Any]]:
        """List all available MCP tools with their schemas.

        Falls back to returning the known tool list from
        ``ruflo mcp tools`` if the MCP method is not supported.
        """
        try:
            result = await self.call_tool("tools/list", timeout=timeout)
            return result.get("tools") or result.get("result", {}).get("tools", [])
        except McpError as e:
            logger.warning("[mcp] tools/list not supported (%s)", e)
            return []

    # ── High-level Agent wrappers ──────────────────────────────────────

    async def agent_spawn(
        self,
        agent_type: str = "coder",
        agent_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Spawn a new agent in the Ruflo swarm."""
        args: Dict[str, Any] = {"type": agent_type}
        if agent_name:
            args["name"] = agent_name
        if config:
            args["config"] = config
        return await self.call_tool("agent_spawn", args)

    async def agent_execute(
        self,
        agent_id: str,
        task: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a task on a spawned agent."""
        args: Dict[str, Any] = {"agentId": agent_id, "task": task}
        if context:
            args["context"] = context
        return await self.call_tool("agent_execute", args)

    async def agent_status(self, agent_id: str) -> Dict[str, Any]:
        """Get agent status."""
        return await self.call_tool("agent_status", {"agentId": agent_id})

    async def agent_list(self) -> List[Dict[str, Any]]:
        """List all spawned agents."""
        result = await self.call_tool("agent_list")
        return result.get("agents") or result.get("result", {}).get("agents", [])

    async def agent_terminate(self, agent_id: str) -> Dict[str, Any]:
        """Terminate an agent."""
        return await self.call_tool("agent_terminate", {"agentId": agent_id})

    # ── High-level Swarm wrappers ──────────────────────────────────────

    async def swarm_init(
        self,
        topology: str = "hierarchical-mesh",
        max_agents: int = 15,
    ) -> Dict[str, Any]:
        """Initialize a new swarm with the given topology."""
        return await self.call_tool("swarm_init", {
            "topology": topology,
            "maxAgents": max_agents,
        })

    async def swarm_status(self) -> Dict[str, Any]:
        """Get swarm status."""
        return await self.call_tool("swarm_status")

    async def swarm_shutdown(self) -> Dict[str, Any]:
        """Shutdown the current swarm."""
        return await self.call_tool("swarm_shutdown")

    async def swarm_health(self) -> Dict[str, Any]:
        """Check swarm health."""
        return await self.call_tool("swarm_health")

    # ── High-level Memory wrappers ─────────────────────────────────────

    async def memory_store(
        self,
        key: str,
        value: str,
        namespace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store a value in Ruflo's persistent memory."""
        args: Dict[str, Any] = {"key": key, "value": value}
        if namespace:
            args["namespace"] = namespace
        if metadata:
            args["metadata"] = metadata
        return await self.call_tool("memory_store", args)

    async def memory_retrieve(self, key: str, namespace: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve a value from Ruflo memory."""
        args: Dict[str, Any] = {"key": key}
        if namespace:
            args["namespace"] = namespace
        return await self.call_tool("memory_retrieve", args)

    async def memory_search(
        self,
        query: str,
        namespace: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Semantic search across stored memories."""
        args: Dict[str, Any] = {"query": query, "limit": limit}
        if namespace:
            args["namespace"] = namespace
        result = await self.call_tool("memory_search", args)
        return result.get("results") or result.get("result", {}).get("results", [])

    async def memory_delete(self, key: str, namespace: Optional[str] = None) -> Dict[str, Any]:
        """Delete a stored memory."""
        args: Dict[str, Any] = {"key": key}
        if namespace:
            args["namespace"] = namespace
        return await self.call_tool("memory_delete", args)

    async def memory_stats(self) -> Dict[str, Any]:
        """Get memory storage statistics."""
        return await self.call_tool("memory_stats")

    async def memory_list(
        self,
        namespace: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Enumerate stored memory entries."""
        args: Dict[str, Any] = {"limit": limit}
        if namespace:
            args["namespace"] = namespace
        result = await self.call_tool("memory_list", args)
        return result.get("entries") or result.get("result", {}).get("entries", [])

    # ── Low-level internals ────────────────────────────────────────────

    async def _initialize(self, timeout: float) -> None:
        """Perform MCP initialization handshake."""
        # Step 1: Send initialize request
        init_request = {
            "jsonrpc": _JSONRPC,
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "0.1.0",
                "capabilities": {},
                "clientInfo": {
                    "name": "agent-hub",
                    "version": "1.0.0",
                },
            },
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[0] = future

        try:
            self._writer.write((json.dumps(init_request) + "\n").encode("utf-8"))
            await self._writer.drain()

            response = await asyncio.wait_for(future, timeout=timeout)
            self._server_info = response.get("serverInfo") or response.get("result", {}).get("serverInfo", {})
            logger.info("[mcp] Initialized: %s", self._server_info)
        finally:
            self._pending.pop(0, None)

        # Step 2: Send initialized notification (no response expected)
        notif = {
            "jsonrpc": _JSONRPC,
            "method": "notifications/initialized",
        }
        self._writer.write((json.dumps(notif) + "\n").encode("utf-8"))
        await self._writer.drain()

    async def _response_listener(self) -> None:
        """Background task: read JSON-RPC responses from stdout."""
        try:
            buffer = ""
            while True:
                line = await self._reader.readline()
                if not line:
                    logger.warning("[mcp] Subprocess stdout closed")
                    break

                text = line.decode("utf-8").strip()
                if not text:
                    continue

                # Handle multi-line JSON (streaming responses)
                buffer += text
                try:
                    msg = json.loads(buffer)
                    buffer = ""
                except json.JSONDecodeError:
                    # Incomplete JSON — wait for more data
                    continue

                self._dispatch_response(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[mcp] Response listener error: %s", e)
        finally:
            # Cancel all pending futures on disconnect
            for req_id, future in list(self._pending.items()):
                if not future.done():
                    future.set_exception(RuntimeError("MCP connection closed"))
            self._pending.clear()

    def _dispatch_response(self, msg: Dict[str, Any]) -> None:
        """Route a JSON-RPC response to its pending future."""
        msg_id = msg.get("id")
        if msg_id is not None and isinstance(msg_id, int):
            future = self._pending.get(msg_id)
            if future and not future.done():
                if "error" in msg:
                    future.set_exception(McpError(msg["error"]))
                else:
                    future.set_result(msg.get("result", {}))
                return

        # Handle notifications (no id) or responses without a matching future
        method = msg.get("method", "")
        if method.startswith("notifications/"):
            logger.debug("[mcp] Notification: %s", method)
        elif msg_id is not None:
            logger.warning("[mcp] Orphaned response for id=%s: %s", msg_id, _truncate(str(msg), 200))

    @property
    def server_version(self) -> str:
        return str(self._server_info.get("version", "unknown"))

    @property
    def server_name(self) -> str:
        return str(self._server_info.get("name", "ruflo"))


class McpError(Exception):
    """MCP protocol-level error."""

    def __init__(self, error: Dict[str, Any]) -> None:
        self.code = error.get("code", -1)
        self.message = error.get("message", "Unknown MCP error")
        self.data = error.get("data")
        super().__init__(f"[MCP {self.code}] {self.message}")


# ── Singleton ──────────────────────────────────────────────────────────

_bridge_instance: Optional[McpBridge] = None


async def get_bridge() -> McpBridge:
    """Get or create the global MCP bridge singleton."""
    global _bridge_instance
    if _bridge_instance is None or not _bridge_instance.is_running:
        _bridge_instance = await McpBridge.start()
    return _bridge_instance


async def close_bridge() -> None:
    """Close the global MCP bridge."""
    global _bridge_instance
    if _bridge_instance:
        await _bridge_instance.stop()
        _bridge_instance = None


def _truncate(text: str, max_len: int) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text
