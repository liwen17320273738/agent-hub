# AGENTS.md

This file provides guidance to AI coding assistants when working with code in this repository.

## Project Overview

Agent Hub is an **AI Delivery Platform** — enterprise clients send a one-sentence request, an AI team of 14 roles executes it, and the client sees deliverables go live.

**Core Flow (Hero Path)**:
```
一句话需求 → 收件箱(90s方案) → 团队执行 → 验收闸门 → 部署上线 → 分享链接
```

**Architecture**:
- **Backend** (port 8000): FastAPI — auth, workspace RBAC, LLM proxy, pipeline, agents, share, credentials vault, SSE events
- **Frontend** (port 5200): Vue 3 + Vite + vue-i18n — 5-entry sidebar (控制台/收件箱/团队/工作流/资产)
- **PostgreSQL** (port 5432): Primary database (users, agents, conversations, pipeline tasks, skills, memory)
- **Redis** (port 6379): Cache + SSE pub/sub + working memory + rate limiting
- **Nginx** (port 80): Reverse proxy (Docker production only)

**Project Structure**:
```
agent-hub/
├── packages/
│   └── agent-hub-pipeline/       # Editable pip pkg: stdlib-only maturation helpers — NOT the full async pipeline_engine (see packages/agent-hub-pipeline/README.md)
├── Makefile                      # Root commands (check, install, dev, stop, test)
├── config.example.yaml           # Application config template
├── config.yaml                   # Local config (gitignored)
├── backend/                      # FastAPI backend
│   ├── Makefile                  # Backend-only commands
│   ├── requirements.txt          # Python dependencies
│   ├── Dockerfile                # Backend Docker image
│   ├── alembic/                  # Database migrations
│   ├── app/
│   │   ├── main.py               # FastAPI entry point
│   │   ├── config.py             # Configuration (env vars)
│   │   ├── database.py           # Async SQLAlchemy setup
│   │   ├── security.py           # JWT auth, password hashing
│   │   ├── redis_client.py       # Redis client singleton
│   │   ├── api/                  # FastAPI routers
│   │   │   ├── auth.py           # Login, register, JWT
│   │   │   ├── pipeline.py       # Tasks, stages, DAG, budget
│   │   │   ├── workspaces.py     # Workspace CRUD + RBAC
│   │   │   ├── credentials.py   # Encrypted credentials vault
│   │   │   ├── share.py          # Public share token endpoints
│   │   │   ├── deliverables.py  # ZIP download
│   │   │   ├── workflows.py     # Workflow CRUD + run
│   │   │   ├── gateway.py        # Feishu/QQ/OpenClaw webhooks
│   │   │   ├── events.py         # SSE streaming
│   │   │   └── observability.py  # Traces, audit, approvals
│   │   ├── services/             # Business logic
│   │   │   ├── llm_router.py     # Multi-provider LLM routing
│   │   │   ├── pipeline_engine.py # 8-layer maturation pipeline + Phase 5 resource check + visual generation (Layer 9.5)
│   │   │   ├── ui_visualizer.py  # UI mockup + architecture diagrams + resource check + design tokens + arch consistency (Phase 5)
│   │   │   ├── dag_orchestrator.py # DAG-based orchestration
│   │   │   ├── lead_agent.py     # Task decomposition & parallel exec
│   │   │   ├── agent_runtime.py  # ReAct loop with tools/memory
│   │   │   ├── memory.py         # 3-layer memory (long-term, working, patterns)
│   │   │   ├── sse.py            # Redis Pub/Sub SSE
│   │   │   ├── executor_bridge.py # Claude CLI subprocess
│   │   │   ├── codegen/            # Code generation (Phase 4)
│   │   │   │   ├── codegen_agent.py # CodeGenAgent: scaffold → generate → build → manifest
│   │   │   │   └── templates.py    # Project templates (vue-app, react, fastapi…)
│   │   │   ├── skill_marketplace.py # Skill registry & execution
│   │   │   ├── self_verify.py    # Output verification
│   │   │   ├── guardrails.py     # Safety guardrails
│   │   │   ├── observability.py  # Tracing & audit
│   │   │   ├── collaboration.py  # Pipeline stages definition
│   │   │   ├── planner_worker.py # Model resolution
│   │   │   ├── model_registry.py # Model catalog
│   │   │   ├── token_tracker.py  # Usage tracking
│   │   │   ├── artifact_writer.py # Stage→TaskArtifact v2 bridge — also `write_code_artifacts()` (Phase 4) + `write_qa_artifacts()` (Phase 6) + `write_deploy_artifacts()` (Phase 7)
│   │   │   ├── qa_executor.py     # Phase 6: resource check, subprocess commands, browser smoke
│   │   │   ├── manifest_sync.py  # Rebuild manifest.json from DB — includes `contract` + `source_manifest` + `build_log`
│   │   │   ├── workspace_archiver.py # Archive old task worktrees
│   │   │   ├── deploy/               # Deployment services (Phase 7)
│   │   │   │   ├── __init__.py       # Exports: LocalPreview, check_deploy_resources, deploy_to_vercel
│   │   │   │   ├── local_preview.py  # Local pnpm preview → health check → screenshot → cleanup
│   │   │   │   └── vercel.py         # Vercel deployment via REST API
│   │   ├── models/               # SQLAlchemy ORM
│   │   │   ├── user.py           # Org + User
│   │   │   ├── workspace.py      # Workspace + WorkspaceMember
│   │   │   ├── credential.py    # Fernet-encrypted vault
│   │   │   ├── pipeline.py       # PipelineTask + Stage + Artifact
│   │   │   ├── task_artifact.py  # TaskArtifact v2 + ArtifactTypeRegistry (19 types, Phase 7 adds preview_url)
│   │   │   ├── workflow.py       # Saved workflow DAGs
│   │   │   ├── agent.py          # AgentDefinition + skills/rules
│   │   │   └── observability.py  # Traces, spans, audit logs
│   │   ├── schemas/              # Pydantic request/response
│   │   └── middleware/           # Rate limiting
│   └── tests/                    # Pytest suite
│       ├── test_hero_delivery_path.py    # Phase 1 E2E
│       ├── test_phase4_golden_template.py # Phase 4 scorecard (10 reqs, ≥8 pass)
│       ├── test_phase5_visual_evidence.py # Phase 5 visual evidence (17 tests: resource check, design tokens, screen plan, arch consistency, contract upgrade)
│       └── ...
├── src/                          # Vue 3 + TypeScript frontend
│   ├── App.vue                   # 5-entry sidebar + WorkspaceSwitcher + i18n
│   ├── main.ts                   # App bootstrap (Pinia + Router + i18n)
│   ├── i18n/                     # vue-i18n (zh + en)
│   ├── router/                   # Vue Router (5 main + share + legacy)
│   ├── views/
│   │   ├── Dashboard.vue         # Hero CTA: 一句话 → 先给方案/直接执行
│   │   ├── Inbox.vue             # Task aggregation (all/active/done/failed)
│   │   ├── Team.vue              # Agent grid
│   │   ├── Workflow.vue          # Visual workflow builder + run
│   │   ├── Assets.vue            # Models, skills, integrations
│   │   ├── SharePage.vue         # Public share (no auth) + acceptance
│   │   └── PipelineTaskDetail.vue # 4-tab: artifacts(8-tab)/overview/deliverables/swimlane
│   ├── components/
│   │   ├── workspace/WorkspaceSwitcher.vue
│   │   ├── task/FailureCard.vue  # RCA 4-field business card
│   │   ├── task/DeliverableCards.vue # 8 doc cards (reused in SharePage)
│   │   ├── design/UiMockupCard.vue  # UI mockup preview (PNG + HTML iframe + fallback)
│   │   ├── task/TaskArchDiagram.vue # Architecture diagram (Mermaid HTML iframe + fallback)
│   │   ├── task/ArtifactCompletionBar.vue
│   │   ├── task/TaskArtifactTabs.vue  # 8-Tab delivery view (the core issuse21 UI)
│   │   ├── task/TaskDocTab.vue        # Markdown + version switcher + superseded
│   │   ├── task/TaskCodeTab.vue       # Code artifact (repo/branch/commits)
│   │   ├── task/TaskQATab.vue         # Phase 6: QA command table, screenshot, console errors
│   │   ├── task/DeployPreviewCard.vue # Phase 7: deploy URL, health badge, screenshot, provider
│   │   └── inbox/TaskTable.vue   # Task list with cost column
│   ├── services/                 # API clients
│   └── stores/                   # Pinia stores
├── skills/                       # Agent skills (deer-flow style)
│   ├── public/                   # Built-in skills (committed)
│   └── custom/                   # User skills (gitignored)
├── docker/                       # Docker Compose + Nginx
│   ├── docker-compose.yml
│   └── nginx/nginx.conf
├── scripts/                      # Dev tooling
│   ├── check.py                  # Dependency checker
│   ├── configure.py              # Config generator
│   ├── serve.sh                  # Dev/prod launcher
│   └── start-daemon.sh           # Background launcher
└── docs/                         # Documentation
```

## Commands

**Root directory** (full application):
```bash
make check      # Check system requirements
make config     # Generate local config files
make install    # Install all dependencies
make dev        # Start all services (backend + frontend)
make stop       # Stop all services
make test       # Run all tests
make test-relay # Backend relay gateway integration tests only
make lint       # Lint all code
```

**Backend directory** (backend only):
```bash
make install    # pip install -r requirements.txt
make dev        # uvicorn with --reload
make test       # pytest tests/ -v
make test-relay # pytest tests/integration/test_relay_gateway.py (sets AGENTHUB_TEST_MINIMAL_LIFESPAN=1)
make lint       # ruff check
make format     # ruff format
```

## Architecture Details

### LLM Router (`app/services/llm_router.py`)

Multi-provider routing supporting:
- **OpenAI-compatible**: OpenAI, DeepSeek, Dashscope (Qwen), Zhipu (GLM), any custom endpoint
- **Anthropic**: Codex models via native API
- **Gemini**: Google models via REST API

Provider is inferred from model name, URL, or explicit header. API keys are passed via headers (never in URLs).

### Pipeline Engine (`app/services/pipeline_engine.py`)

8-layer maturation stack for each pipeline stage (Phase 5 adds Layer 2.5 + Layer 9.5):
1. **Planner** — model resolution
2. **Memory** — context injection from history
3. **Phase 5 Resource Check** — check image/diagram resources for design/arch stages
4. **Tools** — skill schema validation
5. **LLM** — actual model call
6. **Self-verify** — output quality checks
7. **Guardrails** — safety validation
8. **Observability** — trace recording
9. **Memory Store** — persist output for future context
10. **Phase 5 Visual Generation** — design: mockup + tokens + screen plan; arch: diagram + api/data/file plan + consistency check

### DAG Orchestrator (`app/services/dag_orchestrator.py`)

Replaces linear pipeline with dependency-based execution:
- Parallel execution of independent stages
- Dependency resolution via topological ordering
- Template-based pipeline creation (web_app, api_service, data_pipeline)

### Memory System (`app/services/memory.py`)

Three-layer architecture:
- **Long-term**: PostgreSQL — task outputs, facts, patterns
- **Working**: Redis — ephemeral per-session context (TTL-based)
- **Learned Patterns**: PostgreSQL — recurring patterns extracted from history

### SSE Events (`app/services/sse.py`)

Redis Pub/Sub for real-time pipeline updates:
- Channel: `agenthub:pipeline:events`
- Events: stage updates, task completion, errors
- Multi-worker safe via Redis (not in-memory)

### Gateway (`app/api/gateway.py`)

Unified message intake from external platforms:
- **Feishu**: Webhook with signature verification
- **QQ**: Webhook with token validation
- **OpenClaw**: API key authentication + optional Plan/Act approval flow
- **Plan/Act**: Clarifier + planner can pause tasks before execution until a user or trusted API approves / revises / cancels
- All create `PipelineTask` records and emit SSE events

### Skills (`skills/`)

Markdown-first skill definitions (same format as deer-flow):
- `SKILL.md` with YAML frontmatter (name, description, enabled, license)
- `skills/public/` — built-in skills (committed to git)
- `skills/custom/` — user-created skills (gitignored)
- Skills are loaded, validated, and injected into agent system prompts
- **Design stage**: built-in `ui-visual-assets` skill + tool `generate_image_asset` (OpenAI Images, requires `OPENAI_API_KEY`) writes PNGs under `screenshots/generated/`; mount Figma/Design MCP on **Agent-designer** for vector handoff.

## Development Guidelines

### Test-Driven Development
- Write tests in `backend/tests/` following `test_<feature>.py` convention
- Run: `make test` (from root) or `cd backend && python3 -m pytest tests/ -v`
- Tests must pass before a feature is considered complete

### Documentation Update Policy
When making code changes, update:
- `AGENTS.md` for architecture/development changes
- `docs/` for feature documentation
- `README.md` for user-facing changes

### Code Style
- **Backend**: Python 3.9+, type hints, async/await, ruff for linting
- **Frontend**: TypeScript, Vue 3 Composition API, Pinia stores
- No comments that just narrate what code does

### Import Conventions
```python
# API layer
from app.api.pipeline import router

# Service layer
from app.services.llm_router import chat_completion
from app.services.memory import get_context_from_history

# ORM models
from app.models.pipeline import PipelineTask, PipelineStage

# Config
from app.config import settings
```

## Key Features

### Workspace RBAC
- Org → Workspace hierarchy with resource isolation
- Three roles: admin / manager / member
- Sidebar workspace switcher, `workspace_id` FK on tasks and workflows

### Credentials Vault
- Fernet symmetric encryption derived from JWT_SECRET
- API never exposes plaintext, only `has_value: true`
- Supports API keys, OAuth tokens for GitHub/Jira/Slack/Notion

### Cost Governor
- Per-task budget with 60% soft cap (auto-downgrade to DeepSeek) and 100% hard block
- Budget visible in Inbox task table
- 5 fallback model candidates by cost tier

### Share & Acceptance
- HMAC-SHA256 signed tokens with configurable TTL (7/30/365 days)
- Public SharePage: view deliverables + accept/reject without login
- ZIP download of complete delivery package (8 docs + screenshots + manifest)

### Failure RCA Card
- 4-field business-language failure card (stuck where / why / who / next step)
- Auto-inferred owner (Admin / User / Agent) based on error pattern
- Action buttons: retry / retry-with-downgrade / rollback / escalate

### i18n
- vue-i18n with zh/en locale files
- All 5 sidebar entries + Dashboard + Inbox covered
- Language toggle in sidebar footer, persisted to localStorage

### Artifact System (issuse21)
- **DB as source of truth**: `TaskArtifact` with version tracking + `is_latest` flag
- **19 registered types** (Phase 7 adds preview_url): brief, prd, ui_spec, ui_mockup, ui_mockup_html, architecture, architecture_diagram, implementation, test_report, acceptance, ops_runbook, code_link, screenshot, attachment, deploy_manifest, source_manifest, build_log, test_log, preview_url
- **Version history**: Each write auto-increments version, old row → `is_latest=False`
- **Supersede on reject**: `POST /tasks/{id}/artifacts/{type}/supersede` marks as `superseded`
- **Manifest cache**: `manifest.json` rebuilt async from DB after each write (fallback to DB if stale)
- **8-Tab delivery UI**: `TaskArtifactTabs.vue` as default task detail view — user finds PRD/UI/code/tests in 10s
- **Archiver**: Tasks accepted >30d or cancelled >7d → worktree compressed to `_archive/`
- **Pipeline integration**: `artifact_writer.py` auto-writes v2 artifact when stage completes; Phase 5: design also writes `design_tokens` + `screen_plan` to metadata, arch also writes `api_contract` + `data_model` + `file_plan` to metadata.
- **Artifact contract (Phase 3 + Phase 5)**: `services/artifact_contract.py` — definitions + advisory rules; stage presence enforced in `execute_stage`. Phase 5 upgrade: `design` requires `ui_mockup` (was optional), `architecture` requires `architecture_diagram` (was optional).
- **Code artifacts (Phase 4)**: `source_manifest.json` + `build.log` auto-written by `CodeGenAgent` → persisted via `artifact_writer.write_code_artifacts()` → displayed in `TaskCodeTab.vue` build summary panel

### Pipeline & Workflow
- 14-role agent team with DAG orchestration
- Visual workflow builder → compiler → runner
- 8 standard delivery documents per task
- Quality gates, self-verify, guardrails at every stage

### Golden Code Template (Phase 4)
- **Template on disk**: `packages/agent-hub-pipeline/templates/vue-app/` (pnpm, vitest, TypeScript, pinia, vue-router)
- **CodeGenAgent** (`services/codegen/codegen_agent.py`): scaffold → LLM generation → build → source_manifest + build.log
- **Input guard**: `generate_from_pipeline` requires `planning` + `architecture` outputs
- **Allowlist**: file writes restricted to `src/`, `public/`, `package.json`, config files
- **Auto-fix loop**: up to 2 retries on build failure, reads `build.log` for error diagnosis
- **Artifact integration**: `source_manifest.json` + `build.log` written to project dir → `artifact_writer.write_code_artifacts()` → `TaskArtifact` → `manifest.json`
- **Frontend display**: `TaskCodeTab.vue` shows build summary + collapsible build log
- **Scorecard test**: `test_phase4_golden_template.py` — 10 fixed requirements, real pnpm build, ≥ 8/10 pass

### Visual Evidence Enforcement (Phase 5)

Design/Architecture stages must produce viewable graphics; missing visuals block delivery:
- **Resource check** (`UiVisualizer.check_design_resources` / `check_diagram_resources`): probes OpenAI Images key, Gemini/Nano Banana Pro, HTML prototype, Mermaid CLI availability in Layer 2.5 of `pipeline_engine.py`. All unavailable → stage `blocked`.
- **Design stage** (Layer 9.5): calls `generate_mockup()` (PNG via image gen, HTML fallback) + `generate_design_tokens()` → metadata + `generate_screen_plan()` → metadata. Fails if no PNG/HTML produced.
- **Architecture stage** (Layer 9.5): calls `generate_all_architecture_artifacts()` → `architecture.html` (Mermaid.js rendered), `api_contract.json`, `data_model.json`, `file_plan.json`, `check_architecture_consistency()`. Fails on inconsistency.
- **Artifact contract**: `design` → `ui_mockup` required; `architecture` → `architecture_diagram` required.
- **Frontend**: `UiMockupCard.vue` + `TaskArchDiagram.vue` in `TaskArtifactTabs.vue` + `SharePage.vue`. Both support `compact` prop.
- **Test file**: `test_phase5_visual_evidence.py` — 17 tests (resource check, tokens, screen plan, consistency, contract).

### QA Real Execution (Phase 6)

Testing stage runs real commands + browser smoke; no fake reports:
- **`QaExecutor`** (`services/qa_executor.py`): resource check (source_manifest, node, pnpm, playwright) → `run_all_commands` (pnpm install → build → test) → `run_browser_smoke` (preview server → Playwright screenshot → console errors → page text).
- **Pipeline integration**: Phase 6 block executes post-LLM in testing stage. Blocked if source_manifest missing or essential tools unavailable. Failed if install/build/test fails.
- **Artifact contract**: `testing` requires `test_report`, `build_log`, `screenshot` (was only `test_report`). `test_log` + `console_errors` as optional types.
- **`write_qa_artifacts`** (`services/artifact_writer.py`): formats structured markdown report, reads build.log/test.log, base64-encodes PNG screenshot, writes typed TaskArtifact rows.
- **Frontend**: `TaskQATab.vue` replaces `TaskDocTab` for `test_report` type — command table, screenshot (click-to-enlarge), console error list (red), collapsible logs. Also in `SharePage.vue`.
- **I18n**: `qa.*` keys in all locales (zh/en/ja/ko).
- **Test file**: `test_phase6_qa_execution.py` — 22 tests (resource check, manifest parsing, commands, browser smoke, contract upgrade, write_qa_artifacts).

### Deploy Closure (Phase 7)

Every delivery gets a preview URL with health check and screenshot:

- **`deploy/local_preview.py`**: `LocalPreview` — starts `pnpm preview`, health-checks (15s timeout), Playwright screenshot, port fallback (4173→4174→4175), SIGTERM cleanup. `check_deploy_resources()` checks node/pnpm + `VERCEL_TOKEN`.
- **Pipeline integration**: Phase 7 block executes post-LLM in deployment stage. Vercel preferred if `VERCEL_TOKEN` set; falls back to local preview. Writes deploy artifacts on success. No deploy channel → stage blocked.
- **Artifact contract**: `deployment` now requires `preview_url`, `screenshot`, `deploy_manifest`, `ops_runbook` (was only `ops_runbook`). `preview_url` added as new type.
- **`write_deploy_artifacts`** (`services/artifact_writer.py`): writes `preview_url` JSON, `deploy_manifest` JSON, screenshot base64 PNG, ops_runbook markdown.
- **Frontend**: `DeployPreviewCard.vue` — URL click-to-open, health tag (green/red/yellow), provider label, deployed screenshot. In `TaskArtifactTabs` (preview_url tab) and `SharePage.vue`.
- **I18n**: `deploy.*` keys in all locales (zh/en/ja/ko).


