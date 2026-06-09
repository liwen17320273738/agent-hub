"""
跨阶段一致性验证 — 检查下游阶段是否兑现了上游阶段的承诺。

核心思路：
1. 从上游产出中提取结构化承诺（功能需求、技术决策、UI 规格）
2. 下游阶段产出后，逐条检查承诺是否被兑现
3. 未兑现的承诺 → WARN 或 FAIL，附具体缺失项

验证链路：
- Planning → Architecture: 架构决策是否覆盖了 PRD 需求？
- Planning → Development: 代码是否实现了 PRD 功能？
- Architecture → Development: 代码是否遵循架构方案？
- Architecture → Testing: 测试是否覆盖了架构决策？
"""
from __future__ import annotations

import json
import logging
import os
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from .self_verify import VerifyResult, VerifyStatus

logger = logging.getLogger(__name__)

# 跨阶段验证对: (上游, 下游) → 验证提示词
# 覆盖 quality_gates._CONSISTENCY_PAIRS 的全部阶段对
_CROSS_STAGE_PAIRS: Dict[Tuple[str, str], str] = {
    ("planning", "design"): "PRD 需求是否在 UI/UX 设计规范中有对应的页面和交互？",
    ("planning", "architecture"): "PRD 功能需求是否在架构方案中有对应的技术方案？",
    ("planning", "development"): "PRD 中的功能需求是否都有对应的代码实现？",
    ("planning", "acceptance"): "验收评审是否逐条对照了 PRD 的验收标准？",
    ("design", "architecture"): "设计规范中的组件和交互是否在架构方案中有技术支撑？",
    ("architecture", "development"): "架构方案中的技术决策是否在代码中落实？",
    ("architecture", "testing"): "测试用例是否覆盖了架构方案中的关键路径？",
    ("development", "testing"): "测试是否覆盖了代码实现的核心功能？",
    ("development", "acceptance"): "验收评审是否对照了实际代码产出？",
}

# quality_gates 中使用的上游阶段列表（用于启发式检查）— key 为下游阶段
_CONSISTENCY_UPSTREAM: Dict[str, List[str]] = {
    "design": ["planning"],
    "architecture": ["planning", "design"],
    "development": ["architecture", "planning"],
    "testing": ["development", "architecture"],
    "acceptance": ["planning", "development"],
}


def _cross_stage_enabled() -> bool:
    return os.getenv("CROSS_STAGE_VERIFY_ENABLED", "true").lower() not in ("0", "false", "no")


def _cross_stage_model() -> str:
    """用于交叉验证的模型 — 优先用便宜模型。"""
    return os.getenv("CROSS_STAGE_VERIFY_MODEL", "") or os.getenv("QUALITY_CHECK_MODEL", "") or ""


async def verify_cross_stage(
    stage_id: str,
    output: str,
    previous_outputs: Dict[str, str],
) -> List[VerifyResult]:
    """对当前阶段产出执行跨阶段一致性验证。

    遍历所有已定义的上游→下游验证对，当当前阶段作为下游时，
    检查其产出是否兑现了上游的承诺。
    """
    if not _cross_stage_enabled():
        return []

    if not output.strip():
        return [
            VerifyResult(
                check_name="cross_stage",
                status=VerifyStatus.FAIL,
                message="当前阶段无产出，无法进行交叉验证",
            )
        ]

    model = _cross_stage_model()
    if not model:
        # 回退到启发式关键词匹配
        return _heuristic_cross_check(stage_id, output, previous_outputs)

    results: List[VerifyResult] = []
    for (upstream, downstream), question in _CROSS_STAGE_PAIRS.items():
        if downstream != stage_id:
            continue
        upstream_output = previous_outputs.get(upstream, "")
        if not upstream_output.strip():
            results.append(VerifyResult(
                check_name=f"cross_stage:{upstream}→{downstream}",
                status=VerifyStatus.PASS,
                message=f"上游 {upstream} 无产出，跳过验证",
            ))
            continue

        try:
            result = await _llm_cross_check(upstream, upstream_output, downstream, output, question, model)
            results.append(result)
        except Exception as e:
            logger.warning("[cross_stage] LLM 交叉验证失败 (%s→%s): %s", upstream, downstream, e)
            results.append(VerifyResult(
                check_name=f"cross_stage:{upstream}→{downstream}",
                status=VerifyStatus.WARN,
                message=f"交叉验证执行失败: {str(e)[:100]}",
            ))

    return results


async def _llm_cross_check(
    upstream_stage: str,
    upstream_output: str,
    downstream_stage: str,
    downstream_output: str,
    question: str,
    model: str,
) -> VerifyResult:
    """用 LLM 逐条检查上游承诺是否在下游产出中兑现。"""
    from .llm_router import chat_completion

    prompt = f"""你是代码审查专家。检查"{downstream_stage}"阶段的产出是否兑现了"{upstream_stage}"阶段的承诺。

核心问题：{question}

## 上游产出（{upstream_stage}）
{upstream_output[:4000]}

## 下游产出（{downstream_stage}）
{downstream_output[:4000]}

请：
1. 从上游产出中提取 3-8 条关键承诺/需求
2. 逐条检查下游产出是否兑现了该承诺
3. 返回 JSON 格式结果

返回格式（只返回 JSON，不要其他文字）：
{{
  "overall": "pass|warn|fail",
  "summary": "一句话总结",
  "items": [
    {{"promise": "承诺内容", "fulfilled": true|false, "evidence": "兑现证据或缺失说明"}}
  ]
}}"""

    try:
        result = await chat_completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1500,
        )

        if result.get("error"):
            return VerifyResult(
                check_name=f"cross_stage:{upstream_stage}→{downstream_stage}",
                status=VerifyStatus.WARN,
                message=f"LLM 调用失败: {result['error'][:100]}",
            )

        content = result.get("content", "")
        parsed = _parse_cross_check_result(content)

        overall = parsed.get("overall", "warn")
        summary = parsed.get("summary", "")
        items = parsed.get("items", [])

        fulfilled = sum(1 for i in items if i.get("fulfilled"))
        total = len(items)

        if overall == "fail":
            status = VerifyStatus.FAIL
        elif overall == "warn":
            status = VerifyStatus.WARN
        else:
            status = VerifyStatus.PASS

        detail_lines = [f"{'✓' if i.get('fulfilled') else '✗'} {i.get('promise', '?')}"
                        for i in items]
        detail = "\n".join(detail_lines)

        return VerifyResult(
            check_name=f"cross_stage:{upstream_stage}→{downstream_stage}",
            status=status,
            message=f"{summary}（{fulfilled}/{total} 承诺已兑现）",
            details=detail,
        )

    except Exception as e:
        raise


def _parse_cross_check_result(raw: str) -> Dict[str, Any]:
    """从 LLM 返回中提取 JSON，容错处理。"""
    # 尝试直接解析
    try:
        return json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试提取 JSON 块
    m = re.search(r'\{[\s\S]*"overall"[\s\S]*\}', raw)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    # 回退：从文本中推断
    raw_lower = raw.lower()
    if any(kw in raw_lower for kw in ("fail", "未兑现", "缺失", "不一致", "严重")):
        overall = "fail"
    elif any(kw in raw_lower for kw in ("warn", "部分", "不够", "缺少", "不足")):
        overall = "warn"
    else:
        overall = "pass"

    return {
        "overall": overall,
        "summary": raw[:200].replace("\n", " "),
        "items": [],
    }


def _heuristic_cross_check(
    stage_id: str,
    output: str,
    previous_outputs: Dict[str, str],
) -> List[VerifyResult]:
    """启发式交叉验证 — 不依赖 LLM，基于关键词和术语重叠。

    从上游产出提取关键术语，检查下游产出中是否出现。
    这是 LLM 验证的廉价替代方案。
    """
    results: List[VerifyResult] = []
    output_lower = output.lower()

    for (upstream, downstream), _question in _CROSS_STAGE_PAIRS.items():
        if downstream != stage_id:
            continue
        upstream_output = previous_outputs.get(upstream, "")
        if not upstream_output.strip():
            continue

        # 提取上游关键术语
        upstream_terms = _extract_meaningful_terms(upstream_output)
        if not upstream_terms:
            continue

        found_terms = {t for t in upstream_terms if t.lower() in output_lower}
        missing_terms = upstream_terms - found_terms
        coverage = len(found_terms) / len(upstream_terms) if upstream_terms else 1.0

        if coverage >= 0.7:
            status = VerifyStatus.PASS
        elif coverage >= 0.4:
            status = VerifyStatus.WARN
        else:
            status = VerifyStatus.FAIL

        detail = ""
        if missing_terms:
            detail = f"缺失引用: {', '.join(sorted(missing_terms)[:10])}"

        results.append(VerifyResult(
            check_name=f"cross_stage:{upstream}→{downstream}",
            status=status,
            message=f"术语覆盖率 {coverage:.0%}（{len(found_terms)}/{len(upstream_terms)}）",
            details=detail,
        ))

    return results


def _extract_meaningful_terms(text: str, limit: int = 60) -> set:
    """从文本中提取有意义的术语用于交叉匹配。

    侧重提取：中文词组（2-4字）、英文标识符、引号内术语。
    """
    terms: set = set()

    # 中文词组 — 滑动窗口提取 2-4 字词
    _cn_stop_chars = set('的是在不了有和人这中大上国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严')
    chinese_chars = [c for c in text if '一' <= c <= '鿿']
    seen_cn: set = set()
    for win_size in (4, 3, 2):
        for i in range(len(chinese_chars) - win_size + 1):
            term = ''.join(chinese_chars[i:i + win_size])
            if term in seen_cn:
                continue
            seen_cn.add(term)
            # 跳过纯虚词（超过75%字符是停用字）
            if sum(1 for c in term if c in _cn_stop_chars) > len(term) * 0.75:
                continue
            terms.add(term)

    # 引号内术语
    for m in re.finditer(r'[「『"`\']([^「『"`\'\]]{2,30})[」』"`\']', text):
        terms.add(m.group(1).strip())

    # 英文标识符（驼峰或下划线）
    for m in re.finditer(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b|\b[a-z]+(?:_[a-z]+){1,}\b', text):
        terms.add(m.group(0))

    # 去常见停用词
    stopwords = {"这个", "那个", "一个", "可以", "需要", "使用", "通过", "进行", "实现",
                 "功能", "系统", "用户", "数据", "管理", "支持", "提供", "包括",
                 "interface", "class", "function", "method", "object", "string"}
    terms.difference_update(stopwords)

    if len(terms) <= limit:
        return terms
    # 分层采样：每个长度取配额，按术语质量排序后截断
    by_len: Dict[int, list] = {}
    for t in terms:
        if not t:
            continue
        info_ratio = 1.0 - sum(1 for c in t if c in _cn_stop_chars) / len(t)
        by_len.setdefault(len(t), []).append((info_ratio, t))
    # 每组按信息密度降序排列，同分按字符串排序保证确定性
    for entries in by_len.values():
        entries.sort(key=lambda x: (-x[0], x[1]))
    selected: set = set()
    for win_size, pct in [(4, 0.5), (3, 0.3), (2, 0.2)]:
        if win_size not in by_len:
            continue
        take = max(3, int(limit * pct))
        selected.update(t for _, t in by_len[win_size][:take])
    return selected
