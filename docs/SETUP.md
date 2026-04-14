# Setup Guide

## Prerequisites

Run `make check` to verify all dependencies are installed:

| Tool | Version | Required |
|------|---------|----------|
| Node.js | >= 18 | Yes |
| pnpm | any | Yes |
| Python | >= 3.9 | Yes |
| PostgreSQL | >= 14 | For production |
| Redis | >= 6 | For SSE + cache |
| Docker | any | For Docker deployment |

## Quick Start (Local Development)

### 1. Generate config files

```bash
make config
```

This creates:
- `backend/.env` from `backend/.env.example` (with auto-generated JWT secret)
- `.env` from `.env.example`
- `config.yaml` from `config.example.yaml`

### 2. Configure API keys

Edit `backend/.env` and add your LLM API keys:

```bash
# Required: at least one LLM provider
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...
# or
DEEPSEEK_API_KEY=sk-...
```

### 3. Install dependencies

```bash
make install
```

### 4. Set up database

```bash
# Start PostgreSQL and Redis (if not running)
# Option A: Docker
docker run -d --name agenthub-db -e POSTGRES_USER=agenthub -e POSTGRES_PASSWORD=agenthub -e POSTGRES_DB=agenthub -p 5432:5432 postgres:16-alpine
docker run -d --name agenthub-redis -p 6379:6379 redis:7-alpine

# Option B: Local install
brew install postgresql redis  # macOS
# or: sudo apt install postgresql redis  # Ubuntu

# Run migrations
cd backend && python3 -m alembic upgrade head
```

### 5. Start development server

```bash
make dev
```

Access:
- Frontend: http://localhost:5200
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## Docker Deployment

### 1. Configure

```bash
make config
# Edit .env with production values
```

### 2. Build and start

```bash
make docker-build
make docker-start
```

Access: http://localhost (port 80)

### 3. Stop

```bash
make docker-stop
```

## Environment Variables

### Backend (`backend/.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `JWT_SECRET` | JWT signing key (>= 32 chars) | **Required** |
| `ADMIN_EMAIL` | Initial admin email | `admin@example.com` |
| `ADMIN_PASSWORD` | Initial admin password | `changeme` |
| `OPENAI_API_KEY` | OpenAI API key | |
| `ANTHROPIC_API_KEY` | Anthropic API key | |
| `DEEPSEEK_API_KEY` | DeepSeek API key | |
| `GOOGLE_API_KEY` | Google Gemini API key | |
| `CORS_ORIGINS` | Allowed origins (JSON array) | `["http://localhost:5200"]` |

### Frontend

Frontend connects to backend via Vite proxy in development (configured in `vite.config.ts`).

In production (Docker), nginx proxies `/api/*` to the backend.

## Troubleshooting

### Backend won't start
- Check `logs/backend.log`
- Verify PostgreSQL is running: `pg_isready`
- Verify Redis is running: `redis-cli ping`
- Check `.env` file exists with valid `JWT_SECRET`

### Frontend won't start
- Check `logs/frontend.log`
- Run `pnpm install` to ensure dependencies are installed
- Verify port 5200 is not in use

### Database migration errors
- Run `cd backend && python3 -m alembic upgrade head`
- If schema conflicts: `python3 -m alembic stamp head` then re-run
