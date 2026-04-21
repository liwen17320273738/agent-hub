# SWE-Bench Benchmark — agent-hub

This document is the **reproduction guide** for the SWE-Bench numbers we publish
in the launch post. Honesty matters more than the number — the entire harness,
prompt set, and per-instance traces live in this repo. Anyone with an LLM key
and Docker can re-run it.

> Status: harness ready, single-instance smoke test passing in CI, full Lite/Verified
> runs are budgeted but not yet executed (see [§Cost & Schedule](#cost--schedule)).

---

## TL;DR

| Subset                | Instances | Resolved | Pass-rate | Wall time | Cost (USD) | Model               |
|-----------------------|-----------|----------|-----------|-----------|------------|---------------------|
| `<TBD>` Lite          | 300       | `<TBD>`  | `<TBD>`%  | `<TBD>` h | `<TBD>`    | `claude-sonnet-4-5` |
| `<TBD>` Verified      | 500       | `<TBD>`  | `<TBD>`%  | `<TBD>` h | `<TBD>`    | `claude-sonnet-4-5` |

Per-instance JSON, raw LLM responses, and applied patches are committed under
`docs/benchmarks/<run-id>/`. The schema is described in
[§Output layout](#output-layout) below.

---

## What we measure

We follow the **upstream SWE-Bench scoring rules** verbatim:

* An instance is **resolved** iff every test in its `FAIL_TO_PASS` list passes
  *and* every test in its `PASS_TO_PASS` list still passes after applying the
  agent's patch.
* We use the same **Lite** and **Verified** subsets published by Princeton NLP
  (`princeton-nlp/SWE-bench_Lite` and `princeton-nlp/SWE-bench_Verified`).
* **No special-cased instances**, no per-instance prompt tweaks, no human
  intervention during a run. The harness must finish on its own.

Where we deliberately differ from the official harness:

* **Sandbox**: we use agent-hub's `docker_sandbox.docker_exec` (the same
  sandbox the production system uses for code execution). Same Docker image,
  same isolation flags. The official harness uses its own per-instance
  containers; results may differ at the noise level.
* **Agent**: we use a 3-call **Agentless**-style loop (locate → read → patch).
  This is the simplest credible baseline and the one that makes our numbers
  comparable to public Agentless reports.

---

## Architecture

```text
SWE-Bench dataset (HF or local JSONL)
        │
        ▼
backend/scripts/swebench/dataset.py        # load + normalize instances
        │
        ▼
backend/scripts/swebench/repo_workspace.py # bare-clone cache → per-instance worktree
        │                                  # apply test_patch (sets up failing tests)
        ▼
backend/scripts/swebench/agent.py          # 3-phase Agentless loop
        │   - locate (LLM call 1)
        │   - read   (no LLM, file IO)
        │   - patch  (LLM call 2)
        │   ↓
        │   patch_utils.extract_unified_diff()
        ▼
backend/scripts/swebench/evaluator.py      # git apply --check, git apply
        │                                  # run tests via docker_sandbox
        │                                  # split results by FAIL_TO_PASS / PASS_TO_PASS
        ▼
docs/benchmarks/<run-id>/
        summary.json               # aggregate scores
        <instance_id>/result.json  # per-instance scoring + traces
        <instance_id>/agent.patch  # patch the agent produced
        <instance_id>/llm_response_*.txt
```

Module reference:

| Module | Lines | Responsibility |
|---|---|---|
| `scripts/swebench/dataset.py`        | ~150 | HF + JSONL loader, schema normalization (`SweInstance` dataclass) |
| `scripts/swebench/patch_utils.py`    | ~120 | Pure-logic diff extraction, sanity checks, per-file split |
| `scripts/swebench/repo_workspace.py` | ~140 | Bare-clone cache, per-instance worktree, `git apply` for `test_patch` |
| `scripts/swebench/agent.py`          | ~190 | 3-phase Agentless loop, file-shortlist heuristic |
| `scripts/swebench/evaluator.py`      | ~220 | Apply patch, run tests in Docker (or local fallback), score |
| `scripts/swebench/__main__.py`       | ~180 | CLI entry, parallel orchestration, JSON output |

---

## Reproduction — quickstart

### Prerequisites

1. **Python 3.11+** with [`uv`](https://docs.astral.sh/uv/)
2. **git** ≥ 2.30 (for `git apply --allow-empty`)
3. **Docker** (`docker info` must succeed) — strongly recommended; without it
   you must pass `--allow-local-exec` and accept the security implications
4. **LLM provider key** — pick one and export it:
   * `ANTHROPIC_API_KEY` (recommended baseline)
   * `OPENAI_API_KEY`
   * `DEEPSEEK_API_KEY`
   * `DASHSCOPE_API_KEY`
5. **~32 GB RAM**, **~100 GB disk** for the Docker images and per-repo caches.
   Estimated network: ~50 GB to clone the 300 unique repos in Lite.

### Smoke test (no API key, no Docker, no network)

Use this in CI to prove the harness loads. It only verifies dataset shape and
emits a summary; it does **not** call the LLM or run tests.

```bash
cd backend
PYTHONPATH=. uv run python -m scripts.swebench \
  --source tests/unit/fixtures/swebench_sample.jsonl \
  --output-dir /tmp/swebench-smoke \
  --dry-run
cat /tmp/swebench-smoke/summary.json
```

Expected output: `"dry_run": true, "instance_count": 2, ...`.

### Single instance — full pipeline

```bash
export ANTHROPIC_API_KEY=sk-ant-...

./scripts/run-swebench.sh \
  --source hf:princeton-nlp/SWE-bench_Lite \
  --only django__django-15814 \
  --output-dir ./swebench_runs \
  --model claude-sonnet-4-5
```

Wall time: typically 2–5 minutes for a small Django instance. Cost: ~$0.10–0.30.

### Lite full run — 300 instances, 4-way parallel

```bash
./scripts/run-swebench.sh \
  --source hf:princeton-nlp/SWE-bench_Lite \
  --output-dir ./swebench_runs/lite-$(date +%Y%m%d) \
  --concurrency 4 \
  --model claude-sonnet-4-5 \
  --test-timeout 900
```

Wall time: 4–8 hours depending on LLM rate limits and repo sizes.
Cost: ~$40–80 with Claude Sonnet 4.5 (see [§Cost & Schedule](#cost--schedule)).

### Verified full run — 500 instances

Same command, swap `SWE-bench_Lite` → `SWE-bench_Verified`. Cost ~$80–150.

---

## Output layout

```text
swebench_runs/<run-id>/
├── summary.json
└── <instance_id>/
    ├── result.json
    ├── agent.patch        # only if the agent produced one
    ├── llm_response_0.txt # raw "locate" response
    └── llm_response_1.txt # raw "patch" response
```

### `summary.json` schema

```jsonc
{
  "source": "hf:princeton-nlp/SWE-bench_Lite",
  "model": "claude-sonnet-4-5",
  "instance_count": 300,
  "resolved": 102,
  "resolved_pct": 34.0,
  "duration_s": 21540.5,
  "results": [ /* InstanceResult.to_dict() entries */ ]
}
```

### `result.json` (per instance) schema

```jsonc
{
  "instance_id": "django__django-15814",
  "resolved": true,
  "apply_ok": true,
  "fail_to_pass_passed": ["tests/regressiontests/.../test_x"],
  "fail_to_pass_failed": [],
  "pass_to_pass_passed": [...],
  "pass_to_pass_regressed": [],
  "duration_s": 142.31,
  "engine": "docker",
  "agent": {
    "ok": true,
    "selected_files": ["django/db/models/query.py"],
    "stats": { "files_changed": 1, "hunks": 1, "additions": 3, "deletions": 1 },
    "token_usage": { "input_tokens": 18421, "output_tokens": 412 }
  }
}
```

---

## Cost & Schedule

LLM cost is the dominant variable. Conservative estimates with Claude Sonnet 4.5
at the time of writing (Apr 2026):

| Phase    | Avg input tokens | Avg output tokens | Cost / instance |
|----------|------------------|-------------------|-----------------|
| Locate   | ~6 K             | ~0.1 K            | $0.02           |
| Patch    | ~25 K            | ~0.5 K            | $0.09           |
| **Total**| ~31 K            | ~0.6 K            | **~$0.11**      |

* Lite (300 inst.): **~$33–60** per full run, ~6 h wall time at 4-way parallel
* Verified (500 inst.): **~$55–110** per full run, ~10 h wall time
* Allow ≥ 2× budget for retries, prompt iteration, and wasted runs

**Cheaper alternatives**:

* DeepSeek V3 / Qwen 2.5 — ~10× cheaper. Expected score: 5–10% lower than Sonnet.
* Claude Haiku — ~5× cheaper. Expected score: ~10–15% lower.
* Local Llama-70B / Qwen-2.5-72B — free after hardware. Expected score: ~30% lower
  than frontier; useful as a comparison data point but not a leaderboard run.

---

## Known limitations & honest caveats

1. **Agent is `Agentless`-style, not tool-using.** Adding repo search /
   inter-file navigation is a known +5–10% but adds 2–3× cost. Out of scope
   for the launch baseline.
2. **No retries.** Some Agentless reports use majority-vote across 5–10 sample
   patches per instance. We run exactly one. This costs us a few percent on
   hard instances but keeps the cost-per-percent honest.
3. **No fine-tuned RAG.** We don't index the repo into a vector store; the
   shortlisting heuristic is plain token overlap. Improving this is an
   obvious next step but again increases the surface area.
4. **Test parser is best-effort.** We grep pytest output for `PASSED` /
   `FAILED` lines tagged with the test ID. Repos with custom runners (some
   sphinx / pylint instances) may need per-repo overrides in a follow-up.
5. **Docker images are pulled lazily.** First run on a cold cache may
   download 10+ GB of language runtime images (Python, Node, Ruby).

---

## How to validate a published score

Anyone can rerun the published number:

```bash
git clone https://github.com/<ORG>/agent-hub
cd agent-hub
git checkout v<RELEASE>          # the commit the score was published at
cd backend && uv sync
export ANTHROPIC_API_KEY=...
PYTHONPATH=. uv run python -m scripts.swebench \
    --source hf:princeton-nlp/SWE-bench_Verified \
    --output-dir ./repro \
    --concurrency 4
diff -u docs/benchmarks/<run-id>/summary.json ./repro/summary.json
```

Differences > 1% should be reproducible and reported as a GitHub issue.

---

## Roadmap

| Item                                              | Status   | ETA  |
|---------------------------------------------------|----------|------|
| Harness skeleton + unit tests                     | ✅ done  | —    |
| Single-instance smoke run                         | ✅ done  | —    |
| Lite full run + published summary                 | 🟡 ready to launch | T+1 week |
| Verified full run + published summary             | 🟡 ready to launch | T+2 weeks |
| Per-repo test-runner overrides (sphinx, pylint)   | ⏳ planned | T+3 weeks |
| Tool-using agent loop (search + read + patch)     | ⏳ planned | T+6 weeks |
| Multi-sample majority-vote (Agentless-Pass@K)     | ⏳ planned | T+6 weeks |

---

## Reporting

We will publish, for every run:

1. The exact `summary.json`
2. All per-instance `result.json` + `agent.patch` files
3. A failure-case write-up grouped by category (test parser miss, applies-but-fails, etc.)
4. The git SHA of agent-hub used + the model id + temperature + dataset version

Publication URL pattern: `docs/benchmarks/<YYYYMMDD>-<dataset>-<model>/`.
