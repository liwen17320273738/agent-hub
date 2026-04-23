# ADR-0002: Database as Source of Truth for Artifacts

**Status**: Accepted  
**Date**: 2026-04-22  
**Source**: issuse21 §16 Decision D2

## Context

Artifacts can be stored as files on disk or as DB records. We need one authoritative source to avoid sync issues.

## Decision

Database (PostgreSQL `task_artifacts` table) is the source of truth. `manifest.json` in each task directory is a **cache** that is rebuilt asynchronously after each write.

## Write Flow

1. Write `TaskArtifact` row to DB (version++, `is_latest=True`, old row `is_latest=False`)
2. Write physical file to `tasks/{id}/docs/`
3. Async trigger `manifest_sync.rebuild_manifest(task_id)` — best-effort

## Consequences

- API always queries DB, never reads manifest
- If manifest is stale/missing, system still works (fallback to DB)
- manifest.json is useful for offline inspection and ZIP export
