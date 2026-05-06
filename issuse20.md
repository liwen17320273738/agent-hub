# Issue 20｜路径 A 执行手册 — 30 天把 agent-hub 改成「AI 交付平台」

> 决策已定：**A 路径 = AI 交付平台**（一句话需求 → AI 团队跑 → 看到上线产物）
> 用户场景：**企业客户交付**
> 改造原则：**合并不删** —— 旧路由保留可访问，sidebar 只暴露收口后的 5 个入口
> 起始日：2026-04-22
> 验收日：2026-05-22

---

## 0. 北极星 / Hero 路径

> **价值观（来自 issuse19）**：当前更像「展示 Agent」的 A-agent，不是「让 Agent 完成工作」的 AI-Agent。
> 真正的主角不是 Agent 卡片，而是**任务的推进**。本期所有改造都服务于这一句。

```
飞书/QQ/iOS Shortcut/Web 一句话发需求
        │
        ▼
   📥 收件箱  (90 秒看到 Plan/Act 方案)
        │
        ▼ approve
   🤖 团队     (14 角色按 Plan 跑，实时看到谁在干什么)
        │
        ▼
   ✅ 验收闸门 (客户/你 签字)
        │
        ▼
   🚀 部署上线 (Vercel/CF/小程序/AppStore)
        │
        ▼
   🔗 客户分享页 (/share/:token)
```

**对外一句话**："Agent Hub —— 把企业需求一句话送进来，AI 团队 90 秒出方案，签字后自动跑到上线。"

---

## 1. 五个一级入口（最终态）

| 入口 | 路由 | 替代谁 | 必要二级 tab |
|------|------|--------|------------|
| 📥 **收件箱** | `/inbox` | Dashboard + PlanInbox + InsightsDigest + PipelineDashboard 的待办区 | 待审批计划 / 进行中 / 已完成 / 报表 |
| 🤖 **团队** | `/team` | AgentsConsole + AgentConsole + AgentStack + 14 个 agent 子项 | 实时活跃 / 角色目录 / 历史会话 |
| 🔧 **工作流** | `/workflow` | WorkflowBuilder + 部分 Pipeline | 画布 / 运行 / 模板 / 版本 |
| 📚 **资产** | `/assets` | 模型实验室 + Settings 模型部分 + MCP 服务器 + 技能中心 + 代码索引 + 知识库 | 模型 / MCP / 技能 / 知识库 / 代码索引 |
| ⚙️ **设置** | `/settings` | Settings 其余 + 新增 RBAC/SSO/计费 | 个人 / 工作区 / 成员 / SSO / 计费 / API Keys |

> **EvalLab、InsightsObservability、PipelineTaskDetail** 不在 sidebar，但通过深链可达（任务卡点击进入）。

---

## 1.5 交付包体系（详见 issuse21.md + issuse21.phase.md）

> **完整架构**：`issuse21.md`（§1-14 体系设计 + §15-18 架构决策与可扩展性分析）
> **落地分期**：`issuse21.phase.md`（Phase 0-4 + 每期验收标准）
> 本节只保留执行级摘要，**任何设计细节以 issuse21 为准**。

### 核心问题

产品设计稿、需求稿、UI 设计稿、代码、测试稿、验收稿、运维稿 —— 散在 6 个地方互不连通，且 `docs/delivery/*.md` 全任务共享同一目录会互相覆盖（P0 bug）。

### 8 个架构决策（issuse21 §16，已定）

| # | 决策 | 一句话 |
|---|------|--------|
| D1 | workspace 根 | env 配置 `WORKSPACE_ROOT`，默认 `data/workspace/` |
| D2 | Source of Truth | DB 权威，`manifest.json` 只是缓存 |
| D3 | 版本策略 | 追加版本文件（v1/v2），DB 存 `is_latest` |
| D4 | 打回重做 | 旧 artifact 标 `superseded` + 新版本 |
| D5 | 类型扩展 | `str` + `ArtifactTypeRegistry` 注册表 |
| D6 | 多 worktree | 本期一任务一 worktree，say no 多仓库 |
| D7 | 详情页 UI | 8 Tab + 顶部完成度缩略条 |
| D8 | 迁移节奏 | Phase 1-4 渐进 + 双写 2 周 |

### 目标态目录（issuse21 §3）

```
{WORKSPACE_ROOT}/
  tasks/TASK-{id}-{slug}/
    manifest.json
    docs/  (00-brief ~ 07-ops-runbook, 8 个 md)
    screenshots/
    logs/
    artifacts/
  worktrees/TASK-{id}-{slug}/  (真实代码，独立 git)
  shared/templates/            (从 docs/delivery/ 迁来的模板)
```

### 用户肉眼看到产物的 4 个入口

| 入口 | 路由 | 给谁 |
|------|------|------|
| 任务详情 8 Tab | `/tasks/:id`（默认交付视图） | 团队 |
| 客户分享页 | `/share/:token`（不登录） | 外部客户 |
| 打包下载 | `GET /api/tasks/:id/deliverables.zip` | 归档 |
| 磁盘直翻 | `{WORKSPACE_ROOT}/tasks/TASK-xxx/docs/` | 运维 |

### 与本期 30 天的映射

| 21.phase | 20 的周 | 做什么 |
|----------|--------|--------|
| Phase 0 | D1 | 确认决策 + config + migration 草案 |
| Phase 1 | W1 | 目录服务 + 模板 + 双写 |
| Phase 2 | W2 | DB 索引 + 工件 API + manifest 同步 |
| Phase 3 | W2-W3 | 8 Tab UI + 完成度缩略条 |
| Phase 4 | W4 | 关闭双写 + 归档 + 文档同步 |

---

## 2. 30 天里程碑（4 段冲刺）

### 🎯 D1–D7  Week 1：「不改后端，先治表」

目标：用户**第一眼**看到的产品结构变清楚，**不破坏任何现有功能**。

#### Sprint 1 任务清单（按文件）

- [ ] **`src/App.vue`** — sidebar 重写
  - 30 入口 → 5 入口（按上表）
  - 保留旧路由可访问（不删 router 项）
  - 删除 `coreAgents/supportAgents` 的 14 个 router-link，改进「团队」二级 tab
  - 顶部品牌只留 `Agent Hub`
- [ ] **`src/router/index.ts`** — 新增 4 个壳路由
  - `/inbox`、`/team`、`/workflow`、`/assets`（先不改 `/settings`）
  - 旧路由全部保留 + 加 `meta.legacy: true`（之后可在埋点里看是否还有人访问）
- [ ] **`src/views/Inbox.vue`** — 新建（聚合页）
  - 顶部 4 张 stat：待审批 / 进行中 / 今日完成 / 失败需关注
  - 主体 = 任务列表（合并自 PipelineDashboard 的 Stage Board + PlanInbox 的待审批）
  - 复用现有 `<PipelineDagCanvas>` 在右侧抽屉打开
- [ ] **`src/views/Team.vue`** — 新建（聚合页）
  - 14 角色卡片网格（复用 `<AgentCard>`）
  - 顶部「实时活跃」横条：当前正在执行的 agent + 任务名（订阅现有 SSE）
  - **角色不再是聊天入口，是任务的展开视图** —— 点角色卡 → 跳到「该角色最近参与的 5 个任务」，而不是直接进 chat
- [ ] **新建 `src/components/task/RoleSwimlane.vue`**（W2 才嵌入 PipelineTaskDetail，本周先建组件）
  - 任务详情页要让用户看见 14 角色协作，而不是只看 stage
  - 6 条泳道：接单 / 拆解 / 设计 / 开发 / 测试 / 验收
  - 每条泳道显示：负责 agent / 状态（done/running/blocked/skipped）/ 上一步产物链 / 谁打回了
  - 这是「14 角色不只是营销词」的核心 UI
- [ ] **`src/views/Workflow.vue`** — 新建（壳）
  - 默认嵌入现有 `WorkflowBuilder.vue`，加顶部 tab：画布 / 运行 / 模板 / 版本（后两个先 placeholder）
- [ ] **`src/views/Assets.vue`** — 新建（壳）
  - 5 个 tab：模型 / MCP / 技能 / 知识库（placeholder）/ 代码索引
  - 模型 tab 内嵌 `ModelLab.vue` 内容；MCP tab 嵌 `McpServers.vue`；技能 tab 嵌 `SkillsView.vue`；代码索引 tab 嵌 `CodebaseLab.vue`
- [ ] **品牌收口** — 全局替换
  - `Agent Stack` / `Agent Console` / `一人公司智能体中心` / `AI 军团流水线` → `Agent Hub`
  - 涉及 `Dashboard.vue` h1、`AgentStack.vue`、`AgentConsole.vue` 标题、`PipelineDashboard.vue` h1、`README.md`
- [ ] **🔥 修 P0 bug：交付文档全局共享会被覆盖**
  - `backend/app/api/delivery_docs.py` 的 `_DELIVERY_DIR` 和 `write_stage_output` / `compile_deliverables` 全部改成按 `{task_id}` 分目录：`data/deliverables/{task_id}/0X-xxx.md`
  - 所有读写接口加上 `task_id` 路径参数；旧 `/api/delivery-docs/{name}` 路由保留，自动取**当前激活 task**（兼容期 30 天后删）
  - 新建 `services/deliverable_store.py` 统一封装路径解析 + 防越权（参考 `pipeline_attachments.py` 的 `try_resolve_storage_path`）
  - 单测：两个 task 并发写 PRD 互不干扰
- [ ] **`src/views/Dashboard.vue`** — 改成 Hero CTA + 待办 + 最近任务（**三段式，不再是 teaser 墙**）
  - 删除 4 个 alert teaser（Agent Stack / Agent Console / Pipeline / ModelLab）
  - **顶部**：单 CTA「告诉 AI 军团你要做什么」大输入框 + 两个按钮「先给方案 / 直接执行」+ 5 个模板卡片（竞品调研 / PRD→代码 / 客服问答 / 周报生成 / 数据分析）
  - **中部 我的待办**（3 列）：
    - 待审批（链到 `/inbox?tab=pending`）
    - 执行中（链到 `/inbox?tab=running`）
    - 待验收（链到 `/inbox?tab=accept`）
  - **底部 最近任务卡**（每张只显示 4 字段）：标题 / 当前阶段 / 当前负责人 / 风险或卡点
  - 每张卡片右上角显示**交付包小徽章**：📋🎨🏗💻🧪✅🚀 7 个图标，已产出灰→亮，点击直达 `/tasks/:id?tab=deliverables`
  - 90 秒首屏出结果（先打通到 single-agent，不进 6 层 Pipeline）

#### D7 验收
- [ ] sidebar 只剩 5 项 + 设置
- [ ] 全站没有"Agent Stack/Console"字样
- [ ] 首页打开 5 秒内能看清"该干什么"
- [ ] 旧深链（`/Agent-stack` 等）仍可访问
- [ ] `make dev` 跑得起来，所有现有任务流不回归
- [ ] 两个 task 并发跑，PRD 不互相覆盖（开两个 tab 同时建任务验证）
- [ ] 任务卡上 7 个交付包图标灰/亮状态正确

---

### 🎯 D8–D14  Week 2：「Workflow 双系统合并 + 模型配置统一」

目标：**业务发了执行不下去**这个核心痛点根除。

- [ ] **新建 `backend/app/services/workflow_compiler.py`**
  - 把 `WorkflowDoc`（`src/services/workflowBuilder.ts` 的 doc 结构）编译成 `dag_orchestrator` 可执行的 graph
  - 节点类型先支持 6 个：`llm` / `http` / `condition` / `loop` / `tool` / `knowledge_retrieve`（最后一个先 stub）
  - 单测：`backend/tests/unit/test_workflow_compiler.py` 至少 6 个 case
- [ ] **`backend/app/api/workflows.py`** — 加 `POST /workflows/{id}/run`
  - 调 `workflow_compiler.compile(doc)` → `dag_orchestrator.run(graph)`
  - 返回 `task_id`，复用现有 SSE channel
- [ ] **`src/views/Workflow.vue`** — 「运行」tab 真能跑
  - 调 `POST /workflows/:id/run`，订阅 SSE，把状态喂给画布节点高亮
  - 复用现有 `<PipelineDagCanvas>` 渲染运行态
- [ ] **模型配置 4 层 → 1 层 + 模型策略三分视图**
  - 唯一真相源：`/api/models` + `model_provider` 表
  - `Settings.vue` 删除"模型"配置区块，跳转到 `/assets?tab=models`
  - `config.py` 标记 `LLM_API_URL/KEY/MODEL` 为 deprecated，仅作启动 fallback
  - `llm_proxy.py` / `llm_router.py` 优先读数据库，降级到 env
  - `Assets.vue` 模型 tab 加「测试连接」按钮（已有 ModelLab 逻辑改造）
  - **「模型」tab 内部按 3 类视图组织**（来自 issuse19 §3.2，不是 4 个 provider 平铺）：
    - **默认模型**（兜底，所有未指定阶段都走它）
    - **阶段模型**（planning / coding / review / verify 各自指定，对应 `pipeline_engine` 的 6 层）
    - **回退链**（Cost Governor / 限流 / 失败 时的降级顺序，例如 `Claude → DeepSeek → Qwen`）
  - 用户打开这个 tab 必须能在 5 秒内回答："谁是主模型 / 谁负责 coding / 失败兜底是谁"
  - 新增 `model_strategy` JSON 字段挂在 org / workspace 上，存这三类映射
- [ ] **任务详情新增「交付包」tab（核心）**
  - `PipelineTaskDetail.vue` 顶部 tabs：概览 / 角色泳道 / 交付包 / 阶段日志 / Trace
  - 「交付包」tab = 7 张明信片（`<DeliverableCards>` 组件，复用到 SharePage）
  - 数据源：新建 `GET /api/tasks/{id}/deliverables` 返回 `manifest.json` + 每个 doc 的元数据（存在/缺失/更新时间/字数）
  - 点开任意一张 → 右侧抽屉打开 markdown + 附件列表（图片走 gallery，二进制给下载链接）
  - 顶部「打包下载 zip」按钮 → `GET /api/tasks/{id}/deliverables.zip`（新增 `api/deliverables.py`）
- [ ] **代码卡片连 git**（弱依赖，能做就做）
  - `04-code/CHANGES.md` 由 codegen agent 在每次提交后追加：`- {sha}  {message}  ({files_changed} files)`
  - 卡片正面显示：`本次任务 N commits`，正文展示 commit 列表 + 链到 `repo_url/commit/{sha}`
- [ ] **大文件首拆**（非必须，但有时间就做）
  - `PipelineTaskDetail.vue` 2334 行 → 拆出 `<TaskHeader> <StagePanel> <ArtifactList> <FinalAcceptance> <TraceTimeline> <DeliverableCards> <RoleSwimlane>` 7 子组件，主文件 ≤ 400 行

#### D14 验收
- [ ] 用户在 Workflow Builder 画一个 3 节点 flow（输入 → LLM → HTTP）能点「运行」真跑出结果
- [ ] 改任意一个模型只需在 `/assets?tab=models` 一处改，env 不再生效优先
- [ ] `PipelineTaskDetail.vue` 主文件 ≤ 400 行
- [ ] 进任意一个跑完的任务 → 「交付包」tab 看到 7 张明信片，每张都能展开看 markdown 和附件
- [ ] 跑完 codegen 的任务，「💻 代码」卡能列出至少 1 条 commit + 链到 GitHub

---

### 🎯 D15–D21  Week 3：「Hero 路径打通 + 客户分享页」

目标：企业客户**真能看到产物 + 自己签字**。

- [ ] **首屏 Hero 路径打通**
  - `Dashboard.vue` 的 CTA「一句话发任务」走 `gateway.openclaw_intake(planMode=true)`
  - 90 秒内在 `Inbox` 看到 plan_pending
  - 3 模板（竞品调研 / 周报 / PRD→代码）端到端跑通
- [ ] **新建 `src/views/SharePage.vue`** + 路由 `/share/:token`
  - 公开访问（不要登录）
  - 顶部：任务标题 / 输入需求 / 最终状态徽章
  - **正中央：复用 `<DeliverableCards>` 7 张明信片**（这是客户来这里唯一想看的东西）
  - 底部：部署链接（一键打开） + 大「我同意验收 / 打回」按钮
  - 后端：`GET /api/share/:token` 验签 + 返回 manifest（新增 `services/share_token.py`，HMAC-SHA256 签名 task_id + ttl）
  - 任务详情页加「生成分享链接」按钮（可选 7 天 / 30 天 / 永久）
- [ ] **验收闸门 UI 升级**
  - 现有 `FinalAcceptanceModal.vue` 加「客户签字版」模式
  - 通过 share token 可以访问验收按钮（带 HMAC 签名防伪）
  - approve / reject 进入现有 `final_acceptance` 状态机
- [ ] **任务卡点击 → 深链 PipelineTaskDetail**（保留旧详情页，从 Inbox 跳）

#### D21 验收
- [ ] 在飞书 / iOS Shortcut 发"做一份 OpenAI 与 Anthropic 的竞品分析" → 90 秒看到 5 步方案 → approve → 看到 14 角色实时跑 → 拿到 markdown 报告
- [ ] 可以把这个任务生成分享链接发给同事，**对方不登录**就能看 7 张明信片 + 点验收
- [ ] 部署链接（Vercel / CF）可点开
- [ ] 分享页隐私模式（`/share/:token`）拒绝直接路径访问 `data/deliverables/{task_id}/...`，必须经过 token 验签

---

### 🎯 D22–D28  Week 4：「企业要素 + 可见性」

目标：**对企业客户敢卖**。

- [ ] **Workspace 模型 + 三角色 RBAC**
  - 新增 `models/workspace.py`：`Workspace`、`WorkspaceMember(role: admin|manager|member)`
  - 现有 `Org` 保留为顶级，Workspace 是 Org 下子单元
  - 资源（task/agent/workflow/skill/model）加 `workspace_id` 外键（nullable，向后兼容）
  - sidebar 顶部加 workspace 切换器
- [ ] **Credentials Vault 收口**
  - 新增 `models/credential.py`：API key / OAuth token 加密存储（fernet）
  - 旧 `model_provider.api_key` 迁移到 vault
  - 新 `/assets?tab=integrations`：GitHub / Jira / Slack / Notion 4 个连接器配置入口（先 4 个）
- [ ] **Cost Governor 加超额降级**
  - `cost_governor.py` 加单任务预算 + 超额自动切便宜模型
  - Inbox 任务卡显示成本
- [ ] **失败 RCA — 业务语言 + 下一步指引**（不是技术语言堆 trace）
  - 任务失败时把 trace 喂给 LLM 自动出 root cause
  - 在 `PipelineTaskDetail` 失败状态展示一张「业务卡片」，**4 个字段必须有**（来自 issuse19 §2.4）：
    - **卡在哪一关**（业务语言：「测试 agent 在跑回归时挂了」，不是「stage_3_failed: HTTP 500」）
    - **卡住原因**（人话一句：「调用 OpenAI 超时 60s」，附「查看 trace」折叠区给研发看）
    - **谁需要处理**（自动判定：是用户改 prompt / 是 admin 加额度 / 是 agent 重试）
    - **下一步怎么办**（带按钮：`重试本阶段` / `换模型重试` / `打回上一阶段` / `升级到人工`）
  - 新增 `services/rca_reporter.py`（已有同名文件，改成产出业务卡片格式而不是 raw trace）
- [ ] **交付包打包下载（zip 归档）**
  - `GET /api/tasks/{id}/deliverables.zip`：streaming zip 7 个 md + ui-mocks/ 目录 + manifest.json
  - 分享页加「下载完整交付包」按钮（不需要登录，HMAC token 鉴权）
  - 验收完成的任务，自动归档到 `data/deliverables/_archive/{yyyy-mm}/{task_id}.zip`
- [ ] **i18n 第一刀**
  - 装 `vue-i18n`，主航道（5 个 sidebar 入口 + Dashboard + Inbox + Team）中英双语
  - 其余页面留中文，下期补

#### D28 验收
- [ ] 可以创建第二个 workspace，资源完全隔离
- [ ] 邀请成员（admin/manager/member）权限正确
- [ ] 任务超预算自动切 DeepSeek，不熔断不影响交付
- [ ] 失败任务能看到 LLM 给的修复建议
- [ ] 主航道页面切换中英文 OK

---

## 3. 不在本期范围（明确 Say No）

为了 30 天打透 A 路径，以下**全部延后到下一期**：

- ❌ 知识库 / RAG 完整流水线（先用 stub，下期接 FastGPT 或 RAGFlow）
- ❌ 节点引擎补全到 20+ 节点（本期只 6 个够用）
- ❌ Skill Marketplace（本期 skills/ 文件夹保持原样）
- ❌ Eval Suite 自动 nightly run（保留骨架）
- ❌ Container 沙箱默认开启（仍 cwd 限制）
- ❌ 桌面 Electron 打包
- ❌ 多模态（图片 / PDF / 视频输入）
- ❌ 长任务 checkpoint > 1h
- ❌ MCP server 端（仅保留 client）

---

## 4. 文件改动清单（一目了然）

### 新建
```
src/views/Inbox.vue
src/views/Team.vue
src/views/Workflow.vue
src/views/Assets.vue
src/views/SharePage.vue
src/components/inbox/StatBar.vue
src/components/inbox/TaskList.vue
src/components/team/RealtimeStrip.vue
src/components/task/TaskHeader.vue          (拆 PipelineTaskDetail)
src/components/task/StagePanel.vue
src/components/task/ArtifactList.vue
src/components/task/TraceTimeline.vue
src/components/task/RoleSwimlane.vue        (14 角色协作可视化)
src/components/task/FailureCard.vue         (业务语言失败卡)
backend/app/services/workflow_compiler.py
backend/app/services/share_token.py
backend/app/services/deliverable_store.py    (统一交付包路径解析 + 防越权)
backend/app/models/workspace.py
backend/app/models/credential.py
backend/app/api/workspaces.py
backend/app/api/share.py
backend/app/api/credentials.py
backend/app/api/deliverables.py              (GET /tasks/:id/deliverables, .zip)
src/components/task/DeliverableCards.vue     (7 张明信片，复用到 SharePage)
backend/tests/unit/test_workflow_compiler.py
backend/tests/integration/test_share_endpoint.py
backend/tests/integration/test_workspace_rbac.py
```

### 重写
```
src/App.vue                        sidebar 30→5 入口
src/router/index.ts                新增 5 个一级路由 + legacy meta
src/views/Dashboard.vue            砍 4 alert，改 Hero CTA + 任务卡 7 图标
src/views/PipelineTaskDetail.vue   新增「交付包」tab，拆 7 子组件
backend/app/api/workflows.py       加 POST /run
backend/app/api/delivery_docs.py   🔥 修 P0 bug：按 task_id 分目录
README.md                          重写产品定位 + 删敏感信息
CLAUDE.md                          更新 5 入口架构 + 交付物存储说明
```

### 标记 deprecated（不删，留兼容）
```
src/views/AgentConsole.vue         legacy 路由保留
src/views/AgentStack.vue
src/views/AgentsConsole.vue
src/views/PipelineDashboard.vue    内容并入 Inbox 主体
src/views/PlanInbox.vue            并入 Inbox 「待审批」tab
src/views/InsightsDigest.vue       并入 Inbox 「报表」tab
backend/app/config.py              LLM_API_URL/KEY/MODEL 加 DeprecationWarning
```

---

## 5. 风险 & 回滚预案

| 风险 | 缓解 |
|------|------|
| sidebar 重构破坏老用户深链 | 旧路由全部保留 + 旧页面留代码；只是 sidebar 不暴露 |
| Workflow 编译器漏 case | 节点类型只先 6 个；老的 DAG 任务走旧 `dag_orchestrator` 路径 |
| 模型配置迁移导致线上断 | env 仍作 fallback，发现 DB 没配自动用 env |
| Workspace 加 workspace_id 字段破坏老数据 | 字段 nullable + 默认 NULL（即归属 Org 全局） |
| 30 天做不完 | 每周末砍一次 scope，先保 Hero 路径（D7+D14+D21），D22-D28 次要 |

---

## 6. 周报机制（强制）

每周五写：`issuse20.weekN.md`

| 项 | 内容 |
|----|------|
| ✅ 完成 | 勾掉的 checkbox |
| ❌ 没完成 | 原因 + 是否砍 / 推到下周 |
| 🐛 发现的新坑 | 列出来，决定本期补还是延后 |
| 📊 关键指标 | sidebar 入口数 / 单页最大行数 / Hero 路径秒数 / E2E 跑通的模板数 |

---

## 7. 启动检查（今天就做）

- [ ] 把这份文档评审一遍，砍掉你不认可的项
- [ ] 在 git 上开分支：`feat/issue20-week1-sidebar-collapse`
- [ ] 备份当前 `main`：`git tag pre-issue20-2026-04-22`
- [ ] 确认 `make dev` 当前状态正常
- [ ] 确认 D7 验收清单（**每周末必须能交付**）

---

## 8. 一句话作战指令

> **30 天后，企业客户在飞书发一句话需求，90 秒看到方案，签字后看到产物上线，并能把分享链接发给老板看。**
>
> 其他都是噪音。

—— 任何不服务这一句的功能，本期不做。
