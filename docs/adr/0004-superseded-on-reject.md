# ADR-0004: Superseded Status on Reject

**Status**: Accepted  
**Date**: 2026-04-22  
**Source**: issuse21 §16 Decision D4

## Context

When a task is rejected / sent back for rework, affected artifacts need a clear status.

## Decision

- On reject: latest artifact → `status = "superseded"`, `is_latest` stays True until a new version is written
- On rework completion: new version is written → old superseded row becomes `is_latest = False`
- API: `POST /tasks/{id}/artifacts/{type}/supersede`

## Consequences

- Reject history is visible in the version timeline
- Superseded artifacts are visually marked in the UI (red badge)
- No data is ever deleted — full audit trail preserved
