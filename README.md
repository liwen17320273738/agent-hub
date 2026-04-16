Agent Hub is a browser-based “AI team” dashboard for solo founders and small teams. You pick a role (e.g. marketing, sales, support), chat with it like a consultant, and keep history on your device.

Core
Multiple agents — Each agent has its own name, style, system prompt, and quick-start prompts (one-click to send).
Chats & threads — Many conversations per agent; titles, sidebar, create/delete.
LLM connection — Any OpenAI-style API (e.g. DeepSeek, Qwen/DashScope, OpenAI). You set URL, API key, model, temperature, max tokens in Settings.
Chat experience
Streaming replies; Stop while generating.
Context limits — Caps on message count and total characters per request to control cost and length.
Optional summary — Generate a session summary and reuse it in later turns when old turns are trimmed.
Edit a user message — Change it and drop everything after it, then regenerate the assistant reply.
Regenerate the last assistant message only.
Copy message text; export the thread as Markdown or JSON.
Search & navigation
Search all sessions (sidebar) — Find by title or message text; open the right agent + conversation.
Filter the conversation list within the current agent.
Tools (optional)
If enabled in Settings and your API supports function calling: the model can call small built-in tools (e.g. current time, text stats, random integer). This path is non-streaming.
Models
Model lab — Table of common models with rough ratings (cost, speed, reasoning, Chinese, code, following instructions) and a same-prompt benchmark (latency, tokens if returned, errors).
Deploy & tech
Static site (Vue 3 + Vite + Pinia + Element Plus); hash URLs (/#/...), so it works on simple static hosts (e.g. GitHub Pages with the included workflow).
API keys stay in the browser (localStorage) — fine for personal use; not for high-security or shared PCs unless you add a backend.
In one line: it’s a multi-role AI chat hub with saved threads, search, export, cost-aware context, optional tools, and model comparison — not a full automation platform (no posting to social, email, or CRM by itself).

Enterprise mode (shared org, server-side keys)
Build with `VITE_ENTERPRISE=true` (see `.env.enterprise.example`). Local full stack: `pnpm dev:enterprise` (Vite + API). Production: `pnpm build && pnpm start` serves `dist` and APIs on one port (set env vars from `server/.env.example`).

- **Auth** — Cookie session; first boot creates an admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`. Admins can add members in Settings; everyone in the same org **shares all conversations**.
- **Concurrent edits (optimistic locking)** — Each conversation has a monotonic `revision`. PATCH requires `expectedRevision`; if someone else saved first, the API returns **409** and the client reloads the conversation list so you do not silently overwrite another user’s changes.
- **Database** — Default: file SQLite via **`node:sqlite`** (requires **Node ≥ 22.5**). Production option: set **`DATABASE_URL`** to a PostgreSQL connection string; the app uses the `pg` driver and auto-creates tables. `GET /health` returns `"database": "sqlite"` or `"postgres"` for a quick check.
- **SQLite experimental warning** — `pnpm dev:server` / `pnpm start` run Node with `--disable-warning=ExperimentalWarning` so logs stay clean (feature is still experimental in Node).
- **LLM** — `LLM_API_URL`, `LLM_API_KEY`, `LLM_MODEL` only on the server; chat, tools, and model-lab go through `/llm/*` with login.
- **API paths** — Dev: Vite proxies `/api/hub` to the Node app (prefix stripped). Prod same-origin: leave `VITE_API_BASE` unset. **Static host (e.g. GitHub Pages) + separate API**: deploy the built SPA to Pages, run the Node API elsewhere, set **`VITE_API_BASE`** at build time to that API’s public URL (with the same path layout, or adjust your reverse proxy). Cookies require **same-site** planning: prefer one registrable domain with subpaths or a gateway, or you will need a token-based auth follow-up.
- **Docker** — `docker compose up --build -d` builds the SPA inside the image and starts PostgreSQL + API (see `Dockerfile`, `docker-compose.yml`). Override secrets via environment or `.env` next to compose. Open `http://localhost:8787` (default admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`). Static page: `http://localhost:8787/beihai-trip-animated.html`.

### Deploy quick reference

| 方式 | 做法 | 访问 |
|------|------|------|
| **GitHub Pages**（静态，密钥在浏览器） | 推送到 `main`；仓库 **Settings → Pages → Source** 选 **GitHub Actions** | `https://<user>.github.io/<repo>/`；北海页 `…/beihai-trip-animated.html`。用户站点仓库在 Actions Variables 设 `VITE_BASE_PATH=/` |
| **Docker**（企业模式 + Postgres） | 根目录：`docker compose up --build -d`；改 `SESSION_SECRET`、`ADMIN_*` 等 | `http://<主机>:8787` |
| **任意静态托管** | `pnpm build`（按需 `VITE_BASE_PATH=/子路径/`）；上传 `dist/` | 需支持 SPA：`index.html` 回退（Hash 路由已用 `/#/`，多数主机可直接挂 `dist`） |

GitHub Actions 工作流：`.github/workflows/deploy-github-pages.yml`。

Kimi_key: sk-67EzrYtI6rARayc3eFisJuhDUPk0bljJH3BbjilM0Xgh7B8U

Qwn_key:
sk-1f19571aa000485f83a5db8f9f1ba196 

Deepseek_key:
sk-673436a6786144d79bb86a75e98f341a


邮箱: admin@example.com
密码: changeme
