# ADR-0008: Gradual Migration with V2 Switch

**Status**: Accepted (V2 enabled)  
**Date**: 2026-04-22  
**Source**: issuse21 §16 Decision D8

## Context

Migrating from a global `docs/delivery/*.md` system to per-task artifact storage needs to be non-breaking.

## Decision

Feature flag `ARTIFACT_STORE_V2` in config:
- **Phase 1-2** (`v2=false`): Dual-write — stage outputs go to both old and new paths
- **Phase 3-4** (`v2=true`): New tasks only write to v2 paths; old tasks fallback to legacy API

Current status: **v2=True** — migration complete.

## Migration Timeline

1. Week 1-2: Dual-write enabled, verified data parity
2. Week 3: v2 switch flipped to True
3. Week 4: Archiver service compresses old worktrees
4. Future: Remove legacy `delivery_docs.py` write path (keep as template service)

## Consequences

- Zero downtime migration
- Old tasks remain accessible via fallback
- New tasks get full versioning and DB indexing from day one
