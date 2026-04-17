"""Eval Suite — datasets, runs, results.

Built around three first-class concepts:

  EvalDataset     — a named collection of cases (e.g. "developer-regression-v1")
  EvalCase        — one input/expectation triple inside a dataset
  EvalRun         — one full pass of a dataset (snapshot of agent + scoring)
  EvalResult      — per-case outcome under one run

This is intentionally agent-centric: a case targets a `role` (or seed_id)
and runs through `AgentRuntime` exactly as the production /agents/run does.

Scoring is pluggable via `case.scorer` — built-ins include:
    - "contains"        : expected substrings must appear in agent output
    - "regex"           : regex pattern must match
    - "json_path"       : output is parsed as JSON, dotted path must equal value
    - "exact"           : exact string match (after strip)
    - "llm_judge"       : a separate LLM grades the answer (rubric in `expected.rubric`)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, String, Text, Integer, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default


class EvalDataset(Base):
    """A named, versioned collection of evaluation cases."""
    __tablename__ = "eval_datasets"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False, unique=True, index=True)
    description = Column(Text, default="")
    tags = Column(JsonDict(), default=list)
    target_role = Column(String(100), default="")  # default role if cases don't override
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=utcnow_default())
    updated_at = Column(DateTime, server_default=utcnow_default(), onupdate=datetime.utcnow)

    cases = relationship("EvalCase", back_populates="dataset", cascade="all, delete-orphan")


class EvalCase(Base):
    """One input/expectation triple inside a dataset."""
    __tablename__ = "eval_cases"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(GUID(), ForeignKey("eval_datasets.id", ondelete="CASCADE"), index=True, nullable=False)
    name = Column(String(200), default="")
    task = Column(Text, nullable=False)
    context = Column(JsonDict(), default=dict)
    role = Column(String(100), default="")  # overrides dataset.target_role
    scorer = Column(String(50), default="contains")  # contains | regex | json_path | exact | llm_judge
    expected = Column(JsonDict(), default=dict)
    weight = Column(Float, default=1.0)
    timeout_seconds = Column(Integer, default=120)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=utcnow_default())

    dataset = relationship("EvalDataset", back_populates="cases")


class EvalRun(Base):
    """One end-to-end pass over a dataset (snapshot of conditions + aggregate score)."""
    __tablename__ = "eval_runs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(GUID(), ForeignKey("eval_datasets.id", ondelete="SET NULL"), nullable=True, index=True)
    label = Column(String(200), default="")  # human-friendly tag like "main vs deepseek-v3"
    agent_role_override = Column(String(100), default="")  # if set, all cases use this role
    model_override = Column(String(100), default="")
    status = Column(String(20), default="pending")  # pending | running | completed | failed | aborted
    total_cases = Column(Integer, default=0)
    passed_cases = Column(Integer, default=0)
    failed_cases = Column(Integer, default=0)
    skipped_cases = Column(Integer, default=0)
    avg_score = Column(Float, default=0.0)
    avg_latency_ms = Column(Float, default=0.0)
    total_tokens = Column(Integer, default=0)
    error = Column(Text, default="")
    started_at = Column(DateTime, server_default=utcnow_default())
    completed_at = Column(DateTime, nullable=True)
    metadata_extra = Column(JsonDict(), default=dict)

    results = relationship("EvalResult", back_populates="run", cascade="all, delete-orphan")


class EvalResult(Base):
    """Per-case outcome under one run."""
    __tablename__ = "eval_results"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(GUID(), ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    case_id = Column(GUID(), ForeignKey("eval_cases.id", ondelete="SET NULL"), nullable=True, index=True)
    case_name = Column(String(200), default="")  # snapshot for readability
    role = Column(String(100), default="")
    seed_id = Column(String(100), default="")
    score = Column(Float, default=0.0)
    passed = Column(Boolean, default=False)
    output = Column(Text, default="")
    observations = Column(JsonDict(), default=list)
    scorer = Column(String(50), default="")
    scorer_detail = Column(JsonDict(), default=dict)
    error = Column(Text, default="")
    steps = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=utcnow_default())

    run = relationship("EvalRun", back_populates="results")
