"""Compile a WorkflowDoc (from the frontend builder) into DAG stages.

Supported node types (Phase 1):
  - llm        — call an LLM with a prompt
  - http       — make an HTTP request
  - condition  — branch based on previous output
  - loop       — repeat a subgraph N times
  - tool       — invoke a registered tool/skill
  - knowledge_retrieve — stub for future RAG integration
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class CompiledNode:
    """A single executable node in the compiled workflow."""

    def __init__(
        self,
        node_id: str,
        node_type: str,
        label: str,
        config: Dict[str, Any],
        depends_on: List[str],
    ):
        self.node_id = node_id
        self.node_type = node_type
        self.label = label
        self.config = config
        self.depends_on = depends_on

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "label": self.label,
            "config": self.config,
            "depends_on": self.depends_on,
        }


class CompiledWorkflow:
    """Result of compiling a WorkflowDoc."""

    def __init__(self, name: str, nodes: List[CompiledNode]):
        self.name = name
        self.nodes = nodes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes],
        }


SUPPORTED_NODE_TYPES = {"llm", "http", "condition", "loop", "tool", "knowledge_retrieve"}


def compile_workflow(doc: Dict[str, Any]) -> CompiledWorkflow:
    """Compile a WorkflowDoc JSON into an executable CompiledWorkflow.

    The doc structure (from workflowBuilder.ts):
      {
        "name": "...",
        "nodes": [
          { "id": "...", "type": "llm", "data": { "label": "...", ... }, "position": {...} },
          ...
        ],
        "edges": [
          { "id": "...", "source": "node-1", "target": "node-2" },
          ...
        ]
      }
    """
    name = doc.get("name", "Unnamed Workflow")
    raw_nodes = doc.get("nodes", [])
    raw_edges = doc.get("edges", [])

    if not raw_nodes:
        raise ValueError("Workflow has no nodes")

    dep_map: Dict[str, List[str]] = {}
    for edge in raw_edges:
        source = edge.get("source", "")
        target = edge.get("target", "")
        if source and target:
            dep_map.setdefault(target, []).append(source)

    compiled_nodes: List[CompiledNode] = []
    seen_ids = set()

    for node in raw_nodes:
        node_id = node.get("id", "")
        if not node_id or node_id in seen_ids:
            continue
        seen_ids.add(node_id)

        node_type = node.get("type", "llm")
        data = node.get("data", {})

        if node_type not in SUPPORTED_NODE_TYPES:
            logger.warning("Unsupported node type '%s' for node '%s', treating as llm", node_type, node_id)
            node_type = "llm"

        label = data.get("label", node_id)
        config = _extract_config(node_type, data)
        depends = dep_map.get(node_id, [])

        compiled_nodes.append(CompiledNode(
            node_id=node_id,
            node_type=node_type,
            label=label,
            config=config,
            depends_on=depends,
        ))

    if not compiled_nodes:
        raise ValueError("No valid nodes after compilation")

    return CompiledWorkflow(name=name, nodes=compiled_nodes)


def _extract_config(node_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract node-type-specific config from the builder's data payload."""
    if node_type == "llm":
        return {
            "prompt": data.get("prompt", data.get("description", "")),
            "model": data.get("model", ""),
            "temperature": data.get("temperature", 0.7),
            "max_tokens": data.get("maxTokens", 2000),
            "system_prompt": data.get("systemPrompt", ""),
        }
    elif node_type == "http":
        return {
            "url": data.get("url", ""),
            "method": data.get("method", "GET"),
            "headers": data.get("headers", {}),
            "body": data.get("body", ""),
        }
    elif node_type == "condition":
        return {
            "expression": data.get("expression", ""),
            "true_branch": data.get("trueBranch", ""),
            "false_branch": data.get("falseBranch", ""),
        }
    elif node_type == "loop":
        return {
            "iterations": data.get("iterations", 1),
            "loop_body": data.get("loopBody", []),
        }
    elif node_type == "tool":
        return {
            "tool_name": data.get("toolName", ""),
            "arguments": data.get("arguments", {}),
        }
    elif node_type == "knowledge_retrieve":
        return {
            "query": data.get("query", ""),
            "top_k": data.get("topK", 5),
        }
    return {}
