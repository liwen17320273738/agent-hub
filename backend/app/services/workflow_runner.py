"""Execute a compiled workflow by running each node in dependency order.

Phase 1: sequential execution with dependency resolution.
Future: parallel execution via asyncio.gather for independent nodes.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from .workflow_compiler import CompiledWorkflow, CompiledNode
from .llm_router import chat_completion
from .sse import emit_event

logger = logging.getLogger(__name__)


class WorkflowRunResult:
    def __init__(self, workflow_name: str, run_id: str):
        self.workflow_name = workflow_name
        self.run_id = run_id
        self.node_results: Dict[str, Dict[str, Any]] = {}
        self.status: str = "running"
        self.error: Optional[str] = None
        self.elapsed_ms: float = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "node_results": self.node_results,
        }


async def run_workflow(workflow: CompiledWorkflow, run_id: Optional[str] = None) -> WorkflowRunResult:
    """Execute all nodes in a compiled workflow respecting dependencies."""
    rid = run_id or str(uuid.uuid4())
    result = WorkflowRunResult(workflow.name, rid)
    start = time.monotonic()

    await emit_event("workflow:start", {"run_id": rid, "name": workflow.name})

    node_map = {n.node_id: n for n in workflow.nodes}
    completed: set[str] = set()

    try:
        execution_order = _topological_sort(workflow.nodes)
    except ValueError as e:
        result.status = "failed"
        result.error = str(e)
        return result

    for node_id in execution_order:
        node = node_map[node_id]

        await emit_event("workflow:node-start", {
            "run_id": rid, "node_id": node_id, "label": node.label, "type": node.node_type,
        })

        try:
            node_output = await _execute_node(node, result.node_results)
            result.node_results[node_id] = {
                "status": "done",
                "output": node_output,
            }
            completed.add(node_id)
            await emit_event("workflow:node-done", {
                "run_id": rid, "node_id": node_id, "status": "done",
            })
        except Exception as e:
            logger.error("Workflow node %s failed: %s", node_id, e)
            result.node_results[node_id] = {
                "status": "failed",
                "error": str(e),
            }
            await emit_event("workflow:node-error", {
                "run_id": rid, "node_id": node_id, "error": str(e),
            })
            result.status = "failed"
            result.error = f"Node {node.label} failed: {e}"
            break

    if result.status == "running":
        result.status = "done"

    result.elapsed_ms = (time.monotonic() - start) * 1000
    await emit_event("workflow:done", {
        "run_id": rid, "status": result.status, "elapsed_ms": result.elapsed_ms,
    })
    return result


def _topological_sort(nodes: List[CompiledNode]) -> List[str]:
    """Kahn's algorithm for topological ordering."""
    in_degree: Dict[str, int] = {}
    adjacency: Dict[str, List[str]] = {}
    all_ids = set()

    for node in nodes:
        all_ids.add(node.node_id)
        in_degree.setdefault(node.node_id, 0)
        adjacency.setdefault(node.node_id, [])

    for node in nodes:
        for dep in node.depends_on:
            if dep in all_ids:
                adjacency.setdefault(dep, []).append(node.node_id)
                in_degree[node.node_id] = in_degree.get(node.node_id, 0) + 1

    queue = [nid for nid in all_ids if in_degree.get(nid, 0) == 0]
    order: List[str] = []

    while queue:
        queue.sort()
        current = queue.pop(0)
        order.append(current)
        for neighbor in adjacency.get(current, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(all_ids):
        raise ValueError("Workflow contains a cycle")

    return order


async def _execute_node(node: CompiledNode, prior_results: Dict[str, Dict[str, Any]]) -> str:
    """Execute a single node based on its type."""
    config = node.config

    if node.node_type == "llm":
        return await _exec_llm(config, prior_results, node.depends_on)
    elif node.node_type == "http":
        return await _exec_http(config)
    elif node.node_type == "condition":
        return _exec_condition(config, prior_results, node.depends_on)
    elif node.node_type == "tool":
        return f"[Tool stub] {config.get('tool_name', 'unknown')}: tool execution not yet implemented"
    elif node.node_type == "knowledge_retrieve":
        return f"[RAG stub] query='{config.get('query', '')}': knowledge retrieval not yet implemented"
    elif node.node_type == "loop":
        return f"[Loop stub] iterations={config.get('iterations', 1)}: loop execution not yet implemented"
    else:
        return f"[Unknown node type: {node.node_type}]"


async def _exec_llm(
    config: Dict[str, Any],
    prior_results: Dict[str, Dict[str, Any]],
    depends_on: List[str],
) -> str:
    """Call LLM with prompt, injecting prior node outputs as context."""
    prompt = config.get("prompt", "")
    system_prompt = config.get("system_prompt", "")

    context_parts: List[str] = []
    for dep_id in depends_on:
        dep_result = prior_results.get(dep_id, {})
        if dep_result.get("output"):
            context_parts.append(f"[{dep_id}的输出]:\n{dep_result['output']}")

    if context_parts:
        full_prompt = "以下是上游节点的输出:\n\n" + "\n\n".join(context_parts) + "\n\n---\n\n" + prompt
    else:
        full_prompt = prompt

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": full_prompt})

    from ..config import settings
    model = config.get("model") or settings.llm_model or "deepseek-chat"

    try:
        result = await chat_completion(
            model=model,
            messages=messages,
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 2000),
        )
        return result.get("content", result.get("text", str(result)))
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}") from e


async def _exec_http(config: Dict[str, Any]) -> str:
    """Make an HTTP request."""
    url = config.get("url", "")
    if not url:
        raise ValueError("HTTP node requires a URL")

    method = config.get("method", "GET").upper()
    headers = config.get("headers", {})
    body = config.get("body", "")

    async with httpx.AsyncClient(timeout=30) as client:
        if method == "GET":
            resp = await client.get(url, headers=headers)
        elif method == "POST":
            resp = await client.post(url, headers=headers, content=body)
        elif method == "PUT":
            resp = await client.put(url, headers=headers, content=body)
        elif method == "DELETE":
            resp = await client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

    return resp.text[:5000]


def _exec_condition(
    config: Dict[str, Any],
    prior_results: Dict[str, Dict[str, Any]],
    depends_on: List[str],
) -> str:
    """Evaluate a simple condition based on prior outputs."""
    expression = config.get("expression", "")
    if not expression:
        return "true"

    prev_output = ""
    if depends_on:
        dep = prior_results.get(depends_on[0], {})
        prev_output = dep.get("output", "")

    expr_lower = expression.lower()
    if "contains:" in expr_lower:
        keyword = expression.split(":", 1)[1].strip()
        return "true" if keyword.lower() in prev_output.lower() else "false"

    return "true"
