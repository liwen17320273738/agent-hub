# ADR-0003: Append-Only Versioning for Artifacts

**Status**: Accepted  
**Date**: 2026-04-22  
**Source**: issuse21 §16 Decision D3

## Context

When an artifact is regenerated (e.g., re-running a pipeline stage), we need to decide whether to overwrite or keep history.

## Decision

Append-only versioning:
- Each write creates a new `TaskArtifact` row with `version = previous + 1`
- Previous row: `is_latest = False`
- New row: `is_latest = True, status = "active"`
- Unique constraint: `(task_id, artifact_type, version)`

## Consequences

- Full version history is always available
- UI can show a version dropdown to compare old vs new
- Storage grows linearly with revisions (acceptable for text artifacts)
