"""
Skill Marketplace — discovery, installation, versioning, and sandboxed execution.

Features:
1. Registry of built-in + filesystem SKILL.md skills with Schema validation
2. Skill installation from marketplace (version pinned)
3. Sandboxed execution with timeout + resource limits
4. Execution metrics and popularity ranking
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.skill import Skill
from .tool_schema import (
    SkillSchema, validate_input, validate_output,
    compute_idempotency_key, check_idempotency,
    record_execution_start, record_execution_complete,
)
from .llm_router import chat_completion
from .sse import emit_event
from .skill_loader import discover_skills, get_loaded_skills, get_skill as get_fs_skill

logger = logging.getLogger(__name__)


MARKETPLACE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "code-review": {
        "name": "Code Review",
        "category": "development",
        "version": "1.2.0",
        "author": "system",
        "description": "AI-powered code review with security checks, best practices, and performance suggestions.",
        "tags": ["code", "review", "security", "quality"],
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code to review"},
                "language": {"type": "string", "description": "Programming language"},
                "context": {"type": "string", "description": "Additional context"},
            },
            "required": ["code", "language"],
        },
        "output_schema": {"type": "string"},
        "prompt_template": """你是一位资深代码审查专家。请对以下 {language} 代码进行审查：

```{language}
{code}
```

{context}

请从以下维度进行评审：
1. 代码质量和可读性
2. 潜在 Bug 和逻辑错误
3. 安全漏洞
4. 性能问题
5. 最佳实践建议

输出格式：
- 问题列表（按严重程度排序）
- 修改建议（包含代码片段）
- 总体评分 (1-10)""",
    },
    "prd-writing": {
        "name": "PRD Writing",
        "category": "product",
        "version": "1.1.0",
        "author": "system",
        "description": "Generate structured product requirements documents.",
        "tags": ["prd", "product", "requirements", "documentation"],
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Product/feature title"},
                "description": {"type": "string", "description": "High-level description"},
                "audience": {"type": "string", "description": "Target audience"},
            },
            "required": ["title", "description"],
        },
        "output_schema": {"type": "string"},
        "prompt_template": """你是一位资深产品经理。请根据以下信息编写一份完整的 PRD：

标题: {title}
描述: {description}
目标用户: {audience}

PRD 必须包含：
1. 需求概述
2. 目标用户画像
3. 功能范围 (IN/OUT of scope)
4. 用户故事 (至少 5 条)
5. 验收标准
6. 非功能需求
7. 里程碑规划""",
    },
    "test-strategy": {
        "name": "Test Strategy",
        "category": "testing",
        "version": "1.0.0",
        "author": "system",
        "description": "Generate comprehensive test strategies and test cases.",
        "tags": ["testing", "qa", "test-cases", "automation"],
        "input_schema": {
            "type": "object",
            "properties": {
                "feature": {"type": "string"},
                "tech_stack": {"type": "string"},
                "requirements": {"type": "string"},
            },
            "required": ["feature"],
        },
        "output_schema": {"type": "string"},
        "prompt_template": """你是 QA 负责人。请为以下功能制定测试策略：

功能: {feature}
技术栈: {tech_stack}
需求: {requirements}

输出：
1. 测试范围
2. 测试用例列表 (编号 + 步骤 + 预期结果)
3. 边界条件
4. 性能/安全测试项
5. 自动化建议""",
    },
    "deploy-checklist": {
        "name": "Deploy Checklist",
        "category": "ops",
        "version": "1.0.0",
        "author": "system",
        "description": "Pre-deployment validation checklist generation.",
        "tags": ["deploy", "ops", "checklist", "ci-cd"],
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "environment": {"type": "string"},
                "changes": {"type": "string"},
            },
            "required": ["service"],
        },
        "output_schema": {"type": "string"},
        "prompt_template": """请为以下部署生成检查清单：

服务: {service}
环境: {environment}
变更: {changes}

清单要涵盖：数据库迁移、配置变更、回滚方案、监控告警、灰度策略。""",
    },
    "api-design": {
        "name": "API Design",
        "category": "development",
        "version": "1.0.0",
        "author": "system",
        "description": "Design RESTful or GraphQL APIs following best practices.",
        "tags": ["api", "rest", "design", "openapi"],
        "input_schema": {
            "type": "object",
            "properties": {
                "resource": {"type": "string"},
                "operations": {"type": "string"},
                "constraints": {"type": "string"},
            },
            "required": ["resource"],
        },
        "output_schema": {"type": "string"},
        "prompt_template": """设计 {resource} 的 RESTful API：
操作: {operations}
约束: {constraints}

输出 OpenAPI 3.0 格式，包含路由、请求/响应 Schema、错误码、分页、认证。""",
    },
    "security-audit": {
        "name": "Security Audit",
        "category": "security",
        "version": "1.0.0",
        "author": "system",
        "description": "Security vulnerability analysis and remediation suggestions.",
        "tags": ["security", "audit", "vulnerability", "compliance"],
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "context": {"type": "string"},
            },
            "required": ["code"],
        },
        "output_schema": {"type": "string"},
        "prompt_template": """对以下代码进行安全审计：

```
{code}
```

上下文: {context}

检查: SQL注入、XSS、CSRF、认证绕过、权限提升、敏感信息泄露、不安全的依赖。
输出: 漏洞列表 (严重程度 + 位置 + 修复建议)。""",
    },
}


def _resolve_skill(skill_id: str) -> Optional[Dict[str, Any]]:
    """Look up a skill from built-in registry first, then filesystem."""
    entry = MARKETPLACE_REGISTRY.get(skill_id)
    if entry:
        return entry
    fs = get_fs_skill(skill_id)
    if fs:
        return {
            "name": fs["name"],
            "category": fs["category"],
            "version": fs["version"],
            "author": fs.get("author", "community"),
            "description": fs["description"],
            "tags": fs.get("tags", []),
            "input_schema": fs.get("input_schema", {}),
            "output_schema": fs.get("output_schema", {}),
            "prompt_template": fs.get("prompt_template", ""),
        }
    return None


async def execute_skill(
    db: AsyncSession,
    *,
    skill_id: str,
    input_data: Dict[str, Any],
    model: str = "",
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    """Execute a skill with schema validation, idempotency, and sandboxed timeout."""
    registry_entry = _resolve_skill(skill_id)
    if not registry_entry:
        return {"ok": False, "error": f"Unknown skill: {skill_id}"}

    schema = SkillSchema(
        id=skill_id,
        name=registry_entry["name"],
        category=registry_entry["category"],
        version=registry_entry.get("version", "1.0.0"),
        input_schema=registry_entry.get("input_schema", {}),
        output_schema=registry_entry.get("output_schema", {}),
        timeout_seconds=timeout_seconds,
    )

    try:
        validated_input = validate_input(schema, input_data)
    except ValueError as e:
        return {"ok": False, "error": f"Input validation failed: {e}"}

    idempotency_key = compute_idempotency_key(skill_id, validated_input)
    cached = check_idempotency(skill_id, validated_input)
    if cached and cached.status == "completed" and cached.output:
        return {"ok": True, "content": cached.output, "cached": True}

    record = record_execution_start(skill_id, validated_input)

    prompt_template = registry_entry.get("prompt_template", "")
    prompt = prompt_template.format(**{
        k: validated_input.get(k, "") for k in registry_entry.get("input_schema", {}).get("properties", {})
    })

    await emit_event("skill:executing", {"skillId": skill_id, "input": {k: str(v)[:100] for k, v in validated_input.items()}})

    try:
        from ..config import settings
        use_model = model or settings.llm_model

        result = await asyncio.wait_for(
            chat_completion(
                model=use_model,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=timeout_seconds,
        )

        if "error" in result:
            record_execution_complete(record, None, status="failed", error=result["error"])
            return {"ok": False, "error": result["error"]}

        content = result.get("content", "")
        record_execution_complete(record, content, status="completed")

        db_skill = await db.get(Skill, skill_id)
        if db_skill:
            db_skill.install_count = (db_skill.install_count or 0) + 1
            await db.flush()

        await emit_event("skill:completed", {"skillId": skill_id, "outputLength": len(content)})

        return {
            "ok": True,
            "content": content,
            "cached": False,
            "model": use_model,
            "usage": result.get("usage"),
        }

    except asyncio.TimeoutError:
        record_execution_complete(record, None, status="failed", error="Execution timeout")
        return {"ok": False, "error": f"Skill execution timed out after {timeout_seconds}s"}
    except Exception as e:
        record_execution_complete(record, None, status="failed", error=str(e))
        return {"ok": False, "error": str(e)}


async def get_marketplace_catalog() -> List[Dict[str, Any]]:
    """Return the full skill marketplace catalog (built-in + filesystem)."""
    catalog = []
    seen: set = set()

    for skill_id, entry in MARKETPLACE_REGISTRY.items():
        catalog.append({
            "id": skill_id,
            "name": entry["name"],
            "category": entry["category"],
            "version": entry.get("version", "1.0.0"),
            "author": entry.get("author", "community"),
            "description": entry["description"],
            "tags": entry.get("tags", []),
            "inputSchema": entry.get("input_schema", {}),
            "source": "builtin",
        })
        seen.add(skill_id)

    for skill_id, fs_entry in get_loaded_skills().items():
        if skill_id in seen:
            continue
        catalog.append({
            "id": skill_id,
            "name": fs_entry["name"],
            "category": fs_entry["category"],
            "version": fs_entry.get("version", "1.0.0"),
            "author": fs_entry.get("author", "community"),
            "description": fs_entry["description"],
            "tags": fs_entry.get("tags", []),
            "inputSchema": fs_entry.get("input_schema", {}),
            "source": "filesystem",
            "sourcePath": fs_entry.get("source_path", ""),
        })

    return catalog


STAGE_SKILL_MAP: Dict[str, List[str]] = {
    "planning": ["product", "analysis", "prd", "general"],
    "design": ["design", "product", "general"],
    "architecture": ["architecture", "design", "development"],
    "development": ["development", "security", "design"],
    "testing": ["testing", "development"],
    "reviewing": ["analysis", "product", "testing", "operations"],
    "deployment": ["deployment", "operations", "development"],
    "security": ["security", "testing", "specialized"],
}


async def get_skills_for_stage(
    db: AsyncSession,
    stage_id: str,
    role: str,
) -> List[Dict[str, str]]:
    """Get enabled skills relevant to a pipeline stage.

    Priority: trigger_stages exact match > fallback to STAGE_SKILL_MAP category match.
    """
    result = await db.execute(
        select(Skill).where(Skill.enabled.is_(True))
    )
    all_skills = result.scalars().all()

    matched: list[Skill] = []
    fallback: list[Skill] = []
    categories = STAGE_SKILL_MAP.get(stage_id, [])

    for s in all_skills:
        triggers = s.trigger_stages or []
        if triggers and stage_id in triggers:
            matched.append(s)
        elif not triggers and categories and s.category in categories:
            fallback.append(s)

    chosen = matched if matched else fallback[:5]

    return [
        {
            "name": s.name,
            "prompt": s.prompt_template[:2000],
            "execution_mode": s.execution_mode or "inline",
            "completion_criteria": s.completion_criteria or [],
            "allowed_tools": s.allowed_tools or [],
        }
        for s in chosen
        if s.prompt_template
    ]


async def install_skill(db: AsyncSession, skill_id: str) -> Optional[Skill]:
    """Install a marketplace skill to the database."""
    entry = MARKETPLACE_REGISTRY.get(skill_id)
    if not entry:
        return None

    existing = await db.get(Skill, skill_id)
    if existing:
        existing.version = entry.get("version", existing.version)
        existing.prompt_template = entry.get("prompt_template", existing.prompt_template)
        existing.input_schema = entry.get("input_schema", existing.input_schema)
        existing.output_schema = entry.get("output_schema", existing.output_schema)
        existing.tags = entry.get("tags", existing.tags)
        await db.flush()
        return existing

    skill = Skill(
        id=skill_id,
        name=entry["name"],
        category=entry["category"],
        description=entry["description"],
        version=entry.get("version", "1.0.0"),
        author=entry.get("author", "system"),
        prompt_template=entry.get("prompt_template", ""),
        input_schema=entry.get("input_schema", {}),
        output_schema=entry.get("output_schema", {}),
        tags=entry.get("tags", []),
        is_builtin=True,
        enabled=True,
    )
    db.add(skill)
    await db.flush()
    return skill
