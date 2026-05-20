"""GitHub MCP Bridge — stdio JSON-RPC 客户端

通过 stdio 子进程与 @modelcontextprotocol/server-github 通信，
将 GitHub API 暴露为 Agent 可调用的 MCP 工具。

用法:
    bridge = await GithubMcpBridge.start()
    repos = await bridge.call_tool("search_repositories", {"query": "fastapi"})
    await bridge.stop()

要求:
    - GITHUB_PERSONAL_ACCESS_TOKEN 环境变量
    - npx + @modelcontextprotocol/server-github
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JSONRPC = "2.0"


class GithubMcpBridge:
    """与 github-mcp-server 通信的 MCP stdio 客户端。"""

    def __init__(self, token: Optional[str] = None):
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._started = False
        self._token = token or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
        self._server_tools: List[Dict[str, Any]] = []

    @classmethod
    async def start(cls, token: Optional[str] = None) -> "GithubMcpBridge":
        bridge = cls(token=token)
        await bridge._launch()
        return bridge

    async def _launch(self) -> None:
        env = os.environ.copy()
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = self._token

        self._process = await asyncio.create_subprocess_exec(
            "npx", "-y", "@modelcontextprotocol/server-github",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader = self._process.stdout
        self._writer = self._process.stdin

        # MCP 初始化握手
        await self._send_request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "agent-hub", "version": "0.1"},
        })
        # 发送 initialized 通知
        await self._send_notification("notifications/initialized", {})

        # 获取工具列表
        tools_result = await self._send_request("tools/list", {})
        self._server_tools = tools_result.get("tools", [])
        self._started = True

        self._listener_task = asyncio.create_task(self._listen())

        logger.info(
            "github-mcp started, %d tools available: %s",
            len(self._server_tools),
            [t.get("name") for t in self._server_tools],
        )

    async def _listen(self) -> None:
        """监听来自服务器的通知/请求（静默处理）。"""
        try:
            while self._reader and not self._reader.at_eof():
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                    rid = msg.get("id")
                    if rid is not None and rid in self._pending:
                        future = self._pending.pop(rid)
                        if "result" in msg:
                            future.set_result(msg["result"])
                        elif "error" in msg:
                            future.set_exception(
                                Exception(msg["error"].get("message", "MCP error"))
                            )
                except json.JSONDecodeError:
                    continue
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("github-mcp listener stopped", exc_info=True)

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._request_id += 1
        rid = self._request_id
        payload = {"jsonrpc": _JSONRPC, "id": rid, "method": method, "params": params}

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = future

        self._writer.write((json.dumps(payload) + "\n").encode())
        await self._writer.drain()

        return await asyncio.wait_for(future, timeout=30.0)

    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        payload = {"jsonrpc": _JSONRPC, "method": method, "params": params}
        self._writer.write((json.dumps(payload) + "\n").encode())
        await self._writer.drain()

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """调用 GitHub MCP 工具，返回文本结果。"""
        if not self._started:
            raise RuntimeError("github-mcp not started")
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        # 提取文本内容
        content = result.get("content", [])
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return self._server_tools

    async def stop(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._process:
            try:
                self._process.stdin.close()
            except Exception:
                pass
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            except Exception:
                pass
            self._process = None
        self._started = False
