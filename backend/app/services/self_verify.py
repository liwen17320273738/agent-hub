"""
Self-Verification Loop — 每个 Skill 执行后的自动验证

验证链 (启发式规则 + 可选 LLM 快速过滤):
1. 格式验证: 输出是否符合预期格式 (Markdown 标题/列表检测)
2. 长度验证: 输出是否达到最低字符数要求
3. 必要章节检测: 输出是否包含阶段要求的关键章节名
4. 关键词检测: 输出是否包含特定结论关键词
5. 一致性检查: 输出是否引用了前序阶段的主题
6. 占位符检测: 检测文字/TODO/语义占位符
7. 截断检测: 输出是否被意外截断
8. LLM 快速质量过滤: 有配置时用独立弱模型做实质性内容评估（非同一模型）

LLM-based quality evaluation can be enabled per-stage via
QUALITY_CHECK_MODEL in settings.  When unset, only heuristic checks run.
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
        "required_sections": ["目标", "范围", "用户故事", "验收标准", "优先级"],
        "min_length": 800,
        "format": "markdown",
        "must_contain": ["验收"],
        "min_sections": 4,
        "min_user_stories": 3,
    },
    "design": {
        "required_sections": ["界面", "交互", "布局", "配色"],
        "min_length": 500,
        "format": "markdown",
        "must_contain": ["用户"],
        "must_contain_any": True,
    },
    "architecture": {
        "required_sections": ["技术选型", "架构", "数据模型", "API", "实现步骤"],
        "min_length": 1000,
        "format": "markdown",
        "must_contain": ["风险"],
        "min_code_blocks": 1,
    },
    "development": {
        "required_sections": ["项目结构", "代码"],
        "min_length": 1500,
        "format": "markdown",
        "must_contain": ["```"],
        "min_code_blocks": 3,
        "min_code_files": 2,
    },
    "testing": {
        "required_sections": ["测试范围", "测试用例"],
        "min_length": 600,
        "format": "markdown",
        "must_contain": ["PASS", "NEEDS WORK", "结论", "通过", "失败"],
        "must_contain_any": True,
        "min_test_cases": 5,
    },
    "reviewing": {
        "required_sections": ["评估"],
        "min_length": 400,
        "format": "markdown",
        "must_contain": ["APPROVE", "REJECT", "通过", "驳回"],
        "must_contain_any": True,
    },
    "deployment": {
        "required_sections": ["环境", "部署"],
        "min_length": 400,
        "format": "markdown",
        "must_contain": ["docker", "Docker", "CI", "回滚", "部署", "启动"],
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
    checks.append(_check_semantic_placeholder(output))
    checks.append(_check_no_truncation(output))

    # 7. Stage-specific structural checks
    min_code_blocks = reqs.get("min_code_blocks", 0)
    if min_code_blocks:
        checks.append(_check_code_blocks(output, min_code_blocks))

    min_code_files = reqs.get("min_code_files", 0)
    if min_code_files:
        checks.append(_check_code_files(output, min_code_files))

    min_test_cases = reqs.get("min_test_cases", 0)
    if min_test_cases:
        checks.append(_check_test_cases(output, min_test_cases))

    min_user_stories = reqs.get("min_user_stories", 0)
    if min_user_stories:
        checks.append(_check_user_stories(output, min_user_stories))

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


def _check_semantic_placeholder(output: str) -> VerifyResult:
    """Detect semantic placeholders — phrases that promise future work but
    deliver nothing concrete today."""
    semantic_patterns = [
        r"将在?下一[步版]?[本代]?[中里]?实现",
        r"需[要待]进一步[讨确]?[论认定]?",
        r"后[续期]?再[行考处]?虑理?",
        r"(?:此功|该特)能[将在]?[于在]?(?:后续|未来|下一个?版本).*实现",
        r"具体(?:细节|方案|实现).*(?:待定|稍后|暂无|后续)",
        r"暂[时不]?[不考]?[考处]?虑",
        r"这里省略\d+行",
        r"以下(?:内容|代码|部分)省略",
        r"代码略",
        r"pending(?:ing)? implementation",
        r"(?:to be|will be) implemented in future",
        r"left as an exercise",
        r"out of (?:the )?scope for now",
        r"(?:this|the) feature will be added in (?:a )?(?:future|next)",
    ]
    found = []
    for pattern in semantic_patterns:
        matches = re.findall(pattern, output, re.IGNORECASE)
        for m in matches:
            # Find context: grab up to 60 chars around the match
            idx = output.lower().find(m.lower())
            start = max(0, idx - 40)
            end = min(len(output), idx + len(m) + 40)
            context = output[start:end].replace("\n", " ")
            # Deduplicate by context
            if not any(context[:30] in f for f in found):
                found.append(context)
    if found:
        messages = "; ".join(f[:60] for f in found[:3])
        if len(found) > 3:
            messages += f" (+{len(found)-3} more)"
        return VerifyResult(
            check_name="semantic_placeholder",
            status=VerifyStatus.WARN,
            message=f"检测到语义占位符: {messages}",
        )
    return VerifyResult(
        check_name="semantic_placeholder",
        status=VerifyStatus.PASS,
        message="无语义占位符",
    )


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


def _check_code_blocks(output: str, min_count: int) -> VerifyResult:
    """Count fenced code blocks (``` ... ```)."""
    blocks = re.findall(r"```\w*", output)
    count = len(blocks)
    if count >= min_count:
        return VerifyResult(
            check_name="code_blocks",
            status=VerifyStatus.PASS,
            message=f"包含 {count} 个代码块",
        )
    if count > 0:
        return VerifyResult(
            check_name="code_blocks",
            status=VerifyStatus.WARN,
            message=f"代码块不足 ({count}/{min_count})",
        )
    return VerifyResult(
        check_name="code_blocks",
        status=VerifyStatus.FAIL,
        message=f"未找到代码块 (需要至少 {min_count} 个)",
    )


def _check_code_files(output: str, min_count: int) -> VerifyResult:
    """Count code blocks with file path annotations (```lang:path)."""
    file_blocks = re.findall(r"```\w+:[^\n`]+", output)
    filepath_comments = re.findall(
        r"(?://|#)\s*(?:filepath|file|文件)[:\s]", output, re.IGNORECASE
    )
    count = len(file_blocks) + len(filepath_comments)
    if count >= min_count:
        return VerifyResult(
            check_name="code_files",
            status=VerifyStatus.PASS,
            message=f"包含 {count} 个带路径的代码文件",
        )
    if count > 0:
        return VerifyResult(
            check_name="code_files",
            status=VerifyStatus.WARN,
            message=f"带路径代码文件不足 ({count}/{min_count})",
        )
    return VerifyResult(
        check_name="code_files",
        status=VerifyStatus.WARN,
        message="未检测到带路径的代码文件（建议使用 ```lang:path 格式）",
    )


def _check_test_cases(output: str, min_count: int) -> VerifyResult:
    """Count test case entries (numbered items, TC-xxx, test_xxx, etc.)."""
    patterns = [
        re.findall(r"TC[-_]?\d+", output, re.IGNORECASE),
        re.findall(r"test[-_]\w+", output, re.IGNORECASE),
        re.findall(r"(?:测试用例|用例)\s*\d+", output),
        re.findall(r"^\s*\d+\.\s.*(?:测试|test|验证|检查)", output, re.MULTILINE | re.IGNORECASE),
    ]
    unique = set()
    for matches in patterns:
        unique.update(matches)
    count = len(unique)
    if count >= min_count:
        return VerifyResult(
            check_name="test_cases",
            status=VerifyStatus.PASS,
            message=f"包含 {count} 个测试用例",
        )
    if count >= min_count // 2:
        return VerifyResult(
            check_name="test_cases",
            status=VerifyStatus.WARN,
            message=f"测试用例偏少 ({count}/{min_count})",
        )
    return VerifyResult(
        check_name="test_cases",
        status=VerifyStatus.WARN,
        message=f"测试用例过少 ({count}/{min_count})",
    )


def _check_user_stories(output: str, min_count: int) -> VerifyResult:
    """Count user story entries (作为...我希望..., As a...I want...)."""
    zh = re.findall(r"作为.*?[，,].*?(?:希望|能够|可以)", output)
    en = re.findall(r"As a.*?I (?:want|need|can)", output, re.IGNORECASE)
    numbered = re.findall(r"^\s*\d+\.\s.*(?:用户|功能|需求)", output, re.MULTILINE)
    count = len(zh) + len(en) + len(numbered)
    if count >= min_count:
        return VerifyResult(
            check_name="user_stories",
            status=VerifyStatus.PASS,
            message=f"包含 {count} 个用户故事/需求项",
        )
    return VerifyResult(
        check_name="user_stories",
        status=VerifyStatus.WARN,
        message=f"用户故事/需求项偏少 ({count}/{min_count})",
    )


async def llm_content_quality_check(
    stage_id: str,
    output: str,
    previous_outputs: Optional[Dict[str, str]] = None,
) -> Optional[VerifyResult]:
    """Optional LLM-based content quality check using a dedicated lightweight model.

    Only runs when QUALITY_CHECK_MODEL is set in settings.  Uses a short
    model call to flag obviously empty / hallucinated / copy-pasta content.
    This is NOT the deep evaluation in quality_gates.py — it's a cheap fast
    filter for the self-verify loop.
    """
    try:
        from ..config import settings

        model = getattr(settings, "quality_check_model", "") or ""
        api_url = getattr(settings, "quality_check_api_url", "") or ""
        if not model:
            return None  # disabled
    except Exception:
        return None

    system_prompt = (
        "You are a content quality filter. Read the stage output below and "
        "answer ONLY with PASS or FAIL + one-line reason.\n\n"
        "FAIL if ANY of:\n"
        "- The output is mostly boilerplate / template text with no meaningful content\n"
        "- It says 'under development' or 'coming soon' for every deliverable\n"
        "- It's a copy-paste of the input prompt with minor rewording\n"
        "- It's hallucinated (references real products/APIs that don't exist)\n"
        "- It repeatedly says the same thing in different words with no substance\n\n"
        "Otherwise PASS.\n\n"
        "Format: PASS|FAIL: <reason>"
    )
    user_msg = f"## Stage: {stage_id}\n\n{output[:3000]}"
    if previous_outputs:
        context = "\n".join(
            f"## {sid}\n{out[:500]}"
            for sid, out in list(previous_outputs.items())[:2]
            if out and sid != stage_id
        )
        if context:
            user_msg = context + "\n\n" + user_msg

    try:
        from .llm_router import chat_completion

        result = await chat_completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            api_url=api_url,
            temperature=0.1,
            max_tokens=200,
        )
        if result.get("error"):
            return None

        content = (result.get("content") or "").strip()
        if content.upper().startswith("FAIL"):
            reason = content.split(":", 1)[1].strip() if ":" in content else "内容质量不达标"
            return VerifyResult(
                check_name="llm_quality",
                status=VerifyStatus.WARN,
                message=f"LLM 质量过滤: {reason}",
            )
        return VerifyResult(
            check_name="llm_quality",
            status=VerifyStatus.PASS,
            message="LLM 质量过滤通过",
        )
    except Exception as e:
        logger.debug(f"[self_verify] LLM content quality check skipped: {e}")
        return None


def _compute_overall(checks: List[VerifyResult]) -> VerifyStatus:
    if any(c.status == VerifyStatus.FAIL for c in checks):
        return VerifyStatus.FAIL
    if any(c.status == VerifyStatus.WARN for c in checks):
        return VerifyStatus.WARN
    return VerifyStatus.PASS
