"""Tests for self-verification logic."""
from __future__ import annotations

from app.services.self_verify import (
    verify_stage_output,
    VerifyStatus,
)


def test_planning_output_passes():
    output = """# PRD
## 目标
Build a todo app

## 范围
### IN-SCOPE
- CRUD operations
### OUT-OF-SCOPE
- Social features

## 用户故事
- As a user, I want to create tasks
- As a user, I want to mark tasks done
- As a user, I want to delete tasks

## 验收标准
- All CRUD operations work
- Response time < 200ms
"""
    result = verify_stage_output("planning", "product-manager", output)
    assert result.overall_status in (VerifyStatus.PASS, VerifyStatus.WARN)
    assert result.auto_proceed is True


def test_short_output_fails():
    result = verify_stage_output("planning", "product-manager", "Too short")
    assert result.overall_status == VerifyStatus.FAIL
    assert result.auto_proceed is False


def test_development_needs_code_blocks():
    output = """# 项目结构
/src
  /components

# 代码
Here is some code but no code blocks.

# 依赖
None.
""" + "x" * 1000
    result = verify_stage_output("development", "developer", output)
    checks = {c.check_name: c.status for c in result.checks}
    assert checks.get("keywords") in (VerifyStatus.FAIL, VerifyStatus.WARN)


def test_placeholder_detection():
    output = "# Plan\nThis is a TODO placeholder\n" + "x" * 600
    result = verify_stage_output("planning", "product-manager", output)
    checks = {c.check_name: c.status for c in result.checks}
    assert checks.get("no_placeholder") == VerifyStatus.WARN
