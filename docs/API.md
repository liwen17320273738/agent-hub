# API Reference

Base URL: `http://localhost:8000` (direct) or `http://localhost/api` (through nginx)

## Authentication

All protected endpoints require JWT token in `Authorization: Bearer <token>` header.

Pipeline endpoints alternatively accept `X-Pipeline-Key` header.

### Auth Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login, returns JWT token |
| GET | `/api/auth/me` | Get current user info |

## Agents

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agents` | List all agents |
| POST | `/api/agents` | Create agent |
| GET | `/api/agents/{id}` | Get agent details |
| PUT | `/api/agents/{id}` | Update agent |
| DELETE | `/api/agents/{id}` | Delete agent |

## Conversations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/conversations` | List conversations |
| POST | `/api/conversations` | Create conversation |
| GET | `/api/conversations/{id}` | Get conversation with messages |
| DELETE | `/api/conversations/{id}` | Delete conversation |
| POST | `/api/conversations/{id}/messages` | Add message |

## LLM Proxy

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Chat completion (streaming SSE) |

Request body:
```json
{
  "messages": [{"role": "user", "content": "..."}],
  "model": "deepseek-chat",
  "agentId": "optional-agent-id",
  "conversationId": "optional-conversation-id"
}
```

## Pipeline

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pipeline/tasks` | List pipeline tasks |
| POST | `/api/pipeline/tasks` | Create task |
| GET | `/api/pipeline/tasks/{id}` | Get task detail |
| PATCH | `/api/pipeline/tasks/{id}` | Update task |
| POST | `/api/pipeline/tasks/{id}/auto-run` | Run linear pipeline |
| POST | `/api/pipeline/tasks/{id}/dag-run` | Run DAG pipeline |
| POST | `/api/pipeline/tasks/{id}/smart-run` | Lead Agent decomposition + parallel exec |
| POST | `/api/pipeline/tasks/{id}/analyze` | Lead Agent analysis only |
| POST | `/api/pipeline/tasks/{id}/run-stage` | Run single stage |
| GET | `/api/pipeline/skills` | List pipeline skills |
| PUT | `/api/pipeline/skills/{name}` | Toggle skill |
| GET | `/api/pipeline/templates` | List DAG templates |

## Skills

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/skills` | List all skills |
| POST | `/api/skills` | Create skill |
| GET | `/api/skills/{id}` | Get skill details |
| PUT | `/api/skills/{id}` | Update skill |
| DELETE | `/api/skills/{id}` | Delete skill |
| GET | `/api/skills/marketplace/catalog` | Browse skill catalog |
| POST | `/api/skills/marketplace/install/{id}` | Install skill |
| POST | `/api/skills/{id}/execute` | Execute skill |

## Memory

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/memory/search` | Search long-term memory |
| GET | `/api/memory/working` | Get working memory for task |
| POST | `/api/memory/working` | Set working memory |
| DELETE | `/api/memory/working/{task_id}` | Clear working memory |
| GET | `/api/memory/patterns` | List learned patterns |

## Executor

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/executor/run` | Execute Claude Code task |
| GET | `/api/executor/jobs/{id}` | Get job status |
| GET | `/api/executor/jobs/task/{task_id}` | List jobs for task |
| POST | `/api/executor/jobs/{id}/kill` | Kill running job |

## Events (SSE)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/events/stream` | SSE event stream |
| GET | `/api/events/clients` | Connected client count |

## Gateway

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/gateway/feishu/webhook` | Feishu webhook |
| POST | `/api/gateway/qq/webhook` | QQ webhook |
| POST | `/api/gateway/openclaw/message` | OpenClaw message |

## Models

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/models` | List model providers |
| POST | `/api/models` | Create provider |
| PUT | `/api/models/{id}` | Update provider |
| DELETE | `/api/models/{id}` | Delete provider |

## Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |

Response: `{"status": "healthy", "service": "agent-hub"}`
