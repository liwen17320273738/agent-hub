"""
Tool Standardization — Skill Schema 验证 + 幂等性保障

每个 Skill 必须遵循严格的 Schema 定义:
1. input_schema: JSON Schema 验证输入
2. output_schema: JSON Schema 验证输出
3. idempotency_key: 确保重复执行不会产生副作用
4. retry_policy: 失败重试策略
5. timeout: 执行超时限制
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from enum import Enum
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)


class RetryPolicy(BaseModel):
    max_retries: int = 3
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 30.0


class SkillSchema(BaseModel):
    """Strict schema definition for a skill."""
    id: str
    name: str
    version: str = "1.0.0"
    category: str

    input_schema: Dict[str, Any] = {}
    output_schema: Dict[str, Any] = {}

    timeout_seconds: int = 300
    retry_policy: RetryPolicy = RetryPolicy()
    idempotent: bool = True

    required_permissions: List[str] = []
    required_tools: List[str] = []
    side_effects: List[str] = []  # e.g. ["file_write", "api_call", "database_write"]

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v or not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Skill ID must be alphanumeric with hyphens/underscores")
        return v


class SkillExecutionRecord(BaseModel):
    """Record of a single skill execution for idempotency tracking."""
    skill_id: str
    idempotency_key: str
    input_hash: str
    output: Optional[str] = None
    status: str = "pending"  # pending / running / completed / failed / skipped
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: int = 0
    retry_count: int = 0
    error: Optional[str] = None


_execution_cache: Dict[str, SkillExecutionRecord] = {}


def compute_idempotency_key(skill_id: str, input_data: Dict[str, Any]) -> str:
    """Deterministic key based on skill + input for deduplication."""
    canonical = json.dumps({"skill": skill_id, "input": input_data}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def validate_input(schema: SkillSchema, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate skill input against its JSON Schema.
    Returns normalized input or raises ValueError.
    """
    if not schema.input_schema:
        return input_data

    required = schema.input_schema.get("required", [])
    properties = schema.input_schema.get("properties", {})

    errors = []
    for field in required:
        if field not in input_data:
            errors.append(f"Missing required field: {field}")

    for field, value in input_data.items():
        if field in properties:
            prop_def = properties[field]
            expected_type = prop_def.get("type", "string")
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"Field '{field}' must be string, got {type(value).__name__}")
            elif expected_type == "integer" and not isinstance(value, int):
                errors.append(f"Field '{field}' must be integer, got {type(value).__name__}")
            elif expected_type == "number" and not isinstance(value, (int, float)):
                errors.append(f"Field '{field}' must be number, got {type(value).__name__}")
            elif expected_type == "boolean" and not isinstance(value, bool):
                errors.append(f"Field '{field}' must be boolean, got {type(value).__name__}")

            max_len = prop_def.get("maxLength")
            if max_len and isinstance(value, str) and len(value) > max_len:
                errors.append(f"Field '{field}' exceeds max length {max_len}")

    if errors:
        raise ValueError(f"Input validation failed: {'; '.join(errors)}")

    return input_data


def validate_output(schema: SkillSchema, output_data: Any) -> bool:
    """Validate skill output against its schema."""
    if not schema.output_schema:
        return True

    if schema.output_schema.get("type") == "string":
        return isinstance(output_data, str)
    if schema.output_schema.get("type") == "object":
        return isinstance(output_data, dict)
    return True


def check_idempotency(skill_id: str, input_data: Dict[str, Any]) -> Optional[SkillExecutionRecord]:
    """Check if this exact skill+input combination was already executed."""
    key = compute_idempotency_key(skill_id, input_data)
    record = _execution_cache.get(key)
    if record and record.status == "completed":
        logger.info(f"[idempotency] Skill {skill_id} already executed with same input, returning cached result")
        return record
    return None


def record_execution_start(skill_id: str, input_data: Dict[str, Any]) -> SkillExecutionRecord:
    """Record the start of a skill execution."""
    key = compute_idempotency_key(skill_id, input_data)
    input_hash = hashlib.sha256(json.dumps(input_data, sort_keys=True).encode()).hexdigest()[:16]

    record = SkillExecutionRecord(
        skill_id=skill_id,
        idempotency_key=key,
        input_hash=input_hash,
        status="running",
        started_at=time.time(),
    )
    _execution_cache[key] = record
    return record


def record_execution_complete(
    record: SkillExecutionRecord,
    output: str,
    status: str = "completed",
    error: Optional[str] = None,
) -> SkillExecutionRecord:
    """Record the completion of a skill execution."""
    record.status = status
    record.output = output
    record.error = error
    record.completed_at = time.time()
    record.duration_ms = int((record.completed_at - record.started_at) * 1000)
    _execution_cache[record.idempotency_key] = record
    return record


async def execute_with_retry(
    skill_schema: SkillSchema,
    execute_fn,
    input_data: Dict[str, Any],
) -> SkillExecutionRecord:
    """Execute a skill with retry policy and idempotency checking."""
    cached = check_idempotency(skill_schema.id, input_data)
    if cached and skill_schema.idempotent:
        cached.status = "skipped"
        return cached

    validate_input(skill_schema, input_data)
    record = record_execution_start(skill_schema.id, input_data)

    policy = skill_schema.retry_policy
    last_error = None
    backoff = policy.backoff_seconds

    for attempt in range(policy.max_retries + 1):
        try:
            record.retry_count = attempt
            result = await execute_fn(input_data)

            if validate_output(skill_schema, result):
                return record_execution_complete(record, str(result))
            else:
                last_error = "Output validation failed"
                logger.warning(f"[tool] {skill_schema.id} output validation failed on attempt {attempt + 1}")

        except Exception as e:
            last_error = str(e)
            logger.warning(f"[tool] {skill_schema.id} attempt {attempt + 1} failed: {e}")

        if attempt < policy.max_retries:
            import asyncio
            await asyncio.sleep(min(backoff, policy.max_backoff_seconds))
            backoff *= policy.backoff_multiplier

    return record_execution_complete(record, "", status="failed", error=last_error)


# --- Built-in Skill Schemas ---

BUILTIN_SCHEMAS: Dict[str, SkillSchema] = {
    "code-review": SkillSchema(
        id="code-review",
        name="代码审查",
        category="development",
        input_schema={
            "type": "object",
            "required": ["code", "language"],
            "properties": {
                "code": {"type": "string", "maxLength": 50000},
                "language": {"type": "string"},
                "focus_areas": {"type": "string"},
            },
        },
        output_schema={"type": "string"},
        timeout_seconds=120,
        idempotent=True,
        side_effects=[],
    ),
    "prd-writing": SkillSchema(
        id="prd-writing",
        name="PRD 撰写",
        category="product",
        input_schema={
            "type": "object",
            "required": ["title", "description"],
            "properties": {
                "title": {"type": "string", "maxLength": 500},
                "description": {"type": "string", "maxLength": 10000},
                "target_users": {"type": "string"},
            },
        },
        output_schema={"type": "string"},
        timeout_seconds=180,
        idempotent=True,
    ),
    "deploy-checklist": SkillSchema(
        id="deploy-checklist",
        name="部署检查",
        category="operations",
        input_schema={
            "type": "object",
            "required": ["service_name"],
            "properties": {
                "service_name": {"type": "string"},
                "environment": {"type": "string"},
                "changes_summary": {"type": "string"},
            },
        },
        output_schema={"type": "string"},
        timeout_seconds=120,
        idempotent=True,
        required_permissions=["deploy"],
        side_effects=["deployment"],
    ),
}
