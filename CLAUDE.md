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
│   │   │   ├── pipeline_engine.py # 6-layer maturation pipeline
│   │   │   ├── dag_orchestrator.py # DAG-based orchestration
│   │   │   ├── lead_agent.py     # Task decomposition & parallel exec
│   │   │   ├── agent_runtime.py  # ReAct loop with tools/memory
│   │   │   ├── memory.py         # 3-layer memory (long-term, working, patterns)
│   │   │   ├── sse.py            # Redis Pub/Sub SSE
│   │   │   ├── executor_bridge.py # Claude CLI subprocess
│   │   │   ├── skill_marketplace.py # Skill registry & execution
│   │   │   ├── self_verify.py    # Output verification
│   │   │   ├── guardrails.py     # Safety guardrails
│   │   │   ├── observability.py  # Tracing & audit
│   │   │   ├── collaboration.py  # Pipeline stages definition
│   │   │   ├── planner_worker.py # Model resolution
│   │   │   ├── model_registry.py # Model catalog
│   │   │   └── token_tracker.py  # Usage tracking
│   │   ├── models/               # SQLAlchemy ORM
│   │   │   ├── user.py           # Org + User
│   │   │   ├── workspace.py      # Workspace + WorkspaceMember
│   │   │   ├── credential.py    # Fernet-encrypted vault
│   │   │   ├── pipeline.py       # PipelineTask + Stage + Artifact
│   │   │   ├── workflow.py       # Saved workflow DAGs
│   │   │   ├── agent.py          # AgentDefinition + skills/rules
│   │   │   └── observability.py  # Traces, spans, audit logs
│   │   ├── schemas/              # Pydantic request/response
│   │   └── middleware/           # Rate limiting
│   └── tests/                    # Pytest suite
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
│   │   └── PipelineTaskDetail.vue # 3-tab: overview/deliverables/swimlane
│   ├── components/
│   │   ├── workspace/WorkspaceSwitcher.vue
│   │   ├── task/FailureCard.vue  # RCA 4-field business card
│   │   ├── task/DeliverableCards.vue # 8 doc cards (reused in SharePage)
│   │   ├── task/ArtifactCompletionBar.vue
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
make lint       # Lint all code
```

**Backend directory** (backend only):
```bash
make install    # pip install -r requirements.txt
make dev        # uvicorn with --reload
make test       # pytest tests/ -v
make lint       # ruff check
make format     # ruff format
```

## Architecture Details

### LLM Router (`app/services/llm_router.py`)

Multi-provider routing supporting:
- **OpenAI-compatible**: OpenAI, DeepSeek, Dashscope (Qwen), Zhipu (GLM), any custom endpoint
- **Anthropic**: Claude models via native API
- **Gemini**: Google models via REST API

Provider is inferred from model name, URL, or explicit header. API keys are passed via headers (never in URLs).

### Pipeline Engine (`app/services/pipeline_engine.py`)

6-layer maturation stack for each pipeline stage:
1. **Planner** — model resolution
2. **Memory** — context injection from history
3. **Tools** — skill schema validation
4. **LLM** — actual model call
5. **Self-verify** — output quality checks
6. **Guardrails** — safety validation
7. **Observability** — trace recording
8. **Memory Store** — persist output for future context

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

### Test-Driven Development
- Write tests in `backend/tests/` following `test_<feature>.py` convention
- Run: `make test` (from root) or `cd backend && python3 -m pytest tests/ -v`
- Tests must pass before a feature is considered complete

### Documentation Update Policy
When making code changes, update:
- `CLAUDE.md` for architecture/development changes
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

### Pipeline & Workflow
- 14-role agent team with DAG orchestration
- Visual workflow builder → compiler → runner
- 8 standard delivery documents per task
- Quality gates, self-verify, guardrails at every stage
