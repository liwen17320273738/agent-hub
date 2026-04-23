# ADR-0005: Artifact Type Registry

**Status**: Accepted  
**Date**: 2026-04-22  
**Source**: issuse21 §16 Decision D5

## Context

We need a fixed set of artifact types (brief, PRD, UI spec, etc.) but also extensibility for custom types.

## Decision

String-based `artifact_type` with a registry table (`artifact_type_registry`):
- 12 built-in types seeded at startup
- `type_key` is the PK; `category`, `display_name`, `icon`, `tab_group`, `sort_order`
- Custom types can be added via DB insert (no code change required)

## 12 Built-in Types

brief, prd, ui_spec, architecture, implementation, test_report, acceptance, ops_runbook, code_link, screenshot, attachment, deploy_manifest

## Consequences

- Adding a new artifact type = one DB row, no migration
- Frontend reads registry to render tabs dynamically
- Sort order determines tab display sequence
