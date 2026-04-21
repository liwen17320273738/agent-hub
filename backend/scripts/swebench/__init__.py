"""SWE-Bench runner for agent-hub.

This package is intentionally decoupled from the FastAPI app:

* It reuses ``app.services.llm_router.chat_completion`` for LLM calls
* It reuses ``app.services.tools.docker_sandbox.docker_exec`` when Docker is
  available; otherwise it shells out locally (clearly logged)
* It does NOT touch Postgres, Redis, the DAG orchestrator, or any
  agent-hub web concerns. SWE-Bench has its own per-instance state.

Public surface (stable):

* :func:`scripts.swebench.dataset.load_instances`
* :func:`scripts.swebench.patch_utils.extract_unified_diff`
* :func:`scripts.swebench.repo_workspace.RepoWorkspace`
* :func:`scripts.swebench.agent.run_agentless_attempt`
* :func:`scripts.swebench.evaluator.evaluate_patch`
* CLI entry: ``python -m scripts.swebench --help``
"""
from __future__ import annotations

__all__ = [
    "dataset",
    "patch_utils",
    "repo_workspace",
    "agent",
    "evaluator",
]
