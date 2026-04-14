"""Tests for tool schema validation and idempotency."""
import pytest

from app.services.tool_schema import (
    SkillSchema,
    RetryPolicy,
    validate_input,
    validate_output,
    compute_idempotency_key,
    check_idempotency,
    record_execution_start,
    record_execution_complete,
    BUILTIN_SCHEMAS,
)


def test_skill_schema_validation():
    schema = SkillSchema(
        id="test-skill",
        name="Test",
        category="development",
    )
    assert schema.idempotent is True
    assert schema.timeout_seconds == 300


def test_skill_id_validation():
    with pytest.raises(ValueError):
        SkillSchema(id="invalid id with spaces", name="Bad", category="dev")


def test_validate_input_required_field():
    schema = BUILTIN_SCHEMAS["code-review"]
    with pytest.raises(ValueError, match="Missing required field"):
        validate_input(schema, {"code": "x = 1"})


def test_validate_input_success():
    schema = BUILTIN_SCHEMAS["code-review"]
    result = validate_input(schema, {"code": "x = 1", "language": "python"})
    assert result["language"] == "python"


def test_validate_input_type_mismatch():
    schema = BUILTIN_SCHEMAS["code-review"]
    with pytest.raises(ValueError, match="must be string"):
        validate_input(schema, {"code": 123, "language": "python"})


def test_validate_output():
    schema = BUILTIN_SCHEMAS["code-review"]
    assert validate_output(schema, "Some review output") is True
    assert validate_output(schema, 12345) is False


def test_idempotency_key_deterministic():
    key1 = compute_idempotency_key("s1", {"a": 1, "b": 2})
    key2 = compute_idempotency_key("s1", {"b": 2, "a": 1})
    assert key1 == key2


def test_idempotency_key_different_inputs():
    key1 = compute_idempotency_key("s1", {"a": 1})
    key2 = compute_idempotency_key("s1", {"a": 2})
    assert key1 != key2


def test_idempotency_caching():
    record = record_execution_start("test-cache", {"x": 42})
    record_execution_complete(record, "result", status="completed")

    cached = check_idempotency("test-cache", {"x": 42})
    assert cached is not None
    assert cached.output == "result"


def test_builtin_schemas_exist():
    assert "code-review" in BUILTIN_SCHEMAS
    assert "prd-writing" in BUILTIN_SCHEMAS
    assert "deploy-checklist" in BUILTIN_SCHEMAS
