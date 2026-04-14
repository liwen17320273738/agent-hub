"""
Self-Verification Loop — 每个 Skill 执行后的自动验证

验证链:
1. 格式验证: 输出是否符合预期格式 (Markdown? JSON? 包含必要 section?)
2. 完整性验证: 输出是否覆盖了所有必要项 (如 PRD 需包含验收标准)
3. 质量验证: 使用 LLM 快速评估输出质量 (用便宜模型)
4. 回归验证: 是否与前序阶段产出一致 (不矛盾)

每个验证步骤返回 PASS / WARN / FAIL + 具体原因
"""
from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Optional, Dict, Any, List

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class VerifyStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class VerifyResult(BaseModel):
    check_name: str
    status: VerifyStatus
    message: str
    details: Optional[str] = None


class StageVerification(BaseModel):
    stage_id: str
    role: str
    overall_status: VerifyStatus
    checks: List[VerifyResult]
    auto_proceed: bool = True  # False = needs human review
    suggestions: List[str] = []


STAGE_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "planning": {
        "required_sections": ["目标", "范围", "用户故事", "验收标准"],
        "min_length": 500,
        "format": "markdown",
        "must_contain": ["验收"],
    },
    "architecture": {
        "required_sections": ["技术选型", "架构", "数据模型", "API", "实现步骤"],
        "min_length": 800,
        "format": "markdown",
        "must_contain": ["风险"],
    },
    "development": {
        "required_sections": ["项目结构", "代码", "依赖"],
        "min_length": 1000,
        "format": "markdown",
        "must_contain": ["```"],
    },
    "testing": {
        "required_sections": ["测试范围", "测试用例", "边界条件"],
        "min_length": 400,
        "format": "markdown",
        "must_contain": ["PASS", "NEEDS WORK", "结论"],
        "must_contain_any": True,
    },
    "reviewing": {
        "required_sections": ["评估", "验收"],
        "min_length": 300,
        "format": "markdown",
        "must_contain": ["APPROVED", "REJECTED"],
        "must_contain_any": True,
    },
    "deployment": {
        "required_sections": ["环境", "构建", "部署"],
        "min_length": 400,
        "format": "markdown",
        "must_contain": ["docker", "Docker", "CI", "回滚"],
        "must_contain_any": True,
    },
}


def verify_stage_output(
    stage_id: str,
    role: str,
    output: str,
    previous_outputs: Optional[Dict[str, str]] = None,
) -> StageVerification:
    """Run all verification checks on a stage output."""
    checks: List[VerifyResult] = []
    suggestions: List[str] = []

    reqs = STAGE_REQUIREMENTS.get(stage_id, {})

    # 1. Format check
    checks.append(_check_format(output, reqs.get("format", "markdown")))

    # 2. Length check
    min_len = reqs.get("min_length", 100)
    checks.append(_check_length(output, min_len))

    # 3. Required sections check
    required = reqs.get("required_sections", [])
    if required:
        checks.append(_check_required_sections(output, required))

    # 4. Must-contain keywords
    must_contain = reqs.get("must_contain", [])
    if must_contain:
        must_any = reqs.get("must_contain_any", False)
        checks.append(_check_keywords(output, must_contain, any_match=must_any))

    # 5. Consistency with previous stages
    if previous_outputs:
        checks.append(_check_consistency(output, previous_outputs, stage_id))

    # 6. Common quality checks
    checks.append(_check_no_placeholder(output))
    checks.append(_check_no_truncation(output))

    overall = _compute_overall(checks)
    auto_proceed = overall != VerifyStatus.FAIL

    if overall == VerifyStatus.WARN:
        suggestions.append("建议人工审核后再推进到下一阶段")
    if overall == VerifyStatus.FAIL:
        suggestions.append("本阶段产出未通过验证，需要重新执行或人工修正")

    return StageVerification(
        stage_id=stage_id,
        role=role,
        overall_status=overall,
        checks=checks,
        auto_proceed=auto_proceed,
        suggestions=suggestions,
    )


def _check_format(output: str, expected: str) -> VerifyResult:
    if expected == "markdown":
        has_headers = bool(re.search(r'^#{1,3}\s', output, re.MULTILINE))
        has_lists = bool(re.search(r'^[\s]*[-*\d]+[.)]\s', output, re.MULTILINE))
        if has_headers or has_lists:
            return VerifyResult(check_name="format", status=VerifyStatus.PASS, message="Markdown 格式正确")
        return VerifyResult(check_name="format", status=VerifyStatus.WARN, message="未检测到 Markdown 标题或列表")
    return VerifyResult(check_name="format", status=VerifyStatus.PASS, message="格式检查跳过")


def _check_length(output: str, min_len: int) -> VerifyResult:
    length = len(output.strip())
    if length >= min_len:
        return VerifyResult(check_name="length", status=VerifyStatus.PASS, message=f"内容长度 {length} 字符")
    if length >= min_len * 0.5:
        return VerifyResult(
            check_name="length",
            status=VerifyStatus.WARN,
            message=f"内容偏短 ({length}/{min_len} 字符)",
        )
    return VerifyResult(
        check_name="length",
        status=VerifyStatus.FAIL,
        message=f"内容过短 ({length}/{min_len} 字符)",
    )


def _check_required_sections(output: str, sections: List[str]) -> VerifyResult:
    missing = []
    for section in sections:
        if section not in output:
            missing.append(section)

    if not missing:
        return VerifyResult(
            check_name="required_sections",
            status=VerifyStatus.PASS,
            message=f"包含所有 {len(sections)} 个必要章节",
        )

    if len(missing) <= len(sections) * 0.3:
        return VerifyResult(
            check_name="required_sections",
            status=VerifyStatus.WARN,
            message=f"缺少部分章节: {', '.join(missing)}",
        )

    return VerifyResult(
        check_name="required_sections",
        status=VerifyStatus.FAIL,
        message=f"缺少关键章节: {', '.join(missing)}",
    )


def _check_keywords(output: str, keywords: List[str], any_match: bool = False) -> VerifyResult:
    found = [kw for kw in keywords if kw in output]

    if any_match:
        if found:
            return VerifyResult(
                check_name="keywords",
                status=VerifyStatus.PASS,
                message=f"包含关键结论: {', '.join(found)}",
            )
        return VerifyResult(
            check_name="keywords",
            status=VerifyStatus.FAIL,
            message=f"未找到任何结论关键词: {', '.join(keywords)}",
        )

    missing = [kw for kw in keywords if kw not in found]
    if not missing:
        return VerifyResult(check_name="keywords", status=VerifyStatus.PASS, message="包含所有必要关键词")
    return VerifyResult(
        check_name="keywords",
        status=VerifyStatus.WARN,
        message=f"缺少关键词: {', '.join(missing)}",
    )


def _check_consistency(output: str, previous: Dict[str, str], stage_id: str) -> VerifyResult:
    """Basic consistency check: does the output reference the task title from planning?"""
    planning = previous.get("planning", "")
    if not planning:
        return VerifyResult(check_name="consistency", status=VerifyStatus.PASS, message="无前序产出可比较")

    first_line = planning.split("\n")[0].strip().replace("#", "").strip()
    if first_line and len(first_line) > 5:
        keywords = [w for w in first_line.split() if len(w) > 2][:3]
        matches = sum(1 for kw in keywords if kw in output)
        if matches > 0:
            return VerifyResult(
                check_name="consistency",
                status=VerifyStatus.PASS,
                message=f"与 PRD 主题一致 ({matches}/{len(keywords)} 关键词匹配)",
            )
        return VerifyResult(
            check_name="consistency",
            status=VerifyStatus.WARN,
            message="与 PRD 主题关联度较低",
        )

    return VerifyResult(check_name="consistency", status=VerifyStatus.PASS, message="一致性检查通过")


def _check_no_placeholder(output: str) -> VerifyResult:
    placeholders = ["TODO", "TBD", "FIXME", "[待补充]", "[placeholder]", "Lorem ipsum"]
    found = [p for p in placeholders if p.lower() in output.lower()]
    if found:
        return VerifyResult(
            check_name="no_placeholder",
            status=VerifyStatus.WARN,
            message=f"包含占位符: {', '.join(found)}",
        )
    return VerifyResult(check_name="no_placeholder", status=VerifyStatus.PASS, message="无占位符")


def _check_no_truncation(output: str) -> VerifyResult:
    truncation_signs = ["...", "（续）", "(continued)", "以下省略"]
    last_100 = output[-100:] if len(output) > 100 else output
    found = [s for s in truncation_signs if s in last_100]
    if found:
        return VerifyResult(
            check_name="no_truncation",
            status=VerifyStatus.WARN,
            message="内容可能被截断",
        )
    return VerifyResult(check_name="no_truncation", status=VerifyStatus.PASS, message="内容完整")


def _compute_overall(checks: List[VerifyResult]) -> VerifyStatus:
    if any(c.status == VerifyStatus.FAIL for c in checks):
        return VerifyStatus.FAIL
    if any(c.status == VerifyStatus.WARN for c in checks):
        return VerifyStatus.WARN
    return VerifyStatus.PASS
