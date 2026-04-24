"""Tests for self-verification logic."""
from __future__ import annotations

from app.services.self_verify import (
    verify_stage_output,
    VerifyStatus,
)


def test_planning_output_passes():
    output = """# PRD
## 目标
Build a task list web application for personal productivity: users manage items with due dates,
tags, and optional reminders. Success means sub-200ms API latency for list operations under normal load.

## 范围
### IN-SCOPE
- CRUD operations on tasks and lists
- Basic filtering and sorting
### OUT-OF-SCOPE
- Social features and shared workspaces

## 用户故事
- As a user, I want to create tasks so that I can track work items
- As a user, I want to mark tasks done so that I can see progress
- As a user, I want to delete tasks so that I can keep the list tidy

## 验收标准
- All CRUD operations work end-to-end against the REST API
- Response time p95 < 200ms for list endpoints in integration tests
- Errors return structured JSON with a stable error code

## 优先级
- P0: create/read/update/delete tasks
- P1: filters and sorting
- P2: export and notifications later
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
