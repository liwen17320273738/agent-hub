"""Unit tests for the learning-loop A/B shadow segmentation helpers.

The two pure helpers under test:

  * ``_targeting_matches(t, template, complexity)`` — does a single
    override apply to a given (template, complexity) call site?
  * ``_targeting_overlap(a, b)`` — do two overrides' targeting dicts
    have any segment in common? Used by ``_archive_overlapping`` to
    decide whether activating an override should retire others.

Empty dicts / missing keys / empty lists mean "match anything"
(legacy back-compat for rows that pre-date the targeting feature).
"""
from __future__ import annotations

from app.services.learning_loop import _targeting_matches, _targeting_overlap


# ─────────────────────────────────────────────────────────────────────
# _targeting_matches
# ─────────────────────────────────────────────────────────────────────


def test_targeting_empty_matches_everything():
    """No targeting → universal override; pre-feature rows must keep
    working."""
    assert _targeting_matches({}, template="qa", complexity="light") is True
    assert _targeting_matches({}, template=None, complexity=None) is True
    assert _targeting_matches(None, template="qa", complexity="light") is True


def test_targeting_template_filter():
    t = {"templates": ["qa"]}
    assert _targeting_matches(t, template="qa", complexity="light") is True
    assert _targeting_matches(t, template="design", complexity="light") is False


def test_targeting_template_with_call_site_missing_segment():
    """Call site without a template short-circuits the template filter
    — the implementation treats a missing call-site segment as
    "constraint not applicable", same as the legacy back-compat case
    for empty targeting. This keeps old code paths that don't pass a
    template (e.g. ad-hoc /run-stage calls) from being silently
    excluded by every targeted shadow.
    """
    t = {"templates": ["qa"]}
    assert _targeting_matches(t, template=None, complexity="light") is True


def test_targeting_complexity_filter():
    t = {"complexities": ["light"]}
    assert _targeting_matches(t, template="qa", complexity="light") is True
    assert _targeting_matches(t, template="qa", complexity="heavy") is False


def test_targeting_combined_is_and():
    """Both ``templates`` and ``complexities`` must intersect — AND."""
    t = {"templates": ["qa"], "complexities": ["light", "medium"]}
    assert _targeting_matches(t, template="qa", complexity="light") is True
    assert _targeting_matches(t, template="qa", complexity="medium") is True
    assert _targeting_matches(t, template="qa", complexity="heavy") is False
    assert _targeting_matches(t, template="design", complexity="light") is False


def test_targeting_empty_list_means_anything():
    """``{"templates": []}`` is the same as omitting the key — no filter."""
    t = {"templates": [], "complexities": ["light"]}
    assert _targeting_matches(t, template="qa", complexity="light") is True
    assert _targeting_matches(t, template="design", complexity="light") is True


# ─────────────────────────────────────────────────────────────────────
# _targeting_overlap
# ─────────────────────────────────────────────────────────────────────


def test_overlap_disjoint_templates():
    assert _targeting_overlap(
        {"templates": ["qa"]}, {"templates": ["design"]},
    ) is False


def test_overlap_intersecting_templates():
    assert _targeting_overlap(
        {"templates": ["qa", "design"]}, {"templates": ["design"]},
    ) is True


def test_overlap_empty_is_universal():
    """An empty / missing targeting dict is "match everything" → it
    overlaps with literally any other targeting."""
    assert _targeting_overlap({}, {"templates": ["qa"]}) is True
    assert _targeting_overlap({"complexities": ["light"]}, {}) is True
    assert _targeting_overlap({}, {}) is True


def test_overlap_disjoint_complexity():
    """Even if templates intersect, disjoint complexities → no overlap."""
    a = {"templates": ["qa"], "complexities": ["light"]}
    b = {"templates": ["qa"], "complexities": ["heavy"]}
    assert _targeting_overlap(a, b) is False


def test_overlap_template_intersect_complexity_intersect():
    a = {"templates": ["qa", "design"], "complexities": ["light", "medium"]}
    b = {"templates": ["design"], "complexities": ["medium", "heavy"]}
    assert _targeting_overlap(a, b) is True
