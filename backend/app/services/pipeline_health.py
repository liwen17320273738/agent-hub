"""
Pipeline Health Check — OpenClaw → Claude → Hermes 链路诊断

Diagnoses the full Agent Hub pipeline and provides actionable fix recommendations.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def diagnose_pipeline_health() -> Dict[str, Any]:
    """
    Run full pipeline health check.

    Returns a comprehensive health report with:
    - OpenClaw intake status
    - Claude executor status
    - Hermes gate status
    - LLM model availability
    - Structured output support
    - Fix recommendations
    """
    results = {
        "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        "components": {},
        "overall_status": "healthy",
        "blockers": [],
        "warnings": [],
        "fixes": [],
    }

    # 1. OpenClaw — intake gateway
    results["components"]["openclaw"] = await _check_openclaw()

    # 2. Claude — executor
    results["components"]["claude_executor"] = await _check_claude_executor()

    # 3. Hermes — quality gate
    results["components"]["hermes_gate"] = await _check_hermes_gate()

    # 4. LLM models — availability
    results["components"]["llm_models"] = await _check_llm_models()

    # 5. Structured output capability
    results["components"]["structured_output"] = _check_structured_output()

    # Aggregate
    for comp, status in results["components"].items():
        if status.get("status") == "down":
            results["blockers"].append(comp)
            results["overall_status"] = "degraded"
        elif status.get("status") == "degraded":
            results["warnings"].append(comp)

    if results["blockers"]:
        results["overall_status"] = "blocked"

    return results


async def _check_openclaw() -> Dict[str, Any]:
    """Check OpenClaw intake gateway"""
    status = {"status": "healthy", "checks": []}

    # Check gateway router is registered
    try:
        from ..api.gateway import router
        status["checks"].append({"check": "gateway_router", "ok": True, "detail": "Gateway router registered"})
    except Exception as e:
        status["checks"].append({"check": "gateway_router", "ok": False, "detail": str(e)})
        status["status"] = "degraded"

    # Check relay API
    try:
        from ..api.relay import router
        status["checks"].append({"check": "relay_api", "ok": True, "detail": "Relay API available"})
    except Exception:
        status["checks"].append({"check": "relay_api", "ok": False, "detail": "Relay API not loaded"})
        status["status"] = "degraded"

    # Check SSE events
    try:
        from ..services.sse import emit_event
        status["checks"].append({"check": "sse_events", "ok": True, "detail": "SSE event system available"})
    except Exception:
        status["checks"].append({"check": "sse_events", "ok": False, "detail": "SSE not available"})

    return status


async def _check_claude_executor() -> Dict[str, Any]:
    """Check Claude Code executor availability"""
    status = {"status": "healthy", "checks": []}
    fixes = []

    # Check Claude CLI
    claude_path = os.environ.get("CLAUDE_PATH") or shutil.which("claude")
    if claude_path:
        status["checks"].append({
            "check": "claude_cli",
            "ok": True,
            "detail": f"Claude CLI found: {claude_path}",
        })
    else:
        status["checks"].append({
            "check": "claude_cli",
            "ok": False,
            "detail": "Claude CLI not found. Install: npm i -g @anthropic-ai/claude-code",
        })
        status["status"] = "degraded"
        fixes.append("npm install -g @anthropic-ai/claude-code")

    # Check Anthropic API key (accepts sk-ant-*, local proxy keys, or any non-empty key)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key and len(anthropic_key) > 10:
        key_prefix = anthropic_key[:20] + "..." if len(anthropic_key) > 20 else anthropic_key
        status["checks"].append({
            "check": "anthropic_api_key",
            "ok": True,
            "detail": f"Anthropic API key configured ({key_prefix})",
        })
    elif anthropic_key:
        status["checks"].append({
            "check": "anthropic_api_key",
            "ok": True,
            "detail": "Anthropic API key configured (custom format)",
        })
    else:
        status["checks"].append({
            "check": "anthropic_api_key",
            "ok": False,
            "detail": "ANTHROPIC_API_KEY not set or invalid format",
        })
        status["status"] = "degraded"
        fixes.append("Set ANTHROPIC_API_KEY in .env (starts with sk-ant-)")

    # Check executor bridge
    try:
        from ..services.executor_bridge import execute_claude_code
        status["checks"].append({
            "check": "executor_bridge",
            "ok": True,
            "detail": "Executor bridge loaded",
        })
    except Exception as e:
        status["checks"].append({"check": "executor_bridge", "ok": False, "detail": str(e)})

    # Check sandbox work dirs
    try:
        from ..services.executor_bridge import ALLOWED_WORK_DIRS
        status["checks"].append({
            "check": "sandbox_dirs",
            "ok": len(ALLOWED_WORK_DIRS) > 0,
            "detail": f"{len(ALLOWED_WORK_DIRS)} allowed work directories",
        })
    except Exception:
        status["checks"].append({"check": "sandbox_dirs", "ok": False, "detail": "No work directories configured"})

    if fixes:
        status["fixes"] = fixes

    return status


async def _check_hermes_gate() -> Dict[str, Any]:
    """Check Hermes quality gate"""
    status = {"status": "healthy", "checks": []}

    # Check self_verify
    try:
        from ..services.self_verify import verify_stage_output
        status["checks"].append({
            "check": "self_verify",
            "ok": True,
            "detail": "Self-verification engine loaded",
        })
    except Exception as e:
        status["checks"].append({"check": "self_verify", "ok": False, "detail": str(e)})

    # Check guardrails
    try:
        from ..services.guardrails import evaluate_guardrail
        status["checks"].append({
            "check": "guardrails",
            "ok": True,
            "detail": "Guardrails engine loaded",
        })
    except Exception:
        status["checks"].append({"check": "guardrails", "ok": False, "detail": "Guardrails not loaded"})

    # Check AI defence (new P3 module)
    try:
        from ..services.ai_defence import get_ai_defence
        defence = get_ai_defence()
        status["checks"].append({
            "check": "ai_defence",
            "ok": True,
            "detail": "AIDefence security engine loaded",
        })
    except Exception:
        status["checks"].append({"check": "ai_defence", "ok": False, "detail": "AIDefence not loaded"})

    # Check human_gate pipeline integration
    try:
        from ..services.pipeline_engine import STAGE_ROLE_PROMPTS
        gate_stages = [s for s, c in STAGE_ROLE_PROMPTS.items() if c.get("human_gate")]
        status["checks"].append({
            "check": "human_gates",
            "ok": True,
            "detail": f"{len(gate_stages)} stages with human approval gates: {gate_stages}",
        })
    except Exception as e:
        status["checks"].append({"check": "human_gates", "ok": False, "detail": str(e)})

    return status


async def _check_llm_models() -> Dict[str, Any]:
    """Check LLM model availability"""
    status = {"status": "healthy", "checks": [], "available_providers": []}

    from ..config import settings
    provider_keys = settings.get_provider_keys()

    # Check each provider
    providers = {
        "deepseek": "DeepSeek (best for structured output)",
        "anthropic": "Anthropic Claude (best reasoning)",
        "openai": "OpenAI (full capabilities)",
        "zhipu": "Zhipu GLM (⚠️ no JSON mode)",
        "google": "Google Gemini",
        "qwen": "Qwen (Alibaba)",
    }

    for provider, description in providers.items():
        key = provider_keys.get(provider)
        if key and key not in ("", "sk-your-key-here", "your-key-here"):
            status["checks"].append({
                "check": f"{provider}_available",
                "ok": True,
                "detail": f"{description} — API key configured",
            })
            status["available_providers"].append(provider)
        else:
            status["checks"].append({
                "check": f"{provider}_available",
                "ok": False,
                "detail": f"{description} — NO API key configured",
            })

    # Critical: check if we have at least ONE structured-output-capable model
    json_capable = [p for p in status["available_providers"] if p in ("deepseek", "anthropic", "openai", "google")]
    if not json_capable:
        status["status"] = "degraded"
        status["fix"] = (
            "NO models with structured output support available. "
            "zhipu GLM does not support response_format/json_object. "
            "Configure DEEPSEEK_API_KEY or ANTHROPIC_API_KEY or OPENAI_API_KEY in .env"
        )

    # Provider-specific model health
    try:
        from ..services.llm_router import get_provider_health
        provider_health = get_provider_health()
        status["provider_health"] = provider_health
    except Exception:
        pass

    return status


def _check_structured_output() -> Dict[str, Any]:
    """Check structured output capability"""
    status = {"status": "healthy", "checks": []}

    from ..services.planner_worker import (
        STRUCTURED_OUTPUT_STAGES,
        MODEL_CAPABILITIES,
        TIER_MODELS,
        resolve_model,
    )

    # Check which stages need structured output
    status["checks"].append({
        "check": "structured_stages",
        "ok": True,
        "detail": f"{len(STRUCTURED_OUTPUT_STAGES)} stages require structured output",
    })

    # Check model capability matrix
    json_models = [m for m, caps in MODEL_CAPABILITIES.items() if caps["supports_json_mode"]]
    no_json_models = [m for m, caps in MODEL_CAPABILITIES.items() if not caps["supports_json_mode"]]

    status["checks"].append({
        "check": "json_capable_models",
        "ok": len(json_models) > 0,
        "detail": f"JSON-capable: {json_models}. ⚠️ No JSON: {no_json_models}",
    })

    # Simulate model resolution for planning stage
    try:
        result = resolve_model(
            role="Agent-ceo",
            stage_id="planning",
            requires_structured_output=True,
        )
        status["checks"].append({
            "check": "planning_model_resolution",
            "ok": True,
            "detail": f"Planning would use: {result['model']} ({result.get('reason', '')})",
        })
    except Exception as e:
        status["checks"].append({
            "check": "planning_model_resolution",
            "ok": False,
            "detail": f"Failed to resolve model: {e}",
        })
        status["status"] = "degraded"

    # Check for the specific zhipu + structured output conflict
    for tier, models in TIER_MODELS.items():
        tier_ok = any(
            MODEL_CAPABILITIES.get(m["id"], {}).get("supports_json_mode", False)
            for m in models
        )
        if not tier_ok:
            status["checks"].append({
                "check": f"tier_{tier.value}_json_aware",
                "ok": False,
                "detail": f"Tier {tier.value} has NO JSON-capable model in its list",
            })
            status["status"] = "degraded"

    return status


def print_health_report(report: Dict[str, Any]) -> str:
    """Format health report as readable text"""
    lines = ["=" * 60, " Agent Hub Pipeline Health Check", "=" * 60, ""]

    lines.append(f"Overall Status: {report['overall_status'].upper()}")
    lines.append(f"Timestamp: {report['timestamp']}")
    lines.append("")

    for comp_name, comp in report["components"].items():
        status_icon = "✅" if comp["status"] == "healthy" else ("⚠️" if comp["status"] == "degraded" else "❌")
        lines.append(f"{status_icon} {comp_name}: {comp['status']}")

        for check in comp.get("checks", []):
            icon = "  ✅" if check["ok"] else "  ❌"
            lines.append(f"{icon} {check['check']}: {check.get('detail', '')}")

        if comp.get("fixes"):
            lines.append("  🔧 Fixes:")
            for fix in comp["fixes"]:
                lines.append(f"     $ {fix}")

        lines.append("")

    if report["blockers"]:
        lines.append(f"❌ BLOCKERS ({len(report['blockers'])}):")
        for b in report["blockers"]:
            lines.append(f"  - {b}")

    if report["warnings"]:
        lines.append(f"⚠️ WARNINGS ({len(report['warnings'])}):")
        for w in report["warnings"]:
            lines.append(f"  - {w}")

    lines.append("=" * 60)

    return "\n".join(lines)
