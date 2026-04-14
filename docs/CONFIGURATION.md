# Configuration Guide

Agent Hub uses a layered configuration system:

1. **`backend/.env`** — Environment variables (secrets, database URLs)
2. **`config.yaml`** — Application config (models, pipeline, skills, memory)

## config.yaml

Copy `config.example.yaml` to `config.yaml` at the project root.

### Models

Define available LLM providers:

```yaml
models:
  - name: gpt-4o
    display_name: GPT-4o
    provider: openai
    model: gpt-4o
    api_key: $OPENAI_API_KEY  # resolved from env
    max_tokens: 4096

  - name: claude-sonnet-4
    display_name: Claude Sonnet 4
    provider: anthropic
    model: claude-sonnet-4-20250514
    api_key: $ANTHROPIC_API_KEY
    max_tokens: 8192

  - name: deepseek-chat
    display_name: DeepSeek Chat
    provider: openai_compatible
    model: deepseek-chat
    api_key: $DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com/v1
```

Supported providers:
- `openai` — OpenAI native API
- `anthropic` — Anthropic Claude
- `gemini` — Google Gemini
- `openai_compatible` — Any OpenAI-compatible endpoint

Values starting with `$` are resolved as environment variables.

### Pipeline

Configure the default stage sequence and maturation layers:

```yaml
pipeline:
  default_stages:
    - planning
    - architecture
    - implementation
    - testing
    - review
    - deployment

  maturation_layers:
    - planner
    - memory
    - tools
    - llm
    - self_verify
    - guardrails
    - observability
    - memory_store
```

### Skills

```yaml
skills:
  path: ../skills          # relative to backend/
  categories:
    - public               # committed skills
    - custom               # user-created (gitignored)
```

### Memory

```yaml
memory:
  enabled: true
  working_memory_ttl: 3600              # seconds
  max_long_term_entries: 1000
  max_injection_tokens: 2000
  pattern_confidence_threshold: 0.7
```

### Gateway Channels

```yaml
channels:
  feishu:
    enabled: false
    app_id: $FEISHU_APP_ID
    app_secret: $FEISHU_APP_SECRET
  qq:
    enabled: false
    app_id: $QQ_APP_ID
    token: $QQ_TOKEN
```

### Executor

```yaml
executor:
  allowed_dirs:
    - /tmp/agent-hub
  timeout_seconds: 300
```

## Environment Variables Reference

All environment variables are defined in `backend/.env`. See `backend/.env.example` for the full list with descriptions.

Key variables:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL async connection string |
| `REDIS_URL` | Redis connection string |
| `JWT_SECRET` | JWT signing secret (must be >= 32 characters) |
| `ADMIN_EMAIL` | Initial admin user email |
| `ADMIN_PASSWORD` | Initial admin user password |
| `LLM_API_URL` | Default LLM endpoint |
| `LLM_API_KEY` | Default LLM API key |
| `LLM_MODEL` | Default model name |
| `CORS_ORIGINS` | JSON array of allowed CORS origins |
