"""
Quality Gates — Enforceable quality checkpoints between pipeline stages.

Each stage has configurable quality gate criteria that must be met before
the pipeline proceeds. Gates are evaluated after self-verify + peer review.

Gate evaluation layers:
1. Heuristic checks (from self_verify) — format, length, sections, keywords
2. LLM-based deep evaluation — semantic completeness, cross-stage consistency
3. Deliverable completeness — required sections and artifacts present
4. Threshold enforcement — configurable pass/warn/fail thresholds per template

Gate results:
- PASSED: all criteria met, pipeline proceeds
- WARNING: minor issues, pipeline proceeds with advisory
- FAILED: critical issues, pipeline blocks (requires override or rework)
- BYPASSED: human override granted
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .self_verify import verify_stage_output, VerifyStatus, StageVerification
from .llm_router import chat_completion as llm_chat

logger = logging.getLogger(__name__)


class GateStatus(str, Enum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    BYPASSED = "bypassed"
    PENDING = "pending"


class GateCheck(BaseModel):
    name: str
    category: str  # heuristic | llm | deliverable | threshold
    status: GateStatus
    score: float  # 0.0 - 1.0
    message: str
    details: Optional[str] = None


class GateResult(BaseModel):
    stage_id: str
    template: Optional[str] = None
    overall_status: GateStatus
    overall_score: float
    checks: List[GateCheck]
    can_proceed: bool
    block_reason: Optional[str] = None
    suggestions: List[str] = []


DELIVERABLE_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "planning": {
        "label": "PRD（产品需求文档）",
        "required_sections": [
            "需求概述", "目标用户", "功能范围", "用户故事",
            "验收标准", "非功能需求", "里程碑",
        ],
        "required_keywords": ["验收标准", "用户故事"],
        "min_length": 800,
        "pass_threshold": 0.7,
        "fail_threshold": 0.4,
    },
    "architecture": {
        "label": "技术架构方案",
        "required_sections": [
            "技术选型", "系统架构", "数据模型", "API 设计",
            "实现路线图", "风险",
        ],
        "required_keywords": ["API", "数据模型"],
        "min_length": 1000,
        "pass_threshold": 0.7,
        "fail_threshold": 0.4,
    },
    "development": {
        "label": "代码实现",
        "required_sections": [
            "项目结构", "核心代码", "配置",
        ],
        "required_keywords": ["```"],
        "min_length": 1500,
        "pass_threshold": 0.6,
        "fail_threshold": 0.3,
    },
    "testing": {
        "label": "测试验证报告",
        "required_sections": [
            "测试范围", "测试用例", "结论",
        ],
        "required_keywords": ["PASS", "NEEDS WORK", "结论"],
        "keyword_mode": "any",
        "min_length": 600,
        "pass_threshold": 0.7,
        "fail_threshold": 0.4,
    },
    "reviewing": {
        "label": "验收评审报告",
        "required_sections": [
            "评分", "需求覆盖", "结论",
        ],
        "required_keywords": ["APPROVED", "REJECTED"],
        "keyword_mode": "any",
        "min_length": 400,
        "pass_threshold": 0.6,
        "fail_threshold": 0.3,
    },
    "deployment": {
        "label": "部署方案",
        "required_sections": [
            "环境", "Docker", "CI/CD", "回滚",
        ],
        "required_keywords": ["docker", "Docker", "CI", "回滚"],
        "keyword_mode": "any",
        "min_length": 500,
        "pass_threshold": 0.6,
        "fail_threshold": 0.3,
    },
    "design": {
        "label": "UI/UX 设计规范",
        "required_sections": [
            "设计 Token", "页面布局", "组件清单",
        ],
        "required_keywords": ["主色", "字号", "间距"],
        "keyword_mode": "any",
        "min_length": 800,
        "pass_threshold": 0.65,
        "fail_threshold": 0.35,
    },
    "security-review": {
        "label": "安全审计报告",
        "required_sections": ["类别", "修复建议"],
        "required_keywords": ["SECURITY: PASS", "SECURITY: BLOCK"],
        "keyword_mode": "any",
        "min_length": 500,
        "pass_threshold": 0.65,
        "fail_threshold": 0.35,
    },
    "legal-review": {
        "label": "合规审查报告",
        "required_sections": ["数据收集", "隐私政策"],
        "required_keywords": ["LEGAL: PASS", "LEGAL: CONDITIONAL", "LEGAL: BLOCK"],
        "keyword_mode": "any",
        "min_length": 500,
        "pass_threshold": 0.6,
        "fail_threshold": 0.3,
    },
    "data-modeling": {
        "label": "指标与埋点设计",
        "required_sections": ["北极星指标", "事件名"],
        "required_keywords": ["指标", "埋点"],
        "keyword_mode": "any",
        "min_length": 500,
        "pass_threshold": 0.6,
        "fail_threshold": 0.3,
    },
    "marketing-launch": {
        "label": "上线营销包",
        "required_sections": ["定位", "渠道", "节奏表"],
        "required_keywords": ["KPI", "落地页", "节奏"],
        "keyword_mode": "any",
        "min_length": 400,
        "pass_threshold": 0.55,
        "fail_threshold": 0.3,
    },
    "finance-review": {
        "label": "商业可持续性评估",
        "required_sections": ["成本拆解", "收入模型"],
        "required_keywords": ["CAC", "LTV", "盈亏平衡"],
        "keyword_mode": "any",
        "min_length": 500,
        "pass_threshold": 0.6,
        "fail_threshold": 0.3,
    },
}

TEMPLATE_GATE_OVERRIDES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "full": {},
    "web_app": {
        "development": {"min_length": 2000, "pass_threshold": 0.7},
        "testing": {"pass_threshold": 0.75},
    },
    "api_service": {
        "architecture": {"required_sections": [
            "技术选型", "接口设计", "数据模型", "认证方案", "限流策略",
        ]},
        "testing": {"required_keywords": ["安全", "性能"], "keyword_mode": "any"},
    },
    "data_pipeline": {
        "architecture": {"required_sections": [
            "数据源", "ETL 流程", "数据质量", "监控",
        ]},
        "testing": {"required_sections": [
            "数据质量验证", "端到端测试", "性能测试",
        ]},
    },
    "bug_fix": {
        "planning": {"min_length": 300, "pass_threshold": 0.5, "fail_threshold": 0.2},
        "development": {"min_length": 500, "pass_threshold": 0.5},
    },
    "simple": {
        "planning": {"min_length": 300, "pass_threshold": 0.5, "fail_threshold": 0.2},
        "development": {"min_length": 500, "pass_threshold": 0.5},
    },
    "microservice": {
        "architecture": {"required_sections": [
            "服务边界", "API 契约", "数据隔离", "服务通信", "部署拓扑",
        ]},
        "development": {"min_length": 2000},
        "testing": {"required_sections": [
            "单元测试", "集成测试", "契约测试",
        ]},
    },
    "fullstack_saas": {
        "planning": {"min_length": 1200, "pass_threshold": 0.8},
        "architecture": {"min_length": 1500, "pass_threshold": 0.8},
        "development": {"min_length": 3000, "pass_threshold": 0.7},
        "testing": {"pass_threshold": 0.8},
    },
    "mobile_app": {
        "architecture": {"required_sections": [
            "技术选型", "UI 架构", "状态管理", "离线策略", "API 层",
        ]},
        "testing": {"required_sections": [
            "UI 测试", "集成测试", "设备兼容性",
        ]},
    },
}


def _get_stage_config(
    stage_id: str,
    template: Optional[str] = None,
    task_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge base requirements with template-specific overrides AND per-task
    overrides (highest precedence).

    Precedence order:
        1. ``DELIVERABLE_REQUIREMENTS[stage_id]`` — global defaults
        2. ``TEMPLATE_GATE_OVERRIDES[template][stage_id]`` — template tweaks
        3. ``task_overrides[stage_id]`` — per-task overrides set via the
           dashboard's "门禁阈值" drawer (lives on
           ``PipelineTask.quality_gate_config`` JSONB)

    The third layer is intentionally additive: a missing key falls through to
    the template/global default, so the UI only has to round-trip the keys
    the operator actually changed.
    """
    base = dict(DELIVERABLE_REQUIREMENTS.get(stage_id, {}))
    if template and template in TEMPLATE_GATE_OVERRIDES:
        base.update(TEMPLATE_GATE_OVERRIDES[template].get(stage_id, {}))
    if task_overrides:
        per_stage = task_overrides.get(stage_id) or {}
        if isinstance(per_stage, dict):
            base.update(per_stage)
    return base


def get_effective_gate_config(
    stage_id: str,
    *,
    template: Optional[str] = None,
    task_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Public wrapper for the API/UI: returns the same merged config that
    ``evaluate_quality_gate`` will see. Used by the "门禁阈值" drawer to
    populate sliders with the actual current values."""
    return _get_stage_config(stage_id, template, task_overrides)


def _check_deliverable_sections(output: str, config: Dict[str, Any]) -> GateCheck:
    """Check if required deliverable sections are present."""
    required = config.get("required_sections", [])
    if not required:
        return GateCheck(
            name="deliverable_sections", category="deliverable",
            status=GateStatus.PASSED, score=1.0,
            message="无必要章节要求",
        )

    found = sum(1 for sec in required if sec in output)
    ratio = found / len(required)

    if ratio >= 0.8:
        return GateCheck(
            name="deliverable_sections", category="deliverable",
            status=GateStatus.PASSED, score=ratio,
            message=f"包含 {found}/{len(required)} 个必要章节",
        )
    elif ratio >= 0.5:
        missing = [sec for sec in required if sec not in output]
        return GateCheck(
            name="deliverable_sections", category="deliverable",
            status=GateStatus.WARNING, score=ratio,
            message=f"缺少部分章节: {', '.join(missing[:3])}",
        )
    else:
        missing = [sec for sec in required if sec not in output]
        return GateCheck(
            name="deliverable_sections", category="deliverable",
            status=GateStatus.FAILED, score=ratio,
            message=f"缺少关键章节: {', '.join(missing[:5])}",
        )


def _check_deliverable_keywords(output: str, config: Dict[str, Any]) -> GateCheck:
    """Check required keywords presence."""
    keywords = config.get("required_keywords", [])
    if not keywords:
        return GateCheck(
            name="deliverable_keywords", category="deliverable",
            status=GateStatus.PASSED, score=1.0, message="无必要关键词要求",
        )

    mode = config.get("keyword_mode", "all")
    found = [kw for kw in keywords if kw in output]

    if mode == "any":
        if found:
            return GateCheck(
                name="deliverable_keywords", category="deliverable",
                status=GateStatus.PASSED, score=1.0,
                message=f"包含关键结论: {', '.join(found[:3])}",
            )
        return GateCheck(
            name="deliverable_keywords", category="deliverable",
            status=GateStatus.FAILED, score=0.0,
            message=f"缺少结论关键词 (需包含至少一个): {', '.join(keywords[:5])}",
        )

    ratio = len(found) / len(keywords)
    if ratio >= 0.8:
        return GateCheck(
            name="deliverable_keywords", category="deliverable",
            status=GateStatus.PASSED, score=ratio,
            message=f"包含 {len(found)}/{len(keywords)} 个必要关键词",
        )
    return GateCheck(
        name="deliverable_keywords", category="deliverable",
        status=GateStatus.WARNING, score=ratio,
        message=f"缺少关键词: {', '.join(set(keywords) - set(found))}",
    )


def _check_length_gate(output: str, config: Dict[str, Any]) -> GateCheck:
    """Length gate with configurable threshold."""
    min_len = config.get("min_length", 300)
    actual = len(output.strip())
    ratio = min(actual / min_len, 1.0) if min_len > 0 else 1.0

    if actual >= min_len:
        return GateCheck(
            name="content_length", category="heuristic",
            status=GateStatus.PASSED, score=ratio,
            message=f"内容长度 {actual} 字符 (要求 ≥{min_len})",
        )
    elif actual >= min_len * 0.5:
        return GateCheck(
            name="content_length", category="heuristic",
            status=GateStatus.WARNING, score=ratio,
            message=f"内容偏短 {actual}/{min_len} 字符",
        )
    return GateCheck(
        name="content_length", category="heuristic",
        status=GateStatus.FAILED, score=ratio,
        message=f"内容过短 {actual}/{min_len} 字符",
    )


def _heuristic_to_gate_check(verify: StageVerification) -> GateCheck:
    """Convert heuristic self-verify result to a gate check."""
    status_map = {
        VerifyStatus.PASS: GateStatus.PASSED,
        VerifyStatus.WARN: GateStatus.WARNING,
        VerifyStatus.FAIL: GateStatus.FAILED,
    }
    score_map = {
        VerifyStatus.PASS: 1.0,
        VerifyStatus.WARN: 0.6,
        VerifyStatus.FAIL: 0.2,
    }
    failed_names = [c.check_name for c in verify.checks if c.status != VerifyStatus.PASS]
    detail = f"Details: {', '.join(failed_names)}" if failed_names else None

    return GateCheck(
        name="heuristic_verify", category="heuristic",
        status=status_map[verify.overall_status],
        score=score_map[verify.overall_status],
        message=f"启发式验证: {verify.overall_status.value.upper()} ({len(verify.checks)} 项检查)",
        details=detail,
    )


async def _llm_quality_evaluation(
    stage_id: str,
    output: str,
    config: Dict[str, Any],
    previous_outputs: Optional[Dict[str, str]] = None,
) -> GateCheck:
    """LLM-based deep quality evaluation."""
    label = config.get("label", stage_id)

    system_prompt = f"""你是一位资深的质量审查专家。请对以下「{label}」产出进行深度质量评估。

评估维度（每项 1-10 分）：
1. **完整性** — 是否覆盖了所有必要内容？
2. **准确性** — 内容是否正确、无矛盾？
3. **清晰度** — 表述是否清晰、无歧义？
4. **专业性** — 是否达到行业专业标准？
5. **可执行性** — 后续阶段是否能基于此产出直接开展工作？

输出格式（严格遵守）：
SCORE: <平均分，取整数 1-10>
VERDICT: <PASS 或 WARN 或 FAIL>
SUMMARY: <一句话总结>
ISSUES: <主要问题列表，每行一条，以 - 开头>"""

    user_msg = f"## 待评估产出：{label}\n\n{output[:4000]}"
    if previous_outputs:
        context = "\n".join(
            f"## 前序阶段 — {sid}\n{out[:1000]}"
            for sid, out in list(previous_outputs.items())[:3]
            if out and sid != stage_id
        )
        if context:
            user_msg = context + "\n\n" + user_msg

    try:
        from ..config import settings as app_settings
        model = app_settings.llm_model or "deepseek-chat"
        api_url = app_settings.llm_api_url or ""

        result = await llm_chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            api_url=api_url,
        )

        if result.get("error"):
            raise RuntimeError(result["error"])

        content = result.get("content", "")
        score, verdict, summary, issues = _parse_llm_evaluation(content)

        score_normalized = score / 10.0
        status = {
            "PASS": GateStatus.PASSED,
            "WARN": GateStatus.WARNING,
            "FAIL": GateStatus.FAILED,
        }.get(verdict, GateStatus.WARNING)

        return GateCheck(
            name="llm_quality", category="llm",
            status=status, score=score_normalized,
            message=f"LLM 质量评估: {score}/10 — {summary}",
            details=issues if issues else None,
        )
    except Exception as e:
        logger.warning(f"[quality_gates] LLM evaluation failed for {stage_id}: {e}")
        return GateCheck(
            name="llm_quality", category="llm",
            status=GateStatus.WARNING, score=0.5,
            message=f"LLM 评估不可用（{e}），已跳过",
        )


def _parse_llm_evaluation(content: str) -> tuple[int, str, str, str]:
    """Parse structured LLM evaluation response."""
    score = 5
    verdict = "WARN"
    summary = ""
    issues = ""

    for line in content.strip().split("\n"):
        line = line.strip()
        upper = line.upper()
        if upper.startswith("SCORE:"):
            try:
                s = "".join(c for c in line.split(":", 1)[1] if c.isdigit())
                score = max(1, min(10, int(s))) if s else 5
            except (ValueError, IndexError):
                pass
        elif upper.startswith("VERDICT:"):
            v = line.split(":", 1)[1].strip().upper()
            if "PASS" in v:
                verdict = "PASS"
            elif "FAIL" in v:
                verdict = "FAIL"
            else:
                verdict = "WARN"
        elif upper.startswith("SUMMARY:"):
            summary = line.split(":", 1)[1].strip()
        elif upper.startswith("ISSUES:"):
            issues = line.split(":", 1)[1].strip()
        elif line.startswith("- ") and issues is not None:
            issues += "\n" + line

    return score, verdict, summary, issues


def _apply_thresholds(
    checks: List[GateCheck],
    config: Dict[str, Any],
) -> tuple[GateStatus, float, bool, Optional[str]]:
    """Apply configurable thresholds to compute overall gate result."""
    pass_threshold = config.get("pass_threshold", 0.7)
    fail_threshold = config.get("fail_threshold", 0.4)

    if not checks:
        return GateStatus.PASSED, 1.0, True, None

    scores = [c.score for c in checks]
    avg_score = sum(scores) / len(scores)

    has_critical_failure = any(
        c.status == GateStatus.FAILED and c.category in ("deliverable", "threshold")
        for c in checks
    )

    if has_critical_failure or avg_score < fail_threshold:
        failed_checks = [c for c in checks if c.status == GateStatus.FAILED]
        reason = "; ".join(c.message for c in failed_checks[:3]) if failed_checks else "质量评分过低"
        return GateStatus.FAILED, avg_score, False, reason

    if avg_score < pass_threshold:
        warn_checks = [c for c in checks if c.status in (GateStatus.WARNING, GateStatus.FAILED)]
        reason = "; ".join(c.message for c in warn_checks[:2]) if warn_checks else None
        return GateStatus.WARNING, avg_score, True, reason

    return GateStatus.PASSED, avg_score, True, None


async def evaluate_quality_gate(
    stage_id: str,
    output: str,
    *,
    template: Optional[str] = None,
    previous_outputs: Optional[Dict[str, str]] = None,
    heuristic_result: Optional[StageVerification] = None,
    skip_llm: bool = False,
    task_overrides: Optional[Dict[str, Any]] = None,
) -> GateResult:
    """
    Full quality gate evaluation for a stage output.

    Runs heuristic checks, deliverable completeness, optional LLM evaluation,
    then applies thresholds to determine pass/warn/fail.

    ``task_overrides``: per-task config from ``PipelineTask.quality_gate_config``.
    See ``_get_stage_config`` for precedence rules.
    """
    config = _get_stage_config(stage_id, template, task_overrides)
    checks: List[GateCheck] = []
    suggestions: List[str] = []

    if heuristic_result:
        checks.append(_heuristic_to_gate_check(heuristic_result))
    else:
        verify = verify_stage_output(stage_id, "", output, previous_outputs)
        checks.append(_heuristic_to_gate_check(verify))

    checks.append(_check_deliverable_sections(output, config))
    checks.append(_check_deliverable_keywords(output, config))
    checks.append(_check_length_gate(output, config))

    if not skip_llm:
        llm_check = await _llm_quality_evaluation(
            stage_id, output, config, previous_outputs,
        )
        checks.append(llm_check)

    overall_status, overall_score, can_proceed, block_reason = _apply_thresholds(checks, config)

    if overall_status == GateStatus.WARNING:
        suggestions.append("建议人工审查后再推进")
    if overall_status == GateStatus.FAILED:
        suggestions.append("本阶段未通过质量门禁，需要修改后重新提交")
        failed = [c for c in checks if c.status == GateStatus.FAILED]
        for fc in failed[:3]:
            suggestions.append(f"[修复] {fc.message}")

    return GateResult(
        stage_id=stage_id,
        template=template,
        overall_status=overall_status,
        overall_score=round(overall_score, 3),
        checks=checks,
        can_proceed=can_proceed,
        block_reason=block_reason,
        suggestions=suggestions,
    )


async def generate_quality_report(
    stages: List[Dict[str, Any]],
    *,
    task_title: str = "",
    template: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate a comprehensive quality report for all completed stages.
    Used for the project-level quality dashboard.
    """
    stage_reports: List[Dict[str, Any]] = []
    total_score = 0.0
    gate_count = 0

    for stage_data in stages:
        sid = stage_data.get("stage_id", "")
        output = stage_data.get("output", "")
        gate_status = stage_data.get("gate_status", "pending")
        gate_score = stage_data.get("gate_score")
        verify_status = stage_data.get("verify_status")
        quality_score = stage_data.get("quality_score")
        review_status = stage_data.get("review_status")

        config = _get_stage_config(sid, template)
        report = {
            "stage_id": sid,
            "label": config.get("label", sid),
            "gate_status": gate_status,
            "gate_score": gate_score,
            "verify_status": verify_status,
            "quality_score": quality_score,
            "review_status": review_status,
            "has_output": bool(output),
            "output_length": len(output) if output else 0,
            "pass_threshold": config.get("pass_threshold", 0.7),
            "fail_threshold": config.get("fail_threshold", 0.4),
        }

        if gate_score is not None:
            total_score += gate_score
            gate_count += 1

        stage_reports.append(report)

    avg_score = round(total_score / gate_count, 3) if gate_count > 0 else 0.0
    all_passed = all(
        r["gate_status"] in ("passed", "bypassed", "pending")
        for r in stage_reports
    )
    any_failed = any(r["gate_status"] == "failed" for r in stage_reports)

    return {
        "task_title": task_title,
        "template": template,
        "stages": stage_reports,
        "summary": {
            "total_stages": len(stage_reports),
            "gates_evaluated": gate_count,
            "average_score": avg_score,
            "all_passed": all_passed,
            "any_failed": any_failed,
            "overall_verdict": (
                "FAILED" if any_failed else
                "PASSED" if all_passed and gate_count > 0 else
                "IN_PROGRESS"
            ),
        },
    }
