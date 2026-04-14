"""Tests for Lead Agent task decomposition logic."""
from app.services.lead_agent import _parse_plan, _group_by_dependency


def test_parse_plan_valid_json():
    content = '''Some analysis text
```json
{
  "analysis": "This is a simple task",
  "subtasks": [
    {"id": "st-1", "title": "Write PRD", "role": "product-manager", "prompt": "...", "dependsOn": [], "priority": 1}
  ],
  "strategy": "sequential",
  "estimatedComplexity": "low"
}
```'''
    plan = _parse_plan(content, "Test", "Desc")
    assert plan["analysis"] == "This is a simple task"
    assert len(plan["subtasks"]) == 1
    assert plan["subtasks"][0]["role"] == "product-manager"


def test_parse_plan_fallback_on_invalid():
    content = "Just some plain text without JSON"
    plan = _parse_plan(content, "My Task", "My Desc")
    assert plan["strategy"] == "sequential"
    assert len(plan["subtasks"]) == 1
    assert plan["subtasks"][0]["title"] == "My Task"


def test_group_by_dependency_no_deps():
    subtasks = [
        {"id": "a", "dependsOn": []},
        {"id": "b", "dependsOn": []},
        {"id": "c", "dependsOn": []},
    ]
    groups = _group_by_dependency(subtasks)
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_group_by_dependency_chain():
    subtasks = [
        {"id": "a", "dependsOn": []},
        {"id": "b", "dependsOn": ["a"]},
        {"id": "c", "dependsOn": ["b"]},
    ]
    groups = _group_by_dependency(subtasks)
    assert len(groups) == 3
    assert groups[0][0]["id"] == "a"
    assert groups[1][0]["id"] == "b"
    assert groups[2][0]["id"] == "c"


def test_group_by_dependency_diamond():
    subtasks = [
        {"id": "a", "dependsOn": []},
        {"id": "b", "dependsOn": ["a"]},
        {"id": "c", "dependsOn": ["a"]},
        {"id": "d", "dependsOn": ["b", "c"]},
    ]
    groups = _group_by_dependency(subtasks)
    assert len(groups) == 3
    assert groups[0][0]["id"] == "a"
    assert len(groups[1]) == 2  # b and c in parallel
    assert groups[2][0]["id"] == "d"
