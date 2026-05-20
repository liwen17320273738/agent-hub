# CLAUDE.md

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
├── Makefile                      # Root commands (check, install, dev, stop, test)
├── config.example.yaml           # Application config template
├── config.yaml                   # Local config (gitignored)
├── packages/
│   └── agent-hub-pipeline/       # Stdlib-only maturation helpers (editable install); contains templates/vue-app/ on disk (full async engine stays in backend)
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
│   │   ├── core/                 # Cross-cutting infrastructure
│   │   │   ├── context.py        # Distributed trace context (contextvars)
│   │   │   └── trace_middleware.py # X-Agent-Trace-ID propagation
│   │   ├── api/                  # FastAPI routers (thin — delegate to services)
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
│   │   ├── services/             # Business logic (thick — all domain logic here)
│   │   │   ├── llm_router.py     # Multi-provider LLM routing
│   │   │   ├── pipeline_engine.py # 8-layer maturation pipeline + Phase 5 resource check + visual generation + Phase 6 QA real execution
│   │   │   ├── qa_executor.py    # Phase 6: resource check, subprocess commands, browser smoke via stealth_browser
│   │   │   ├── ui_visualizer.py  # UI mockup (PNG/HTML) + architecture diagrams (Mermaid/HTML) + resource check + design tokens + screen plan + api contract + data model + file plan + consistency check (Phase 5)
│   │   │   ├── dag_orchestrator.py # DAG-based orchestration
│   │   │   ├── lead_agent.py     # Task decomposition & parallel exec
│   │   │   ├── agent_runtime.py  # ReAct loop with tools/memory
│   │   │   ├── agent_bus.py      # Inter-agent communication bus
│   │   │   ├── agent_delegate.py # Agent-to-agent delegation
│   │   │   ├── swarm_coordinator.py # Multi-agent swarm coordination
│   │   │   ├── memory.py         # 3-layer memory (long-term, working, patterns)
│   │   │   ├── sse.py            # Redis Pub/Sub SSE
│   │   │   ├── executor_bridge.py # Claude CLI subprocess
│   │   │   ├── skill_marketplace.py # Skill registry & execution
│   │   │   ├── self_verify.py    # Output verification
│   │   │   ├── guardrails.py     # Safety guardrails
│   │   │   ├── quality_gates.py  # Quality gate enforcement
│   │   │   ├── observability.py  # Tracing, spans, audit
│   │   │   ├── collaboration.py  # Pipeline stages definition
│   │   │   ├── planner_worker.py # Model resolution
│   │   │   ├── planner.py        # High-level planning logic
│   │   │   ├── model_registry.py # Model catalog
│   │   │   ├── token_tracker.py  # Usage tracking
│   │   │   ├── cost_governor.py  # Budget enforcement (60% soft, 100% hard)
│   │   │   ├── task_scheduler.py # Scheduled task execution
│   │   │   ├── task_lifecycle.py # Task state machine
│   │   │   ├── scheduler_task_state.py # Scheduler state tracking
│   │   │   ├── artifact_writer.py # Stage→TaskArtifact v2 bridge; write_qa_artifacts (Phase 6); write_deploy_artifacts (Phase 7)
│   │   │   ├── artifact_contract.py # Artifact contract definitions + rules (Phase 5/6/7 updates)
│   │   │   ├── manifest_sync.py  # Rebuild manifest.json from DB
│   │   │   ├── workspace_archiver.py # Archive old task worktrees
│   │   │   ├── deploy/               # Deployment services (Phase 7)
│   │   │   │   ├── __init__.py       # Exports: LocalPreview, check_deploy_resources, deploy_to_vercel
│   │   │   │   ├── local_preview.py  # Local pnpm preview → health check → screenshot → cleanup
│   │   │   │   └── vercel.py         # Vercel deployment via REST API
│   │   │   ├── workflow_compiler.py # DAG workflow → executable plan
│   │   │   ├── workflow_runner.py   # Execute compiled workflow
│   │   │   ├── learning_engine.py   # Pattern extraction from history
│   │   │   ├── rca_reporter.py      # Root cause analysis reports
│   │   │   ├── e2e_orchestrator.py  # End-to-end test orchestration
│   │   │   ├── codebase_indexer.py  # Code indexing for context
│   │   │   ├── codegen/              # Code generation (Phase 4)
│   │   │   │   ├── codegen_agent.py  # CodeGenAgent: scaffold → generate → build → manifest
│   │   │   │   └── templates.py      # Project templates (vue-app, react, fastapi…)
│   │   │   ├── vector/              # Vector embeddings + pgvector
│   │   │   └── tools/               # Agent tool implementations
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
│   │   ├── test_phase6_qa_execution.py # Phase 6 QA real execution (22 tests: resource check, command exec, browser smoke, contract upgrade, write_qa_artifacts)
│   │   ├── test_phase5_visual_evidence.py # Phase 5 visual evidence (17 tests: resource check, design tokens, screen plan, arch consistency, contract upgrade)
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
│   │   ├── task/TaskArchDiagram.vue # Architecture diagram preview (Mermaid HTML iframe + fallback)
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
make check         # Check system requirements
make config        # Generate local config files
make install       # Install all dependencies (pnpm + pip)
make dev           # Start all services (backend + frontend)
make dev-daemon    # Start all services in background
make stop          # Stop all services
make test          # Run all backend tests (pytest tests/ -v)
make test-unit     # Run backend unit tests only
make test-relay    # Backend relay gateway integration tests only
make lint          # Lint backend (ruff) + frontend (pnpm lint)
make format-backend # Format backend (ruff format — large diffs, use sparingly)
make migrate       # alembic upgrade head (merges backend/.env + root .env)
make reset-admin   # Reset DB admin password from ADMIN_PASSWORD env
make verify-login  # Test /auth/login with current config
```

**Backend directory** (`cd backend`):
```bash
make install       # pip install with agent-hub-pipeline editable
make dev           # uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
make test          # pytest tests/ -v
make test-unit     # pytest tests/unit/ -v
make test-relay    # AGENTHUB_TEST_MINIMAL_LIFESPAN=1 pytest tests/integration/test_relay_gateway.py
make lint          # ruff check .
make format        # ruff check --fix && ruff format .
make migrate       # alembic upgrade head with merged env
```

Run a single test file or test:
```bash
cd backend && python3 -m pytest tests/unit/test_llm_router.py -v
cd backend && python3 -m pytest tests/unit/test_llm_router.py::test_specific -v
```

**Frontend directory** (`cd src` or root):
```bash
pnpm install       # Install dependencies
pnpm dev           # Vite dev server (port 5200)
pnpm build         # Production build
pnpm lint          # ESLint
```

## Architecture Details

### LLM Router (`app/services/llm_router.py`)

Multi-provider routing supporting:
- **OpenAI-compatible**: OpenAI, DeepSeek, Dashscope (Qwen), Zhipu (GLM), any custom endpoint
- **Anthropic**: Claude models via native API
- **Gemini**: Google models via REST API

Provider is inferred from model name, URL, or explicit header. API keys are passed via headers (never in URLs).

### Distributed Trace Context (`app/core/context.py` + `app/core/trace_middleware.py`)

contextvars-based trace propagation across all layers (Gateway → Orchestrator → Agent → Tool → LLM):
- `TraceMiddleware` extracts or generates `X-Agent-Trace-ID` per request, sets `request.state.trace_span`
- `TraceSpan` supports child spans via `new_child()` — use `set_current_span()` when entering sub-contexts
- trace_id is bound to structlog context for all log lines in the request

### Pipeline Engine (`app/services/pipeline_engine.py`)

8-layer maturation stack for each pipeline stage (Phase 5 adds Layer 2.5 resource check + Layer 9.5 visual generation; Phase 6 adds QA real execution post-LLM):
1. **Planner** — model resolution
2. **Memory** — context injection from history
3. **Phase 5 Resource Check** — design/arch stages: probe image gen / diagram rendering availability
4. **Tools** — skill schema validation
5. **LLM** — actual model call
6. **Self-verify** — output quality checks
7. **Guardrails** — safety validation
8. **Observability** — trace recording
9. **Memory Store** — persist output for future context
10. **Phase 5 Visual Generation** — design: mockup PNG/HTML + tokens + screen plan; architecture: diagram HTML + api/data/file plan + consistency check
11. **Phase 6 QA Real Execution** — testing stage: resource check → pnpm install → pnpm build → pnpm test → pnpm preview → Playwright screenshot → write QA artifacts (build_log, test_log, screenshot, test_report)
12. **Phase 7 Deploy Closure** — deployment stage: resource check → Vercel deploy (preferred) or local `pnpm preview` → health check → Playwright screenshot → write deploy artifacts (preview_url, deploy_manifest, screenshot, ops_runbook)

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

## Development Guidelines

### Karpathy Principles (from andrej-karpathy-skills)

行为准则，减少 LLM 编码常见错误。权衡：这些准则偏向谨慎而非速度。对简单任务可灵活判断。

#### 1. 先思考再编码 (Think Before Coding)
- 明确陈述假设。如果不确定，直接提问
- 如果有多种解释，列出来 — 不要静默选择
- 如果有更简单的方案，说出来。必要时反驳需求
- 如果有不清楚的地方，停下来。指出困惑点，然后提问

#### 2. 简洁优先 (Simplicity First)
- 只写解决问题所需的最少代码，不做推测性开发
- 不为单次使用创建抽象
- 不添加未被要求的"灵活性"或"可配置性"
- 不处理不可能发生的错误场景
- 如果写了 200 行但 50 行就够，重写

自问："高级工程师会觉得这过度复杂吗？" 如果是，简化。

#### 3. 精准修改 (Surgical Changes)
- 只修改必须改的，不"改良"相邻代码、注释或格式
- 不重构没有坏的东西
- 匹配现有风格，即使你不同意
- 发现无关的死代码时，提及但不要删除
- 当你的改动造成孤立代码时，清理你引入的未使用导入/变量/函数

检验标准：每个改动行都应直接追溯到用户的需求。

#### 4. 目标驱动执行 (Goal-Driven Execution)
- 将任务转化为可验证目标："添加验证"→"先写无效输入测试，再让测试通过"
- "修复 bug"→"先写能复现的测试，再让测试通过"
- "重构 X"→"确保重构前后测试都通过"
- 多步骤任务先列出简要计划，每步带验证标准

### Test-Driven Development
- Write tests in `backend/tests/` following `test_<feature>.py` convention
- Run: `make test` (from root) or `cd backend && python3 -m pytest tests/ -v`
- Tests must pass before a feature is considered complete

### Documentation Update Policy
When making code changes, update:
- `CLAUDE.md` for architecture/development changes
- `docs/` for feature documentation
- `README.md` for user-facing changes

### Environment Configuration

`.env` files use a merge pattern (implemented in `scripts/serve.sh`):
1. `backend/.env` loaded first (defaults)
2. Root `.env` loaded second (overrides on duplicate keys)
3. This merge is also used by `make migrate`, `make reset-admin`, `make verify-login`

Never commit `.env` files — they are gitignored. Use `.env.example` as template.

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
- **14 registered types** (Phase 4 adds 2): brief, prd, ui_spec, architecture, implementation, test_report, acceptance, ops_runbook, code_link, screenshot, attachment, deploy_manifest, **source_manifest**, **build_log**
- **Version history**: Each write auto-increments version, old row → `is_latest=False`
- **Supersede on reject**: `POST /tasks/{id}/artifacts/{type}/supersede` marks as `superseded`
- **Manifest cache**: `manifest.json` rebuilt async from DB after each write (fallback to DB if stale)
- **8-Tab delivery UI**: `TaskArtifactTabs.vue` as default task detail view — user finds PRD/UI/code/tests in 10s
- **Archiver**: Tasks accepted >30d or cancelled >7d → worktree compressed to `_archive/`
- **Pipeline integration**: `artifact_writer.py` auto-writes v2 artifact when stage completes
- **Artifact contract (Phase 3 + Phase 5 + Phase 6)**: `services/artifact_contract.py` — definitions + advisory rules; stage presence enforced in `execute_stage` when `artifact_contract_enforce`. Phase 5 upgrade: `design` requires `ui_mockup` (was optional), `architecture` requires `architecture_diagram` (was optional). Phase 6 upgrade: `testing` requires `test_report`, `build_log`, `screenshot` (was only `test_report`).
- **Code artifacts (Phase 4)**: `source_manifest.json` and `build.log` auto-written by `CodeGenAgent` → written to `TaskArtifact` via `artifact_writer.write_code_artifacts()` → displayed in `TaskCodeTab.vue` build summary panel

### Task Scheduler & Lifecycle (`app/services/task_scheduler.py` + `task_lifecycle.py`)

- `task_scheduler.py`: Scheduled task execution engine with state persistence via `scheduler_task_state.py`
- `task_lifecycle.py`: Task state machine managing transitions through the pipeline
- Periodic tasks, retry logic, and timeout handling

### Pipeline & Workflow
- 14-role agent team with DAG orchestration
- Visual workflow builder → compiler (`workflow_compiler.py`) → runner (`workflow_runner.py`)
- 8 standard delivery documents per task
- Quality gates, self-verify, guardrails at every stage

### Golden Code Template (Phase 4)

Stable Vue/Vite code generation with self-contained pipeline:
- **Template on disk**: `packages/agent-hub-pipeline/templates/vue-app/` — scaffolded via `scaffold_project()` in `templates.py` (pnpm, vitest, TypeScript, pinia, vue-router)
- **CodeGenAgent** (`services/codegen/codegen_agent.py`): orchestrates scaffold → LLM generation (Claude Code CLI or extraction fallback) → build → source_manifest + build.log
- **Input guard**: `generate_from_pipeline` requires `planning` + `architecture` outputs, returns `missing_required_input` otherwise
- **Allowlist**: file writes restricted to `src/`, `public/`, `package.json`, config files
- **Auto-fix loop**: up to 2 retries on build failure, reads `build.log` for error diagnosis
- **Artifact integration**: `source_manifest.json` + `build.log` written to project dir → `artifact_writer.write_code_artifacts()` persists as `TaskArtifact` → `manifest_sync` includes in `manifest.json`
- **Frontend display**: `TaskCodeTab.vue` shows build summary (commands, created files, pass/fail) + collapsible build log
- **Scorecard test**: `test_phase4_golden_template.py` — 10 fixed requirements, real pnpm build, asserts ≥ 8/10 pass

### Visual Evidence Enforcement (Phase 5)

Design/Architecture stages must produce viewable graphics; missing visuals block delivery:
- **Resource check** (`UiVisualizer.check_design_resources` / `check_diagram_resources`): probes OpenAI Images key, Gemini/Nano Banana Pro, HTML prototype, Mermaid CLI availability before stage execution in Layer 2.5 of `pipeline_engine.py`. Blocked when all channels unavailable.
- **Design stage** (Layer 9.5): after LLM output, calls `generate_mockup()` (PNG via image gen, HTML fallback) + `generate_design_tokens()` (colors, fonts, spacing) + `generate_screen_plan()` (screen list + state matrix). Fail if neither PNG nor HTML produced.
- **Architecture stage** (Layer 9.5): calls `generate_all_architecture_artifacts()` → `architecture.html` (Mermaid.js rendered), `api_contract.json` (endpoint list), `data_model.json` (tables/fields), `file_plan.json` (directory layout), `check_architecture_consistency()` (cross-references entity names between api ↔ data ↔ file). Fail on inconsistency.
- **Artifact contract upgrade**: `design` stage requires `ui_mockup` (was optional); `architecture` stage requires `architecture_diagram` (was optional).
- **Frontend display**: `UiMockupCard.vue` and `TaskArchDiagram.vue` render in `TaskArtifactTabs.vue` (detail page) and `SharePage.vue` (public share). Both support compact mode. i18n keys: `artifactContract.uiMockup`, `artifactContract.architectureDiagram`, `artifactContract.notGeneratedYet`.
- **Test file**: `test_phase5_visual_evidence.py` — 17 tests covering resource check, design tokens, screen plan, architect consistency, contract upgrade.

### QA Real Execution (Phase 6)

Testing stage runs real commands + browser smoke, no fake reports:
- **`QaExecutor`** (`services/qa_executor.py`): resource check (source_manifest, node, pnpm, playwright) → `run_all_commands` (pnpm install → pnpm build → pnpm test) → `run_browser_smoke` (pnpm preview → Playwright screenshot → console error collection → page text extraction).
- **Pipeline integration**: Phase 6 QA block executes post-LLM in testing stage. Blocked if source_manifest missing or essential tools unavailable. Failed if install/build/test fails. On success, writes QA artifacts (test_report, build_log, test_log, screenshot, console_errors).
- **Artifact contract upgrade**: `testing` stage now requires `test_report`, `build_log`, `screenshot` (was only `test_report`). `test_log` and `console_errors` added as optional types.
- **New artifact types**: `test_log` (text, collapsible log view), `console_errors` (json, browser error list).
- **`write_qa_artifacts`** (`services/artifact_writer.py`): formats structured markdown report from QaExecutor result dict, reads build.log/test.log from project_dir, base64-encodes screenshot PNG, writes all as typed TaskArtifact rows.
- **Frontend**: `TaskQATab.vue` shows command table with exit codes/durations, browser screenshot (click-to-enlarge), console error list (red highlight), collapsible build/test logs. Integrated into `TaskArtifactTabs.vue` (replaces TaskDocTab for test_report type) and `SharePage.vue`.
- **I18n**: `qa.testCommands`, `qa.browserScreenshot`, `qa.consoleErrors`, `qa.buildFailed`, `qa.buildLog`, `qa.testLog`, `qa.step`, `qa.command`, `qa.exitCode`, `qa.duration`, `qa.pass`, `qa.fail`, `qa.noQaData`.
- **Test file**: `test_phase6_qa_execution.py` — 22 tests covering resource check, manifest parsing, command execution, browser smoke, artifact contract upgrade, write_qa_artifacts integration.

### Deploy Closure (Phase 7)

Ensures every delivery has an accessible preview URL with health check and screenshot.

- **`deploy/local_preview.py`**: `LocalPreview` class starts `pnpm preview`, health-checks up to 15s, takes Playwright screenshot, cleans up on close. Port fallback (4173→4174→4175). `check_deploy_resources()` checks node/pnpm (local) and `VERCEL_TOKEN` env (Vercel).
- **Pipeline integration**: Phase 7 deploy block executes post-LLM in deployment stage. Vercel preferred when `VERCEL_TOKEN` available, falls back to local preview. Writes deploy artifacts on success.
- **Artifact contract upgrade**: `deployment` stage now requires `preview_url`, `screenshot`, `deploy_manifest`, `ops_runbook` (was only `ops_runbook`). `preview_url` added as new artifact type.
- **New artifact type**: `preview_url` (JSON) — `url`, `provider` (local|vercel), `health_status` (healthy|unhealthy|unknown), `screenshot_path`, `deployed_at`.
- **`write_deploy_artifacts`** (`services/artifact_writer.py`): writes `preview_url` JSON, `deploy_manifest` JSON, `screenshot` base64 PNG, `ops_runbook` markdown.
- **Frontend**: `DeployPreviewCard.vue` — URL click-to-open, health status tag (green/red/yellow), provider label, deployed screenshot. Shown in `TaskArtifactTabs.vue` (preview_url tab) and `SharePage.vue`.
- **I18n**: `deploy.previewUrl`, `deploy.provider`, `deploy.healthStatus`, `deploy.health_healthy`/`_unhealthy`/`_unknown`, `deploy.deployedAt`, `deploy.notAvailable`, `deploy.deployCardTitle`, `deploy.openPreview`, `deploy.deployedScreenshot`, `deploy.noDeployData`.

## Related Files

- [backend/CLAUDE.md](backend/CLAUDE.md) — Backend-specific conventions and testing patterns
- [packages/agent-hub-pipeline/README.md](packages/agent-hub-pipeline/README.md) — Stdlib-only maturation helpers (separate package)
