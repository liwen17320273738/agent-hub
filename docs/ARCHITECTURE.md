# Architecture

## System Overview

```
┌────────────────────────────────────────────────────────────────┐
│                         Nginx (:80)                            │
│  /api/* → Backend    /* → Frontend                             │
└────────────┬──────────────────────────┬────────────────────────┘
             │                          │
     ┌───────▼───────┐         ┌───────▼───────┐
     │  Backend API  │         │   Frontend    │
     │  FastAPI      │         │   Vue 3       │
     │  :8000        │         │   :5200       │
     └───┬───┬───┬───┘         └───────────────┘
         │   │   │
    ┌────┘   │   └────┐
    ▼        ▼        ▼
┌────────┐ ┌──────┐ ┌──────────┐
│ Postgres│ │Redis │ │ External │
│ :5432   │ │:6379 │ │ LLM APIs │
└─────────┘ └──────┘ └──────────┘
```

## Backend Architecture

### Layer Separation

```
app/api/        → Route handlers (thin — parse request, call service, return response)
app/services/   → Business logic (thick — all domain logic, LLM calls, orchestration)
app/models/     → ORM models (passive — no business logic)
app/schemas/    → Pydantic schemas (request/response validation)
app/middleware/  → ASGI middleware (rate limiting, etc.)
```

### Request Flow

```
HTTP Request
  → FastAPI Router (app/api/*.py)
    → Auth Dependency (security.py)
    → Service Function (app/services/*.py)
      → Database (app/models/*.py via SQLAlchemy)
      → Redis (redis_client.py)
      → External API (LLM providers)
    → Pydantic Response
  → HTTP Response
```

### Pipeline Execution Flow

```
Task Created
  → Lead Agent Decomposition (lead_agent.py)
    → Subtask Planning
    → Dependency Analysis
  → Pipeline Engine (pipeline_engine.py)
    → Stage 1: Planning
    → Stage 2: Architecture
    → Stage 3: Implementation
    → Stage 4: Testing
    → Stage 5: Review
    → Stage 6: Deployment
  → Each Stage passes through 6 Maturation Layers:
    1. Planner (model selection)
    2. Memory (context injection)
    3. Tools (skill validation)
    4. LLM (model call)
    5. Self-verify (quality check)
    6. Guardrails (safety check)
    → Observability (trace recording)
    → Memory Store (persist for future)
```

### DAG Orchestration

```
                    ┌──────────┐
                    │ planning │
                    └────┬─────┘
              ┌──────────┼──────────┐
              ▼          ▼          ▼
        ┌──────────┐ ┌────────┐ ┌──────┐
        │arch_design│ │research│ │ spec │
        └────┬─────┘ └───┬────┘ └──┬───┘
             └────────────┼────────┘
                          ▼
                   ┌──────────────┐
                   │implementation│
                   └──────┬───────┘
                          ▼
                    ┌──────────┐
                    │ testing  │
                    └──────┬───┘
                          ▼
                    ┌──────────┐
                    │  review  │
                    └──────────┘
```

Stages with satisfied dependencies execute in parallel.

### Memory Architecture

```
┌─────────────────────────────────────────┐
│              Memory System              │
├──────────────┬────────────┬─────────────┤
│  Long-term   │  Working   │  Patterns   │
│ (PostgreSQL) │  (Redis)   │ (PostgreSQL) │
│              │  TTL-based │              │
│ • Task output│ • Session  │ • Recurring  │
│ • Facts      │   context  │   behaviors  │
│ • History    │ • Temp vars│ • Confidence │
└──────────────┴────────────┴─────────────┘
```

## Frontend Architecture

```
src/
├── App.vue              # Root component with router-view
├── main.ts              # Entry point (createApp, plugins)
├── router/              # Vue Router configuration
├── views/               # Page-level components
│   ├── AgentChat.vue    # Main chat interface
│   ├── Dashboard.vue    # Agent/conversation overview
│   ├── PipelineDashboard.vue  # Pipeline management
│   ├── PipelineTaskDetail.vue # Task detail view
│   ├── Settings.vue     # Settings page
│   └── SkillsView.vue   # Skill marketplace
├── components/          # Shared UI components
├── services/            # API clients
│   ├── api.ts           # Base fetch wrapper with JWT
│   ├── pipelineApi.ts   # Pipeline-specific API
│   ├── messageContext.ts # Chat context builder
│   └── modelCatalog.ts  # Model metadata
├── stores/              # Pinia state management
│   ├── settings.ts      # App settings
│   └── pipeline.ts      # Pipeline state
└── agents/              # Agent type definitions
    ├── types.ts          # AgentConfig, ToolBinding
    └── registry.ts       # Agent registry
```

## Data Flow

### Chat Flow
```
User Input → AgentChat.vue
  → api.ts (POST /api/chat)
  → llm_proxy.py (router)
  → llm_router.py (service)
    → Provider detection (OpenAI/Anthropic/Gemini/...)
    → API call with streaming
  → SSE stream back to frontend
  → Markdown rendering in chat
```

### Pipeline Flow
```
User Creates Task → PipelineDashboard.vue
  → pipelineApi.ts (POST /api/pipeline/tasks)
  → pipeline.py (router)
  → PipelineTask ORM (database)
  → SSE event: task_created

User Runs Pipeline → pipelineApi.ts (POST .../auto-run)
  → pipeline_engine.py
    → For each stage:
      → Maturation layers
      → SSE event: stage_update
  → SSE event: task_completed
  → Frontend updates via EventSource
```

## External Integrations

| Integration | Protocol | Purpose |
|------------|----------|---------|
| OpenAI | HTTPS REST | LLM inference |
| Anthropic | HTTPS REST | LLM inference |
| Google Gemini | HTTPS REST | LLM inference |
| DeepSeek | HTTPS REST (OpenAI-compatible) | LLM inference |
| Feishu | Webhook + REST | IM channel |
| QQ | Webhook | IM channel |
| Redis | TCP | Cache, Pub/Sub, Working Memory |
| PostgreSQL | TCP | Persistent storage |
