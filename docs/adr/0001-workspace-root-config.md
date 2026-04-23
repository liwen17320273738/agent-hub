# ADR-0001: Workspace Root Configuration

**Status**: Accepted  
**Date**: 2026-04-22  
**Source**: issuse21 §16 Decision D1

## Context

Tasks generate multiple artifacts (docs, screenshots, code, logs). We need a predictable physical directory structure for task-scoped storage.

## Decision

Use environment-based configuration with sensible defaults:
- `WORKSPACE_ROOT` defaults to `{PROJECT_ROOT}/data/workspace/`
- Sub-directories: `tasks/`, `worktrees/`, `shared/`
- Each task gets `tasks/TASK-{id}-{slug}/` with `docs/`, `screenshots/`, `logs/`, `exports/`, `artifacts/`

## Consequences

- Operators can mount external volumes by setting `WORKSPACE_ROOT`
- Dev environments use local filesystem with zero config
- Docker deployments need volume mapping for persistence
