# Agent Hub — Launch Kit

> Generated for the W3 launch sprint (see `issuse09.md`, route 2).
> Place this file under `docs/launch/` so we can iterate without polluting the repo root.

This kit contains:

1. **HN main post** (Show HN, ~600 words, ready to paste)
2. **HN first comment** (the "story" reply you post yourself within 60s of submission)
3. **Reddit variants** — `r/programming`, `r/devops`, `r/selfhosted`, `r/LocalLLaMA`
4. **Twitter / X thread** (8 tweets)
5. **dev.to long-form** (skeleton — fill in after launch day)
6. **Demo asset checklist** (what MUST exist before posting)
7. **Launch-day SOP** (timing, monitoring, response templates)
8. **Risk register** (what kills the launch + the mitigation)

All copy is in English. Adjust `<PLACEHOLDER>` markers before submitting.

---

## 1. HN — Show HN main post

**Title** (pick one — both tested against the heuristic in `issuse09.md`):

- `Show HN: Agent Hub – Open-source AI dev team that turns Jira tickets into merged PRs`
- `Show HN: Agent Hub – DAG-based AI agent platform with self-healing pipelines (<X>% on SWE-Bench Verified)`

> Use the second one **only if** the SWE-Bench score is ≥ 35% with full traces published.
> Otherwise lead with the Jira/GitHub angle — that is the actual differentiator.

**Body** (paste verbatim, ~600 words):

```text
Hi HN — I'm Agent. For the past few months I've been building Agent Hub
(github.com/<ORG>/agent-hub), an open-source AI agent platform that does
one thing well: it takes a Jira ticket or a GitHub issue, plans the work,
writes the code in a Docker sandbox, opens a PR, responds to reviewer
comments, and merges when a human approves.

It's self-hosted, BYO model keys (Claude, GPT, Gemini, DeepSeek, Qwen,
or any OpenAI-compatible endpoint), and the whole thing boots with
`docker compose up`.

# Why I built it

Most "AI agent" tools today fall into two camps:

  (a) frameworks (LangGraph, CrewAI, AutoGen) that ship primitives and
      leave you to build the actual product, or
  (b) IDE plugins (Aider, Cline, Copilot Workspace) that need a human
      sitting at the keyboard.

I wanted something asynchronous and ticket-native: file an issue,
walk away, come back to a PR thread you can review like any other.
The closest commercial equivalent is Devin, which is closed source,
ships your code to their cloud, and starts at $500/mo.

# What's actually shipping

  - DAG orchestrator with parallel stages, dependency resolution,
    skip conditions, retries, and human-approval gates
  - Self-healing: when a reviewer rejects a stage (in the UI OR via a
    Jira/GitHub comment), the agent gets the verbatim rejection text
    pre-pended to its system prompt and re-runs only the failed stage.
    No "regenerate everything from scratch."
  - Bidirectional Jira / GitHub integration with HMAC signature
    verification, X-GitHub-Delivery dedup, self-loop prevention (so the
    bot doesn't reply to its own comments), and Redis SETNX cross-worker
    dedup for escalations
  - Visual workflow builder (Vue Flow): drag agents onto a canvas, wire
    dependencies, hit Run, watch nodes turn green via SSE — or skip the
    UI and POST a JSON DAG directly
  - 11 built-in pipeline templates (web app, API service, full SaaS,
    fintech, mobile, …) plus your own
  - Multi-provider LLM router with per-task cost cap (cost_governor) and
    quality gates that auto-trigger reject loops when output scores are
    low
  - 160+ unit tests, runs on Postgres + Redis, ~3s test-suite turnaround

# What it does NOT do (yet)

  - Strong sandbox isolation (Docker `--network none --read-only --cap-drop ALL`,
    not microVM yet)
  - Multi-tenant RBAC beyond org-scoped resource isolation
  - Hosted SaaS (you self-host; cloud beta is on the roadmap, not built)

# SWE-Bench Verified: <X>%
<X>% Verified using <MODEL>, full traces and reproduction script at
github.com/<ORG>/agent-hub/blob/main/docs/BENCHMARK.md.
Beats <BASELINE_PROJECT> with the same model; trails Claude's official
agent by ~<DELTA>%. We publish failure-case analyses too — that's
where the interesting work is.

# Try it (≈3 minutes)

  git clone https://github.com/<ORG>/agent-hub
  cd agent-hub && cp .env.example .env  # paste your model key + GitHub PAT
  docker compose up -d
  open http://localhost:5200

Open the Workflow Builder, hit "Load template → web_app", click Run, and
watch the DAG execute against a tiny demo repo. There's a 90-second
demo gif in the README and a longer recording at <DEMO_URL>.

Happy to answer anything — especially curious if anyone has run agent
platforms in production. What broke first? Where did the LLM bills
sneak up on you?
```

> **Length check**: paste it through wc -w; HN truncates around 4,000 chars but
> 600 words renders cleanly above the fold on desktop and stays readable on mobile.

---

## 2. HN — First comment (post yourself within 60 seconds)

```text
Author here. Some context that didn't fit in the post:

* The "self-healing" loop was the hardest part. We tried a naive
  retry-with-same-prompt first and the agent confidently re-emitted
  the same broken patch. The fix was boring and effective: when a
  stage is REJECT_TOed by a reviewer, the orchestrator stuffs the
  reviewer's verbatim text into the agent's system prompt as a
  "previous-rejection" patch, then re-runs only that stage. Reject
  count is tracked per-stage and once it crosses a threshold the
  task escalates to humans (Slack / Feishu / Jira label) instead
  of looping forever.

* The Jira/GitHub bidirectional bit took the longest to harden:
  webhook signature verification, replay dedup via X-GitHub-Delivery
  with a Redis SETNX TTL, and self-loop prevention so the bot never
  reacts to a comment it itself authored. Without those three you
  get either spoofing or infinite reply loops the first time you
  scale to two workers.

* The DAG orchestrator predates the workflow builder. The builder is
  a thin frontend over the same DAGStage type — the JSON it produces
  is exactly what `POST /pipeline/tasks` already accepted. No DSL.

* Things I deliberately did NOT build for v0: VS Code plugin, hosted
  SaaS, multi-tenant RBAC, microVM isolation, RAG over the codebase.
  Each of those is a real engineering project; better to ship something
  honest than ship five half-features.

Open to ideas, criticism, and "you should really call this X" all of it.
```

---

## 3. Reddit variants

### 3a. r/programming

**Title**: `Open-source DAG-based AI agent platform — turns Jira tickets into PRs, self-heals on reviewer rejection`

**Body**:

```text
Built and open-sourced Agent Hub — an async AI agent platform that
treats Jira/GitHub issues as the input and PRs as the output.

Differences from what's already out there:

* Async and ticket-native (not an IDE plugin like Aider or Cline)
* Self-hosted (`docker compose up`), no data leaves your infra
* Bring your own model — OpenAI / Anthropic / Gemini / DeepSeek /
  any OpenAI-compatible endpoint via a router with per-task cost caps
* Self-healing pipeline: reviewer rejects → AI gets the verbatim
  rejection as a system-prompt patch and re-runs only the failed
  stage, not the whole thing
* Visual workflow builder (Vue Flow) on top of a JSON-based DAG
  spec — same JSON the API already accepted

What's NOT there yet, transparently: microVM isolation, hosted SaaS,
multi-tenant RBAC. These are on the roadmap.

160 backend unit tests, ~3s suite. Postgres + Redis. MIT-ish license
(currently MIT, may move to BSL once cloud beta lands).

Repo: github.com/<ORG>/agent-hub
Demo (90s): <URL>
SWE-Bench Verified: <X>% with full traces published

Curious what people running agents in prod have hit first — LLM
bills, sandbox escapes, prompt drift, or something I haven't
thought of?
```

### 3b. r/devops

**Title**: `Self-hosted AI agent platform with Jira/GitHub webhooks, signature verification, and Redis-backed cross-worker dedup`

**Body**:

```text
Posting in /r/devops because the operational story is half the
project: this is what I had to build to make agent automation safe
to point at a real backlog.

* HMAC webhook signature verification (Jira `JIRA_WEBHOOK_TOKEN`,
  GitHub `X-Hub-Signature-256`)
* X-GitHub-Delivery + Jira comment.id dedup via Redis `SET NX EX`
  so retries / replays never trigger a second AI run
* Self-loop prevention so the bot can never react to a comment it
  itself authored (caused two incidents in early dogfood before
  this landed)
* Cross-worker escalation dedup via the same Redis SETNX primitive
  — important the first time you horizontally scale workers
* In-memory fallback for the Redis primitives so unit tests run
  hermetically (`_MemoryFallback` matches the redis-py SET signature
  including NX/XX/EX flags)
* Docker sandbox: --network none, --read-only, --cap-drop ALL,
  --security-opt no-new-privileges, RW only on the per-task workspace
* Per-task cost cap via `cost_governor`, quality gates with auto
  reject-loop, human-approval gates as first-class DAG nodes
* SSE pipeline events over Redis Pub/Sub so multiple frontend tabs
  see the same DAG state

Stack: Python 3.11 + FastAPI, Postgres, Redis, Vue 3. 160 unit tests,
runs in ~3s. Self-hosted, no telemetry phoned home.

Repo: github.com/<ORG>/agent-hub
Mostly looking for "you should also have done X" — what did I miss?
```

### 3c. r/selfhosted

**Title**: `Agent Hub — open-source self-hosted AI dev team, one `docker compose up` away`

**Body**:

```text
Self-hostable AI agent platform that runs your Jira / GitHub backlog.

* `docker compose up` brings up Postgres + Redis + backend + frontend
* All API keys (LLM, GitHub PAT, Jira token) stay in YOUR .env —
  no SaaS account needed, no telemetry
* Works behind a corporate proxy / on a Hetzner box / on a homelab
  with a tiny Postgres
* RAM: ~1.2 GB for the full stack at idle; LLM calls are network-bound
* Disk: ~600 MB image + per-task workspaces (which you can prune)
* Bring your own model — Claude, GPT, DeepSeek, Qwen, or self-hosted
  Ollama via OpenAI-compatible mode

Use cases I've personally validated:

* Dogfood: Agent Hub fixes its own bugs from its own GitHub issues
* Personal side-projects (smaller is better while you're learning
  what it can/can't do)
* Internal tools at work where you're allowed to point an agent at
  a private repo

What it does NOT replace: code review, ownership, taste. It's an
async junior engineer that needs your approval to merge.

Repo: github.com/<ORG>/agent-hub
Docker compose: ~30 LOC, in the repo root
```

### 3d. r/LocalLLaMA

**Title**: `Open-source AI agent platform that works with local LLMs via OpenAI-compatible mode`

**Body**:

```text
Agent Hub — async AI agent platform — has a multi-provider router
that treats anything OpenAI-compatible as a first-class backend.
That means you can point it at:

* Ollama (`OPENAI_API_BASE=http://host:11434/v1`)
* vLLM
* LM Studio's local server
* TabbyAPI / Aphrodite
* …or hosted DeepSeek / Qwen / Claude / GPT for the heavy stages

You can mix-and-match per stage: planning on a hosted model, codegen
on a local 70B, review on a small local model. Per-task cost cap
applies regardless.

Reasonable expectations:

* A local 70B (Llama-3-70B / Qwen-2.5-72B class) is enough to drive
  the planning + review stages for small repos
* Codegen still benefits a lot from a frontier model right now;
  this is a per-stage choice, not all-or-nothing

Repo: github.com/<ORG>/agent-hub
Config docs: <URL>

Curious which local model + sampler combos people are using for
multi-agent setups. Anyone got a working Qwen-2.5-Coder + DeepSeek-V3
split running?
```

---

## 4. Twitter / X thread (8 tweets)

```text
1/ Open-sourcing Agent Hub today — an async AI agent platform that
   turns Jira tickets and GitHub issues into merged PRs.

   Self-hosted. BYO model. 160 unit tests. `docker compose up`.

   github.com/<ORG>/agent-hub
   <DEMO_GIF.gif>

2/ The pitch in one image: file an issue → AI plans → writes code
   in a Docker sandbox → opens a PR → reviewer comments trigger
   self-healing iterations → human approves → merge.

   <PIPELINE_DIAGRAM.png>

3/ Why "self-healing"?
   Naive agents loop forever on the same broken patch. We feed the
   reviewer's verbatim rejection text back as a system-prompt patch
   on the next attempt, and re-run only the failed stage.
   <REJECT_LOOP_GIF.gif>

4/ Bidirectional integration was the unsexy part that mattered most:
   • HMAC signature verification
   • X-GitHub-Delivery dedup via Redis SETNX
   • Self-loop prevention (bot never reacts to its own comments)
   • Cross-worker escalation dedup

5/ Visual workflow builder (Vue Flow) sits on top of the same DAG
   spec the API already accepted. No DSL — drag, drop, run, watch
   nodes turn green via SSE.
   <BUILDER_GIF.gif>

6/ Multi-provider LLM router with a per-task cost cap.
   Pick the model per stage: planning on Sonnet, codegen on
   DeepSeek, review on a tiny local model. Mix and match.

7/ SWE-Bench Verified: <X>% with full traces.
   Reproduction script lives in the repo. We publish failure-case
   analyses — that's where the interesting work is.
   <BENCH_CHART.png>

8/ Honest about what's NOT there: microVM isolation, hosted SaaS,
   multi-tenant RBAC. All on the roadmap.

   Repo + 90s demo + docs:
   github.com/<ORG>/agent-hub

   Comments, criticism, "you should also do X" — all welcome.
```

---

## 5. dev.to long-form (skeleton)

> Publish 5–7 days after HN, when traffic peaks have passed and you have feedback to incorporate.

```markdown
# How we built an open-source "Devin alternative" — and what it taught us about agent design

## TL;DR

(150 words)

## 1. The problem we wanted to solve

Why frameworks (LangGraph) and IDE plugins (Aider) both miss the
"async ticket-native" niche.

## 2. The architecture

* DAG orchestrator
* Self-healing reject loop
* Bidirectional Jira/GitHub
* Multi-provider LLM router
* Sandbox + cost cap

(diagrams + a few choice code snippets)

## 3. What we deliberately didn't build

(microVM, hosted SaaS, multi-tenant RBAC) — and why "ship honest"
beat "ship the wishlist".

## 4. SWE-Bench numbers + the failure cases

(this section is the long-tail SEO win — search "SWE-Bench failure
cases" months later and our post should rank)

## 5. What broke in production

(escalation cross-worker dedup, self-loop bug, the prompt-drift
story from the launch comments — pull at least 3 incidents from
the dogfood log)

## 6. What's next

(workflow builder v2, hosted beta, SWE-Bench Verified with bigger
context windows)

## 7. Try it

(docker compose up, link to repo, link to Discord/issues)
```

---

## 6. Demo asset checklist (DO NOT SUBMIT WITHOUT THESE)

| Asset                                      | Format    | Length  | Hosted at         | Status |
|--------------------------------------------|-----------|---------|-------------------|--------|
| Hero demo: issue → PR → merge              | MP4 + GIF | 60–90s  | YouTube + repo    | TODO   |
| Workflow builder drag-and-drop             | GIF       | 10–15s  | Repo `docs/img/`  | TODO   |
| SWE-Bench score chart vs baselines         | PNG       | static  | Repo + tweet      | TODO   |
| Architecture diagram (Mermaid → PNG)       | PNG       | static  | Repo `docs/img/`  | TODO   |
| README hero image (composite of the above) | PNG       | static  | Repo top          | TODO   |
| One-line install verified on fresh box     | shell log | —       | `docs/INSTALL.md` | TODO   |
| Demo repo with prepared issue              | repo      | —       | github.com/<ORG>/agent-hub-demo | TODO |

**Hard rule**: if "one-line install verified on fresh box" is not ✅, do NOT post to HN.
The first 50 visitors WILL try `docker compose up`. If it fails, you lose 30+ votes
and never recover them.

**GIF specs**: ≤ 8 MB (HN inlines them up to ~10 MB; bigger and the comment thread
won't render them). Use [`gifski`](https://gif.ski/) for size/quality balance.

---

## 7. Launch-day SOP

### T-7 days
- [ ] Demo assets complete (see §6)
- [ ] Repo description, topics, social-preview image set
- [ ] `LICENSE` file present and unambiguous
- [ ] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue templates
- [ ] CI passes on a fresh fork (someone unfamiliar runs the README)
- [ ] All hardcoded secrets purged from README and example configs
      *(critical — see Risk Register §8a)*
- [ ] Discord / Slack / GitHub Discussions ready, link in README

### T-1 day
- [ ] Final dogfood run: file 3 fresh issues, watch them merge
- [ ] Re-record demo if anything changed
- [ ] Pre-fill the HN first-comment text in a draft tab
- [ ] Schedule day off (or block 6 hours) — no meetings on launch day
- [ ] Notify 5 friendly accounts (Twitter / personal network) for early upvotes — but
      DO NOT ask them to upvote. Ask them to "take a look and comment if it's useful."

### T-0 (Tuesday or Wednesday)
- **06:50 PT** — Coffee. Open HN, Reddit tabs, Twitter, monitoring.
- **07:00 PT** — Submit to HN. Submit Reddit posts (4 subs) within 5 min.
- **07:01 PT** — Post the §2 first-comment.
- **07:05 PT** — Post the §4 Twitter thread.
- **07:00–11:00 PT** — Reply to every HN comment within 15 min. This is the single
  highest-leverage thing you'll do all year.
- **11:00 PT** — Lunch. Set a 30-min timer; come back.
- **11:30–18:00 PT** — Continue replying. Update README with the most-asked questions
  as a "FAQ from launch day" section.
- **18:00 PT** — Send dev.to draft to 2 friends for review.

### T+1 day
- [ ] Read every comment again, compile a "what users actually wanted" list
- [ ] Open GitHub issues for the top 5 with the `launch-feedback` label
- [ ] Triage stars-to-issues ratio: < 1 issue per 100 stars = healthy

### T+7 days
- [ ] Publish dev.to long-form
- [ ] Cross-post to lobste.rs (needs invite)
- [ ] First "what we shipped from launch feedback" tweet thread
- [ ] Decide: stay generic, or start the Resolvr vertical fork (per `issuse09.md` §1)

### Response templates (paste-ready)

**"How is this different from <X>?"**
```
Fair question. Three things:

1. Async + ticket-native — we don't need you at the keyboard;
   the trigger is a Jira/GitHub event, not a chat prompt.
2. Self-healing reject loop — reviewer comments are first-class
   inputs that re-run only the failed stage with the rejection
   text patched into the system prompt.
3. Self-hosted, BYO model, no telemetry — `docker compose up`,
   your data never leaves your infra.

That said, <X> is great at <Y> and we don't try to compete with
that. If your workflow is <Y>-shaped, use <X>.
```

**"What about prompt injection / sandbox escape?"**
```
Genuine concern. Today: Docker --network none --read-only
--cap-drop ALL --security-opt no-new-privileges, workspace mounted
RW only. That blocks the easy attacks but it's not microVM-grade.
The roadmap entry is honest: gVisor / Firecracker is on the
"v1 hardening" list, not done.

If you're considering this for production on untrusted issues,
I'd run it in a dedicated VM and treat the agent as a low-trust
user. Happy to talk through your threat model.
```

**"Will the cloud version be open-core?"**
```
No. The OSS version stays feature-complete. Cloud's value prop is
"I don't want to run Postgres + Redis + configure GitHub webhooks"
— it's not a feature gate.

License question is real though: we'll likely move from MIT to BSL
(n8n / Sentry / CockroachDB style) before the cloud beta to prevent
straight-up SaaS reselling. Source stays readable, self-hosting
stays free, only "host this for paying customers" is restricted.
```

---

## 8. Risk register

### 8a. README contains hardcoded API keys (CRITICAL)

`README.md:47-57` currently has plaintext Kimi / Qwen / DeepSeek API keys
and the default admin password.

**Action**: rotate those keys at the providers, then `git rm` them from the
README *and* from history (`git filter-repo` or BFG). Without this, posting
to HN is reckless — keys will be scraped within minutes of the post hitting
the front page.

### 8b. README is out of date (HIGH)

The README still describes Agent Hub as a "browser-based AI team dashboard
for solo founders". That's the *original* pitch. The current pitch is
"async AI dev team that turns Jira tickets into PRs."

**Action**: rewrite the README hero section using the §1 HN body as a
template before launch. Move the legacy "browser-based dashboard" content
to `docs/HISTORY.md` if you want to keep it.

### 8c. Demo repo doesn't exist (HIGH)

There's nowhere safe to point first-time users for a 3-minute "wow" run.

**Action**: create `github.com/<ORG>/agent-hub-demo` — a tiny Python or
TypeScript repo with a deliberately broken function and a pre-filed issue
that takes the agent ~2 minutes to fix. Pin it from the main repo README.

### 8d. SWE-Bench score not yet measured (MEDIUM)

We can post without a number, but losing the SWE-Bench credibility halves
the number of HN/Reddit users who'll trust the project. The Verified score
is the cheapest credibility we'll ever buy.

**Action**: prioritize the SWE-Bench harness (this kit's companion task)
before launch. Acceptable minimum: 50 instances run end-to-end with full
traces. Better: full Verified.

### 8e. No license-clarity decision (MEDIUM)

MIT now, BSL later — fine, but be explicit in the launch comment so the
first BSL-skeptic doesn't kneecap the thread.

**Action**: add a line to §1 HN body: "Currently MIT; may move to BSL when
cloud beta lands. OSS feature parity guaranteed."

### 8f. Launch day overlaps with $BIG_AI_NEWS (LOW, unpredictable)

Anthropic / OpenAI release cadence will pre-empt your front-page slot if
a model drop lands the same day.

**Action**: monitor `news.ycombinator.com/front` the morning of. If a
major model release is in the top 5, postpone 24 hours. There is no
prize for shipping into noise.

---

## Appendix — copy-pastable post-flight checklist

```
[ ] Keys rotated, README purged
[ ] README rewritten with current pitch
[ ] Demo repo created and pinned
[ ] SWE-Bench number published with traces
[ ] License decision noted in launch post
[ ] No major AI news pre-empting today
[ ] Demo GIF ≤ 8 MB, hosted in repo
[ ] First-comment text in clipboard
[ ] Twitter thread scheduled (or composed in TweetDeck)
[ ] 6h calendar block confirmed
[ ] Submit at 07:00 PT Tuesday or Wednesday
```
