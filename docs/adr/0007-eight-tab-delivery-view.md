# ADR-0007: Eight-Tab Delivery View

**Status**: Accepted  
**Date**: 2026-04-22  
**Source**: issuse21 §16 Decision D7

## Context

Users couldn't find task deliverables — they were scattered across stage outputs, file system, and API responses. The "overview" page was a long scroll of system internals.

## Decision

Task detail page defaults to an 8-tab delivery view (`TaskArtifactTabs.vue`):

1. **需求** (Brief) — `00-brief.md`
2. **PRD** — `01-prd.md`
3. **UI 规格** — `02-ui-spec.md` + screenshots gallery
4. **技术方案** — `03-architecture.md`
5. **代码** — repo path + branch + commits + changed files + test status
6. **测试** — `05-test-report.md` + verify checks
7. **验收** — `06-acceptance.md` + sign-off history
8. **运维** — `07-ops-runbook.md` + deploy links

A completion bar at the top shows 8 icons (gray/green/red) for at-a-glance status.

## Consequences

- Users find any deliverable within 10 seconds
- System internals (stages, logs, quality gates) moved to "概览" tab
- Share page reuses the same tab component in readonly mode
