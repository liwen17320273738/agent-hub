"""SWE-Bench dataset loader.

Two source types supported:

1. ``hf:<repo>[:<split>]`` — uses ``datasets`` (optional dep). Examples::

       hf:princeton-nlp/SWE-bench_Lite
       hf:princeton-nlp/SWE-bench_Verified:test

2. Local JSONL file (one instance per line). The schema mirrors the
   official SWE-Bench fields we actually need; everything else is
   forwarded as-is.

   Required keys per line:
     - instance_id (str)        e.g. "django__django-15814"
     - repo (str)               e.g. "django/django"
     - base_commit (str)        e.g. "0a7d6b9..."
     - problem_statement (str)  the issue body
     - test_patch (str)         applied before scoring (sets up failing tests)
     - patch (str)              the *gold* patch (used only for diff comparison)

   Optional:
     - hints_text, version, FAIL_TO_PASS, PASS_TO_PASS

The loader returns lightweight :class:`SweInstance` dataclasses so the rest
of the harness never touches dict-shape detail.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional


_REQUIRED_KEYS = ("instance_id", "repo", "base_commit", "problem_statement")


@dataclass
class SweInstance:
    """One SWE-Bench task. Mirrors the upstream schema for the fields we use."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    test_patch: str = ""
    patch: str = ""
    hints_text: str = ""
    version: str = ""
    fail_to_pass: List[str] = field(default_factory=list)
    pass_to_pass: List[str] = field(default_factory=list)
    extras: Dict[str, Any] = field(default_factory=dict)

    @property
    def repo_slug(self) -> str:
        return self.instance_id.split("__", 1)[0] if "__" in self.instance_id else self.repo.replace("/", "_")


def load_instances(
    source: str,
    *,
    limit: Optional[int] = None,
    only_ids: Optional[Iterable[str]] = None,
) -> List[SweInstance]:
    """Load + normalise SWE-Bench instances from a local JSONL or HF dataset."""
    if source.startswith("hf:"):
        records = _load_hf(source[3:])
    else:
        records = _load_jsonl(Path(source))

    only_set = set(only_ids) if only_ids else None
    out: List[SweInstance] = []
    for raw in records:
        if only_set and raw.get("instance_id") not in only_set:
            continue
        try:
            out.append(_to_instance(raw))
        except ValueError as exc:
            raise ValueError(f"invalid SWE-Bench record: {exc}") from exc
        if limit is not None and len(out) >= limit:
            break
    return out


def _load_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"SWE-Bench dataset not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n}: invalid JSON ({exc})") from exc


def _load_hf(spec: str) -> Iterator[Dict[str, Any]]:
    try:
        from datasets import load_dataset  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "HuggingFace `datasets` is not installed. "
            "Install with `pip install -r backend/requirements-bench.txt` "
            "or use a local JSONL source instead."
        ) from exc
    if ":" in spec:
        repo, split = spec.split(":", 1)
    else:
        repo, split = spec, "test"
    ds = load_dataset(repo, split=split)
    for row in ds:
        yield dict(row)


def _to_instance(raw: Dict[str, Any]) -> SweInstance:
    missing = [k for k in _REQUIRED_KEYS if not raw.get(k)]
    if missing:
        raise ValueError(f"missing required keys {missing} on instance {raw.get('instance_id', '<unknown>')}")

    return SweInstance(
        instance_id=str(raw["instance_id"]),
        repo=str(raw["repo"]),
        base_commit=str(raw["base_commit"]),
        problem_statement=str(raw["problem_statement"]),
        test_patch=str(raw.get("test_patch") or ""),
        patch=str(raw.get("patch") or ""),
        hints_text=str(raw.get("hints_text") or ""),
        version=str(raw.get("version") or ""),
        fail_to_pass=_as_list(raw.get("FAIL_TO_PASS") or raw.get("fail_to_pass")),
        pass_to_pass=_as_list(raw.get("PASS_TO_PASS") or raw.get("pass_to_pass")),
        extras={
            k: v
            for k, v in raw.items()
            if k
            not in {
                "instance_id",
                "repo",
                "base_commit",
                "problem_statement",
                "test_patch",
                "patch",
                "hints_text",
                "version",
                "FAIL_TO_PASS",
                "PASS_TO_PASS",
                "fail_to_pass",
                "pass_to_pass",
            }
        },
    )


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed]
            except json.JSONDecodeError:
                pass
        return [s]
    return [str(value)]
