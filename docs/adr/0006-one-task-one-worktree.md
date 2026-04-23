# ADR-0006: One Task One Worktree

**Status**: Accepted  
**Date**: 2026-04-22  
**Source**: issuse21 §16 Decision D6

## Context

Tasks that involve code generation need isolated working directories to avoid cross-contamination.

## Decision

Each task gets exactly one worktree at `worktrees/TASK-{id}-{slug}/`. Multi-repository support is explicitly out of scope for this phase.

## Consequences

- Clean isolation between tasks
- Worktrees can be archived after task completion (ADR follows)
- Multi-repo tasks will need a future ADR when the need arises
