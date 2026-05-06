"""Unit tests for the SWE-Bench harness (pure logic only — no LLM / docker / network)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.swebench import dataset, evaluator, patch_utils
from scripts.swebench.agent import (
    _parse_selected_paths,
    _shortlist_paths,
    run_agentless_attempt,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "swebench_sample.jsonl"


# ---------------------------------------------------------------------------
# patch_utils
# ---------------------------------------------------------------------------


def test_extract_unified_diff_from_diff_fenced_block():
    text = (
        "Sure, here's the patch:\n\n"
        "```diff\n"
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old\n"
        "+new\n"
        "```\n"
        "Hope that helps!"
    )
    diff = patch_utils.extract_unified_diff(text)
    assert diff is not None
    assert "diff --git a/foo.py b/foo.py" in diff
    assert "@@ -1,2 +1,2 @@" in diff
    assert diff.endswith("\n")


def test_extract_unified_diff_from_plain_text_no_fence():
    text = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    assert patch_utils.extract_unified_diff(text) is not None


def test_extract_unified_diff_rejects_prose_only():
    assert patch_utils.extract_unified_diff("I would patch foo.py to fix the bug.") is None


def test_extract_unified_diff_picks_largest_candidate():
    """When two candidates exist, prefer the longer (more complete) one."""
    bigger_diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,3 @@\n"
        " line\n-old1\n+new1\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-old\n+new\n"
    )
    smaller = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"
    )
    text = f"```diff\n{smaller}```\n\n```diff\n{bigger_diff}```"
    diff = patch_utils.extract_unified_diff(text)
    assert diff is not None
    assert "b.py" in diff


def test_patch_stats_counts_hunks_and_lines():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n+++ b/a.py\n"
        "@@ -1,2 +1,3 @@\n"
        " keep\n-old\n+new1\n+new2\n"
        "@@ -10,1 +11,0 @@\n-bye\n"
    )
    s = patch_utils.patch_stats(diff)
    assert s.hunks == 2
    assert s.additions == 2
    assert s.deletions == 2
    assert s.files_changed >= 1
    assert not s.is_empty


def test_looks_like_noop_detects_empty():
    assert patch_utils.looks_like_noop("")
    assert patch_utils.looks_like_noop("just words, no diff")


def test_split_per_file_separates_two_files():
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-m\n+n\n"
    )
    pieces = patch_utils.split_per_file(diff)
    assert [p[0] for p in pieces] == ["a.py", "b.py"]
    assert "a.py" in pieces[0][1]
    assert "b.py" in pieces[1][1]


# ---------------------------------------------------------------------------
# dataset
# ---------------------------------------------------------------------------


def test_load_instances_from_local_jsonl():
    insts = dataset.load_instances(str(FIXTURE_PATH))
    assert len(insts) == 2
    first = insts[0]
    assert first.instance_id == "demo__demo-1"
    assert first.repo == "demo/demo"
    assert first.fail_to_pass == ["tests/test_calc.py::test_negatives"]
    assert first.pass_to_pass == ["tests/test_calc.py::test_positives"]


def test_load_instances_filter_by_only_ids():
    insts = dataset.load_instances(str(FIXTURE_PATH), only_ids=["demo__demo-2"])
    assert len(insts) == 1
    assert insts[0].instance_id == "demo__demo-2"


def test_load_instances_limit():
    insts = dataset.load_instances(str(FIXTURE_PATH), limit=1)
    assert len(insts) == 1


def test_load_instances_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        dataset.load_instances(str(tmp_path / "no-such.jsonl"))


def test_load_instances_invalid_record_raises(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"instance_id": "x"}\n')
    with pytest.raises(ValueError):
        dataset.load_instances(str(bad))


# ---------------------------------------------------------------------------
# agent — pure helpers (LLM + filesystem mocked)
# ---------------------------------------------------------------------------


def test_shortlist_paths_keeps_token_matches_first():
    paths = [f"src/foo/file_{i}.py" for i in range(50)] + ["src/special_widget/core.py", "src/utils/special_widget.py"]
    issue = "The special_widget breaks when input is None"
    result = _shortlist_paths(paths, issue, limit=5)
    assert any("special_widget" in p for p in result[:2])


def test_shortlist_paths_falls_back_to_alpha_when_no_match():
    paths = ["zeta.py", "alpha.py", "beta.py"]
    out = _shortlist_paths(paths, "totally unrelated wording", limit=10)
    assert out == ["alpha.py", "beta.py", "zeta.py"]


def test_parse_selected_paths_parses_json_object():
    valid = {"a/x.py", "b/y.py"}
    text = '```json\n{"files": ["a/x.py", "c/never.py"]}\n```'
    assert _parse_selected_paths(text, valid=valid) == ["a/x.py"]


def test_parse_selected_paths_falls_back_to_line_scan():
    valid = {"foo.py", "bar.py"}
    text = "I think we should look at:\n- foo.py\n- bar.py\n- never.py"
    assert sorted(_parse_selected_paths(text, valid=valid)) == ["bar.py", "foo.py"]


@pytest.mark.asyncio
async def test_run_agentless_attempt_full_path(tmp_path: Path):
    (tmp_path / "src").mkdir()
    target = tmp_path / "src" / "calc.py"
    target.write_text("def add(a, b):\n    return 0\n")
    (tmp_path / "src" / "noise.py").write_text("# unrelated\n")

    canned_diff = (
        "diff --git a/src/calc.py b/src/calc.py\n"
        "--- a/src/calc.py\n+++ b/src/calc.py\n"
        "@@ -1,2 +1,2 @@\n def add(a, b):\n-    return 0\n+    return a + b\n"
    )

    async def fake_llm(phase, _msgs):
        if phase == "locate":
            return {"content": '```json\n{"files": ["src/calc.py"]}\n```',
                    "usage": {"input_tokens": 100, "output_tokens": 20}}
        return {"content": f"```diff\n{canned_diff}```",
                "usage": {"input_tokens": 200, "output_tokens": 80}}

    attempt = await run_agentless_attempt(
        instance_id="demo__demo-1",
        problem_statement="add(a,b) returns 0 instead of a+b",
        repo_dir=tmp_path,
        llm=fake_llm,
    )
    assert attempt.ok
    assert attempt.patch is not None
    assert "return a + b" in attempt.patch
    assert attempt.selected_files == ["src/calc.py"]
    assert attempt.token_usage["input_tokens"] == 300
    assert attempt.token_usage["output_tokens"] == 100


@pytest.mark.asyncio
async def test_run_agentless_attempt_handles_no_diff_in_response(tmp_path: Path):
    (tmp_path / "x.py").write_text("# nothing\n")

    async def fake_llm(phase, _msgs):
        if phase == "locate":
            return {"content": '{"files": ["x.py"]}'}
        return {"content": "I think the bug is in x.py."}

    attempt = await run_agentless_attempt(
        instance_id="x__x-1",
        problem_statement="x.py is broken",
        repo_dir=tmp_path,
        llm=fake_llm,
    )
    assert not attempt.ok
    assert attempt.patch is None
    assert attempt.error and "no unified diff" in attempt.error


# ---------------------------------------------------------------------------
# evaluator — split_results pure logic
# ---------------------------------------------------------------------------


def test_split_results_marks_passed_and_failed():
    pytest_output = (
        "tests/test_calc.py::test_negatives PASSED\n"
        "tests/test_calc.py::test_positives PASSED\n"
        "tests/test_text.py::test_empty FAILED\n"
    )
    passed, failed = evaluator._split_results(
        ["tests/test_calc.py::test_negatives", "tests/test_text.py::test_empty"],
        pytest_output,
    )
    assert passed == ["tests/test_calc.py::test_negatives"]
    assert failed == ["tests/test_text.py::test_empty"]


def test_split_results_default_pass_for_pass_to_pass():
    """If a PASS_TO_PASS test isn't mentioned in output (e.g. test runner skipped it),
    we conservatively assume it still passes — same convention SWE-Bench harness uses."""
    passed, regressed = evaluator._split_results(
        ["tests/test_calc.py::test_positives"],
        output="some unrelated output",
        default_pass=True,
    )
    assert passed == ["tests/test_calc.py::test_positives"]
    assert regressed == []


def test_default_pytest_command_quotes_safely():
    cmd = evaluator._default_pytest_command(["a/b.py::test_one", "x.py::test_two"])
    assert cmd.startswith("python -m pytest ")
    assert "a/b.py::test_one" in cmd
    assert "x.py::test_two" in cmd


def test_default_pytest_command_when_empty():
    cmd = evaluator._default_pytest_command([])
    assert cmd == "python -m pytest -x --tb=short"
