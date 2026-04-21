"""Unit tests for the MCP dynamic-tool sandbox classifier.

Covers ``classify_mcp_tool`` + ``mcp_tool_allowed`` resolution order:

  1. ``metadata.category``  (server-declared, with synonyms)
  2. ``metadata.annotations`` (MCP-standard ``readOnlyHint`` /
     ``destructiveHint``)
  3. Prefix heuristic on the tool name (legacy)

Per-resolution outcomes are then validated against the read-only role
policy: only ``read``-classified tools are allowed for read-only roles,
``write`` / ``execute`` / ``unknown`` are denied.
"""
from __future__ import annotations

import pytest

from app.services.tools.registry import classify_mcp_tool, mcp_tool_allowed


# ─────────────────────────────────────────────────────────────────────
# classify_mcp_tool — resolution order and synonyms
# ─────────────────────────────────────────────────────────────────────


def test_classify_explicit_category_wins_over_prefix():
    """``category: read`` declared by the server overrides the
    ``delete_*`` prefix that would otherwise be classified as write."""
    cat, src = classify_mcp_tool("delete_thing", metadata={"category": "read"})
    assert cat == "read"
    assert src == "declared"


def test_classify_explicit_category_synonyms():
    """All synonyms collapse to the canonical tri-state."""
    for syn in ("ro", "readonly", "READ_ONLY", "query", "search", "fetch"):
        cat, src = classify_mcp_tool("foo", metadata={"category": syn})
        assert cat == "read", f"{syn!r} should map to read, got {cat}"
        assert src == "declared"
    for syn in ("rw", "mutate", "Mutation", "create", "update", "delete", "destructive"):
        cat, src = classify_mcp_tool("foo", metadata={"category": syn})
        assert cat == "write", f"{syn!r} should map to write, got {cat}"
        assert src == "declared"
    for syn in ("exec", "RUN", "command", "shell"):
        cat, src = classify_mcp_tool("foo", metadata={"category": syn})
        assert cat == "execute", f"{syn!r} should map to execute, got {cat}"
        assert src == "declared"


def test_classify_unknown_synonym_falls_through_to_prefix():
    """Garbage in ``category`` shouldn't shadow the heuristic — we fall
    through to the next resolution layer."""
    cat, src = classify_mcp_tool("get_thing", metadata={"category": "nonsense"})
    assert cat == "read"
    assert src == "prefix"


def test_classify_destructive_hint_outranks_read_prefix():
    """``annotations.destructiveHint == True`` overrides a misleading
    ``read_*`` prefix."""
    cat, src = classify_mcp_tool(
        "read_secret_and_burn_it",
        metadata={"annotations": {"destructiveHint": True}},
    )
    assert cat == "write"
    assert src == "annotation"


def test_classify_read_only_hint_outranks_write_prefix():
    """``annotations.readOnlyHint == True`` overrides a misleading
    ``delete_*`` prefix."""
    cat, src = classify_mcp_tool(
        "delete_status",
        metadata={"annotations": {"readOnlyHint": True}},
    )
    assert cat == "read"
    assert src == "annotation"


def test_classify_falls_back_to_prefix_when_no_metadata():
    cat, src = classify_mcp_tool("list_things")
    assert cat == "read"
    assert src == "prefix"

    cat, src = classify_mcp_tool("delete_things")
    assert cat == "write"
    assert src == "prefix"


def test_classify_unknown_when_no_signal():
    """No metadata + unrecognised prefix → ``unknown``."""
    cat, src = classify_mcp_tool("xyzzy_do_thing")
    assert cat == "unknown"
    assert src == "prefix"


# ─────────────────────────────────────────────────────────────────────
# mcp_tool_allowed — policy on top of the classifier
# ─────────────────────────────────────────────────────────────────────


def test_mcp_allowed_no_role_passes_through():
    """No role configured → back-compat allow regardless of category."""
    v = mcp_tool_allowed(None, "delete_everything")
    assert v["allowed"] is True
    assert v["reason"] == "no role configured"


def test_mcp_allowed_non_readonly_role_passes_through():
    """A non-read-only role (e.g. engineer) is allowed write tools."""
    v = mcp_tool_allowed("engineer", "delete_repo")
    assert v["allowed"] is True
    assert v["category"] == "write"


def test_mcp_allowed_readonly_role_blocks_write_via_annotation():
    v = mcp_tool_allowed(
        "ceo", "do_thing",
        metadata={"annotations": {"destructiveHint": True}},
    )
    assert v["allowed"] is False
    assert v["category"] == "write"
    assert v["source"] == "annotation"
    assert "do_thing" in v["reason"]


def test_mcp_allowed_readonly_role_blocks_execute():
    """``execute`` is treated as write for sandbox purposes — read-only
    roles can't run shells/deploy commands."""
    v = mcp_tool_allowed("ceo", "weird_op", metadata={"category": "exec"})
    assert v["allowed"] is False
    assert v["category"] == "execute"


def test_mcp_allowed_readonly_role_default_denies_unknown():
    """Default-deny when we can't classify; reason mentions both that
    we couldn't classify and what to do about it."""
    v = mcp_tool_allowed("ceo", "mcp__weird__opaque")
    assert v["allowed"] is False
    assert v["category"] == "unknown"
    assert "could not be classified" in v["reason"]


def test_mcp_allowed_readonly_role_allows_declared_read_on_write_name():
    """Server-declared ``category: read`` lets a read-only role through
    even when the tool name looks dangerous."""
    v = mcp_tool_allowed(
        "ceo", "delete_thing", metadata={"category": "read"},
    )
    assert v["allowed"] is True
    assert v["source"] == "declared"


@pytest.mark.parametrize("role", ["security", "legal", "finance", "marketing", "ceo"])
def test_mcp_allowed_all_readonly_roles_block_write(role):
    """Smoke: every role in READ_ONLY_ROLES rejects a write tool."""
    v = mcp_tool_allowed(role, "create_thing")
    assert v["allowed"] is False, f"{role} should deny create_thing"
