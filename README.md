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

