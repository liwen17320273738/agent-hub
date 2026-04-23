# Issue 16｜Agent Hub vs. 九大开源平台 — 全景评估、最佳资源抽取与缺陷盘点

> 对标对象：Coze Studio · Dify · FastGPT · LangFlow · n8n · RAGFlow · AnythingLLM · Karpathy/Anthropic Skills · Firecrawl
> 评估日期：2026-04-22
> 基线：`backend/app` 全量代码 + `AI-Agent.md` 自检 + 9 平台 2026 最新版本

---

## 0. TL;DR — 三句话结论

1. **agent-hub 的护城河**：多渠道 IM 入口（飞书/QQ/OpenClaw/iOS 快捷指令）+ 14 角色 SDLC 流水线 + 真部署到生产（Vercel/CF/微信小程序/AppStore）+ Plan/Act 双模 — 这条「需求 → 上线」的端到端闭环，9 个对标平台**没有一个能做到**。
2. **agent-hub 的硬伤**：**没有知识库/RAG 系统**、**没有可视化工作流画布**、**没有插件市场 / 模板生态**、**没有 Eval 自评闭环**、**没有容器级沙箱**、**没有 Web 抓取/深度文档解析** — 这 6 个能力是 9 平台里**至少 5 个都有**的标配。
3. **战略选择**：**不要做"另一个 Dify"**，而要做**"AI 团队 OS"**：把 9 个平台**当组件吸进来**（Firecrawl 当浏览器、RAGFlow 当 KB 引擎、Coze Plugins 当工具源、Karpathy/Anthropic Skills 当能力包），把自己的 14 角色 + 真部署护城河做厚。

---

## 1. agent-hub 现状盘点（事实清单）

| 模块 | 实现位置 | 等级 | 备注 |
|------|---------|------|------|
| 多模型路由 | `services/llm_router.py` | ★★★★ | OpenAI/Anthropic/Gemini/DeepSeek/Qwen/GLM 全通 |
| OpenAI 兼容代理 | `api/openai_compat.py` | ★★★★ | `/v1/chat/completions` 直挂 |
| Pipeline 6 层产线 | `services/pipeline_engine.py` (1842 行) | ★★★★ | planner→memory→tools→llm→verify→guardrails→trace→memory |
| DAG 编排 | `services/dag_orchestrator.py` | ★★★ | 拓扑并行；模板：web_app / api_service / data_pipeline |
| 14 角色 Agent | `agents/seed.py` | ★★ | 14 个种子，**只有 5 个真接到 SDLC 阶段** |
| MCP 客户端 | `services/mcp_client.py` (385 行) | ★★★ | streamable_http + sse 双 transport，仅 tools，无 resources/prompts/sampling |
| 浏览器工具 | `services/tools/browser_tool.py` | ★★ | Playwright **soft-import**（未默认安装）、无 agent loop、无登录态复用 |
| 沙箱 | `services/tools/bash_tool.py` + `docker_sandbox.py` | ★★ | cwd 限制 + 可选 Docker exec，**默认仍跑在 host** |
| 三层记忆 | `services/memory.py` | ★★★ | TaskMemory(pgvector) + Redis working + LearnedPattern |
| Codebase 索引 | `services/codebase_indexer.py` | ★★ | 已有，但与 RAG 的成熟度差很远 |
| 多渠道 Gateway | `api/gateway.py` (1440 行) | ★★★★★ | 飞书/QQ/Slack/OpenClaw/iOS Shortcut，**Plan/Act 已闭环** |
| 真部署 | `services/deploy/*` | ★★★★ | Vercel / Cloudflare / WeChat 小程序 / AppStore / GooglePlay |
| Skill 文件包 | `skills/public/*` (15 个) | ★★ | Markdown + YAML，但**无版本/无依赖/无市场/无远程订阅** |
| Eval 系统 | `services/eval_runner.py` (246 行) + `api/eval.py` | ★ | **骨架级** — 没有标准基准、没有 nightly run、没有回归对比 |
| 观测 | `services/observability.py` + `_dashboard.py` | ★★★ | trace/span/token，**无 RCA、无成本告警** |
| Cost Governor | `services/cost_governor.py` | ★★ | 有限额，**无超额自动降级模型 / 无熔断** |
| Scheduler | `services/task_scheduler.py` | ★★ | 有，但**未对接到 IM Trigger** |
| **知识库 RAG** | ❌ | ☆ | **完全没有** —— 没有 KB 实体、没有文档解析、没有切片策略、没有重排 |
| **可视化工作流画布** | `views/WorkflowBuilder.vue` + Vue Flow | ★★ | 前端有画布，**后端 `api/workflows.py` 只是 doc 存档**，无节点执行引擎 |
| **插件/技能市场** | ❌ | ☆ | DEFAULT_SKILLS 硬编码，无版本号、无远程仓库、无订阅 |
| **多租户 RBAC** | `models/user.py` Org | ★★ | 仅 Org 隔离，**无项目级 / 工作区级 RBAC**，IM user 未映射 |

---

## 2. 9 大平台核心能力速记（最佳资源抽取）

### 2.1 Coze Studio（字节跳动）⭐ 20.6k
**最佳可抄资源**：
- **Eino 框架**（Cloudwego/Eino, Go）—— 把 agent runtime / 工作流 / 模型抽象 / 知识库索引做成可独立替换的引擎，**值得借鉴架构边界划分**
- **Coze Loop**——独立的 AgentOps 子系统：prompt 测试、多模型对比、自动评测、E2E 监控（**正是 agent-hub 缺的 Eval 模块**）
- **Plugin 统一系统**：插件 = 第三方 API + Schema + Auth 模板，发布到市场
- **资源管理 DDD 划分**：Plugin / KnowledgeBase / Database / Prompt 四类资源 + 工作区级隔离
- **Chat SDK**：把 agent 嵌到任意业务系统的 Web SDK
- **架构亮点**：Hertz HTTP + DDD 微服务 + MySQL/Redis/MinIO/Milvus

### 2.2 Dify ⭐ 138.7k（最成熟的开源 LLMOps）
**最佳可抄资源**：
- **Workflow 节点全集**：Iteration / **Loop（v1.2.0 新增）** / Variable Aggregator / Code（Py+JS）/ HTTP / Conversation Variables / List Operator / Parameter Extractor / Question Classifier
- **Agent Strategy 插件化**：Function Calling / ReAct 是可装可换的策略插件，CoT/ToT/GoT 都能扩展（**这是 agent-hub 现在硬编码 ReAct 的解药**）
- **Plugin Marketplace**（`langgenius/dify-official-plugins`）：模型 / 工具 / Agent Strategy / 扩展四类 - 可直接对照建设
- **Draft/Publish 双轨**：工作流先存草稿、灰度后发布，保留版本历史
- **LLMOps 三件套**：trace + usage + user feedback 反馈到 prompt
- **RAG Pipeline 节点**：把检索做成工作流的一类节点（hybrid + rerank + score 阈值）

### 2.3 FastGPT ⭐ 27.8k（知识库王者）
**最佳可抄资源**：
- **多种切片策略**：QA 模式（自动生成问答对索引）/ 直接索引 / 父子索引 / 自定义分隔符
- **混合检索 + Rerank** 三段：BM25 + Vector + Cohere/BGE Rerank
- **文件预处理流水线**：CSV/PDF/Word/PPT/HTML/Markdown 全格式 + 图片表格 LaTeX 保留
- **知识库分享 token**：对外发布带 token 的 RAG API（Embed / Iframe / 微信 H5）
- **OneAPI 集成**：一个接口聚合 200+ 模型
- **应用模板库**：HR/Legal/客服/对外 H5 直接套用

### 2.4 LangFlow ⭐ 147.2k（节点画布生态）
**最佳可抄资源**：
- **Component-as-Code**：每个节点 = 一个 Python class，写完即可作为节点出现在画布
- **Custom Component IDE**：浏览器内直接写 Python 节点，热加载
- **Tweaks / Run Flow API**：把整个 flow 当 API 暴露，用 `tweaks={}` 覆盖任意节点参数
- **Embedded Chat Widget**：iframe / Web Component
- **与 LangChain / LangGraph / CrewAI 的双向适配器**

### 2.5 n8n ⭐ 185k（自动化集成王）
**最佳可抄资源**：
- **400+ 集成节点目录**（Notion/Slack/Salesforce/HubSpot/Airtable…）—— 直接抄 Trigger 列表
- **Queue Mode + Bull/Redis Worker**：横向扩 Worker，队列调度（agent-hub 的 task_scheduler 可升级到这套）
- **Sub-workflow + Workflow-as-Tool**：一个 workflow 可作为另一个 workflow 的工具节点（**多 agent 协作的解法**）
- **Form Trigger / Webhook Trigger / Cron Trigger / Database Change Trigger**
- **Credentials 中心化加密**：用户级 / 工作区级密钥隔离 + AES 加密
- **AI Starter Templates**：开箱即用模板库

### 2.6 RAGFlow ⭐ 78.7k（深度文档理解之王）
**最佳可抄资源**：
- **DeepDoc 解析器**：DLA（版面分析）+ OCR + TSR（表格结构识别）+ 表格自动旋转 + VLM 接入图片理解
- **RAPTOR 树状索引**：递归聚类摘要 → 树根（语义） + 树叶（细节），多跳问答专用
- **Knowledge Graph**：实体抽取 + 关系 + 社区报告（GraphRAG 风）
- **引用回溯 + 高亮**：答案逐句对应到源 PDF 像素位置
- **专业模板**：法律 / 论文 / 简历 / 手册 / 书籍各自独立解析模板
- **Multi-Agent Deep Research**（v0.20.0）：deep research agent 默认带

### 2.7 AnythingLLM ⭐ 58.7k（本地化 RAG + Agent Skills）
**最佳可抄资源**：
- **Workspace 隔离架构**：每个 workspace = 独立 RAG + 独立模型 + 独立 prompt（**比 agent-hub 当前 "全局 agent" 更细粒度**）
- **Agent Skill Plugin 系统**：JS `handler.js` + `plugin.json` 即可写自定义技能
- **Community Hub**：技能 / Workflow / Item 跨用户分享
- **Agent Flows 可视化画布**
- **Embed Widget / iframe + 白标**
- **多向量库适配**：LanceDB / Pinecone / Chroma / Weaviate / Qdrant / Milvus
- **Desktop App**（Electron）+ Docker 双发布模式
- **Simple SSO + 三角色 RBAC**（Admin / Manager / Default）

### 2.8 Anthropic Skills + Karpathy 教学资源 ⭐ 121k
**最佳可抄资源**：
- **Skill = 文件夹 + SKILL.md（YAML frontmatter + 描述 + 触发条件）+ 子脚本 + 资源**（agent-hub 已部分采用，需对齐 Anthropic 最新规范）
- **Skill Discovery 机制**：description 字段会被 LLM 用来"自主决定何时加载"
- **Bundled Resources**：脚本 / 模板 / reference docs 跟 SKILL.md 一起打包
- **Karpathy nanochat / llm.c**：教学级 LLM 全栈实现（不是平台，但**可以做成 agent-hub 的"AI 教育"垂直 agent 模板**）
- **PowerPoint / Spreadsheet 等 Anthropic 官方技能**（已内置在 Codex 默认环境）

### 2.9 Firecrawl ⭐ 111.5k（LLM-Ready Web 抓取）
**最佳可抄资源**：
- **5 个 API**：scrape / crawl / map（站点地图）/ search / extract（结构化抽取，支持 JSON Schema）
- **LLM-Optimized Markdown 输出**：比原始 HTML 少 67% token
- **Fire-PDF 引擎**（Rust，2026-04 新发布）：复杂版面 / 表格 / 公式
- **Deep Research Template**（Firesearch / Open Researcher）
- **JS / SPA 渲染默认开启**
- **可自托管**（Docker），SDK 全：Python / Node / Go / Rust + LangChain / LlamaIndex 适配
- **Browser Action API**：自然语言 + Playwright 双输入

---

## 3. 能力对比大矩阵（agent-hub vs 9 平台）

> ✅✅ = 强 / ✅ = 有 / 🟡 = 雏形 / ❌ = 无 / — = 不适用

| 能力维度 | agent-hub | Coze | Dify | FastGPT | LangFlow | n8n | RAGFlow | AnythingLLM | Skills | Firecrawl |
|---------|----------|------|------|---------|----------|-----|---------|-------------|--------|-----------|
| **可视化工作流画布** | 🟡（前端有，后端不执行） | ✅✅ | ✅✅ | ✅✅ | ✅✅ | ✅✅ | ✅ | ✅ | — | — |
| **节点种类数** | <5 | 30+ | 40+ | 25+ | 200+ | 400+ | 15+ | 20+ | — | — |
| **Iteration / Loop 节点** | ❌ | ✅ | ✅✅ | ✅ | ✅ | ✅ | — | ✅ | — | — |
| **Code 节点（Py/JS）** | ❌ | ✅ | ✅✅ | ✅ | ✅✅ | ✅✅ | — | ✅ | — | — |
| **HTTP / Webhook Trigger** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅✅ | ✅ | ✅ | — | — |
| **Cron / 定时 Trigger** | 🟡（有 scheduler 未串） | ✅ | ✅ | ✅ | ✅ | ✅✅ | ❌ | ❌ | — | — |
| **知识库 RAG 引擎** | ❌ | ✅✅ | ✅✅ | ✅✅✅ | ✅ | ✅ | ✅✅✅ | ✅✅ | — | — |
| **深度文档解析（PDF/表格/OCR）** | ❌ | ✅ | ✅ | ✅✅ | ❌ | ❌ | ✅✅✅ | ✅ | — | ✅ |
| **混合检索 + Rerank** | ❌ | ✅ | ✅ | ✅✅ | ❌ | — | ✅✅ | ✅ | — | — |
| **Knowledge Graph / RAPTOR** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅✅✅ | ❌ | — | — |
| **引用回溯 / 答案溯源** | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅✅✅ | ✅ | — | — |
| **多向量库适配** | 🟡（仅 pgvector） | ✅ | ✅✅ | ✅ | ✅ | ✅ | ✅ | ✅✅✅ | — | — |
| **Plugin / Tool 市场** | ❌ | ✅✅ | ✅✅ | ✅ | ✅ | ✅✅ | 🟡 | ✅ | ✅ | — |
| **MCP 客户端** | ✅（仅 tools） | 🟡 | ✅ | 🟡 | ✅ | 🟡 | ❌ | ✅ | — | — |
| **MCP 服务端（暴露自家工具）** | ❌ | ❌ | 🟡 | ❌ | 🟡 | ❌ | ❌ | ❌ | — | ❌ |
| **浏览器自动化（Playwright agent）** | 🟡（soft-import 5 工具） | ❌ | 🟡 | ❌ | ❌ | 🟡 | ❌ | ✅ | — | ✅✅ |
| **Web 抓取 / Crawl** | 🟡（仅 DDG search） | ❌ | 🟡 | ❌ | ❌ | ✅ | ❌ | ✅ | — | ✅✅✅ |
| **结构化 JSON 抽取** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | — | ✅✅✅ |
| **Container 沙箱** | 🟡（可选 Docker） | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | — | — |
| **Agent 多角色协作 / delegate** | 🟡（5 角色串行） | ✅ | ✅ | ❌ | ✅（CrewAI 适配） | 🟡（sub-workflow） | ✅✅ | ✅ | — | — |
| **多 agent 辩论 / 投票** | ❌ | ❌ | 🟡 | ❌ | ✅ | ❌ | ✅ | ❌ | — | — |
| **Plan/Act 双模** | ✅✅ | ❌ | ❌ | ❌ | ❌ | ❌ | 🟡 | ❌ | — | — |
| **长任务 Checkpoint** | 🟡（pipeline_checkpoint 部分） | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | — | — |
| **Workspace / 工作区隔离** | 🟡（仅 Org） | ✅✅ | ✅✅ | ✅ | ✅ | ✅ | ✅ | ✅✅✅ | — | — |
| **多租户 RBAC** | 🟡（仅 admin） | ✅✅ | ✅✅ | ✅✅ | ✅ | ✅✅ | ✅ | ✅✅ | — | — |
| **SSO / SAML** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅✅ | ❌ | ✅ | — | — |
| **Eval / 自动评测** | 🟡（骨架） | ✅✅（Coze Loop） | ✅ | 🟡 | ✅ | 🟡 | ✅ | ❌ | — | — |
| **Prompt 版本 / Draft-Publish** | ❌ | ✅ | ✅✅ | ✅ | 🟡 | ✅ | ❌ | ❌ | — | — |
| **可观测：trace + token** | ✅ | ✅✅ | ✅✅ | ✅ | ✅ | ✅ | ✅ | 🟡 | — | — |
| **失败 RCA / 自动归因** | ❌ | ❌ | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ | — | — |
| **Cost Governor / 预算熔断** | 🟡 | ✅ | ✅✅ | ✅ | ❌ | 🟡 | ❌ | ❌ | — | — |
| **应用模板库** | 🟡（DAG 模板 3 个） | ✅✅✅ | ✅✅✅ | ✅✅ | ✅✅ | ✅✅✅ | ✅ | ✅ | ✅ | — |
| **嵌入 Chat Widget / Iframe** | ❌ | ✅✅ | ✅ | ✅✅ | ✅ | ❌ | ✅ | ✅✅ | — | — |
| **公网分享 / 一键发布 H5** | ❌ | ✅✅ | ✅ | ✅✅ | ❌ | ❌ | ✅ | ✅ | — | — |
| **多语言界面** | ❌（仅中文） | ✅✅ | ✅✅✅ | ✅ | ✅ | ✅✅✅ | ✅ | ✅ | — | — |
| **桌面 App** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅✅ | — | — |
| **多渠道 IM 入口（飞书/QQ/iOS）** | ✅✅✅ | 🟡 | ❌ | 🟡 | ❌ | ✅（间接） | ❌ | ❌ | — | — |
| **真部署到生产（Vercel/CF/小程序/AppStore）** | ✅✅✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — | — |
| **14 角色业务 Agent（CEO/产品/QA…）** | ✅✅✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — | — |

---

## 4. agent-hub 缺陷盘点（按"市场上现成、你没有"排序）

### 🔴 P0 — 没有就接不上行业生态

#### P0-1 没有知识库 / RAG 系统（**所有平台都有，你独缺**）
- **现状**：`backend/app/models` 里没有 `KnowledgeBase` / `Document` / `Chunk` 实体；`memory.py` 的 TaskMemory 是任务级记忆，**不是文档级 RAG**
- **缺什么**：
  - KB CRUD + 文档上传 / 解析 / 切片 / 向量化流水线
  - 多分段策略：固定长度 / 父子 / QA 模式 / 标题感知
  - 混合检索：BM25 + Vector + Rerank
  - 引用回溯（FastGPT/RAGFlow 标配）
  - 多 KB 复用 + 混合检索
- **能抄的**：FastGPT 整套 KB 引擎 + RAGFlow 的 DeepDoc 解析器（Apache 2.0）

#### P0-2 没有节点执行引擎（前端画布是"画给人看的"）
- **现状**：`views/WorkflowBuilder.vue` + Vue Flow 画布存在，`api/workflows.py` **只是 doc 存档**，没有把 doc 转成可执行的 graph runtime
- **缺什么**：
  - Node 类型注册表：LLM / HTTP / Code(Python+JS) / Iteration / Loop / Condition / Variable Aggregator / Parameter Extractor / Question Classifier
  - 变量系统：节点输出 → 后续节点输入的引用语法（`{{node.x.output}}`）
  - 草稿 / 发布双轨 + 版本历史
  - Run Flow API（一键把 flow 当 HTTP API）
- **能抄的**：Dify workflow runtime（最成熟）+ LangFlow 的 Component-as-Code

#### P0-3 没有插件 / 技能市场化体系
- **现状**：`skills/public/*` 是 15 个文件夹 markdown，DEFAULT_SKILLS **硬编码**，无版本号 / 无依赖 / 无远程仓库 / 无订阅
- **缺什么**：
  - Skill manifest（version / dependencies / permissions / pricing）
  - Skill registry server（中央仓库 + 检索）
  - 一键安装 / 升级 / 卸载
  - 用户 / 团队可发布
  - 评分 + 下载量
- **能抄的**：AnythingLLM Community Hub + Dify Marketplace + Anthropic Skills 规范

#### P0-4 没有 Web 深度抓取能力
- **现状**：只有 `tools/web_search.py`（DuckDuckGo）+ `browser_tool.py`（Playwright soft-import，未默认装），**没有整站 crawl、没有 sitemap map、没有结构化 extract**
- **缺什么**：crawl / map / extract / deep research 4 个 Firecrawl-style API
- **能抄的**：Firecrawl 自托管（MIT，Docker 一键起）

#### P0-5 没有 Eval 闭环
- **现状**：`eval_runner.py` 246 行骨架，**没有标准测试集、没有 nightly run、没有版本对比**
- **缺什么**：
  - 任务测试集（30 个固定 task 的 nightly run）
  - 多版本 / 多模型对比
  - 回归告警（今日比昨日掉了 X%）
  - 用户 feedback → trace → 自动入库做 eval set
- **能抄的**：Coze Loop（独立子项目，开源）

### 🟠 P1 — 影响生产可用性

#### P1-1 多租户 RBAC 残缺
- **现状**：仅 Org 级隔离 + admin/user 两角色；**IM user 没映射到 users 表**；**没有 workspace / 项目级权限**
- **缺**：Workspace 模型 + 三级 RBAC（Admin/Manager/Default）+ SSO（OIDC/SAML）+ Credentials 加密中心
- **能抄的**：n8n + AnythingLLM 的 RBAC 设计

#### P1-2 Workflow 节点种类太少
- agent-hub 当前节点 < 5；Dify 40+，n8n 400+
- **必须先补的 10 个节点**：Iteration / Loop / Condition / Code(Py) / HTTP / Variable Aggregator / Parameter Extractor / Question Classifier / Form / Tool

#### P1-3 模板 / 应用市场缺失
- 当前只有 3 个 DAG 模板（web_app / api_service / data_pipeline）
- Dify 有数十个开箱模板，n8n 有 1000+ 社区模板
- **能抄的**：Dify Explore / n8n templates 目录结构

#### P1-4 多 agent 协作 = 流水线 ≠ 团队
- 5 个角色串行 + 一次性 peer-review
- 无 agent-to-agent delegate / debate / vote
- **能抄的**：CrewAI / AutoGen 的 group chat + LangGraph state machine

#### P1-5 Cost Governor 不够狠
- 有限额，**无超额自动降级模型 / 无熔断 / 无每用户预算**
- IM 接进来一个恶意用户能烧光预算
- **能抄的**：Dify 的 LLM usage + budget 系统

#### P1-6 Embed Widget / 公网分享缺失
- 没有 iframe / Web Component / 公网 share token
- 用户做完 agent 没法给客户用
- **能抄的**：FastGPT Share / AnythingLLM Embed

#### P1-7 多语言 i18n 缺失
- 前端仅中文；Dify/n8n/Coze 都是 i18n 标配（en/zh/ja/de…）
- 影响海外推广

#### P1-8 失败 RCA / 自动归因
- trace 有，但没人翻
- 用户看到 "failed: build error" 只能懵圈
- **能抄的**：trace → 喂给 LLM → 自动出 root cause + 修复建议

### 🟡 P2 — 工程化短板

#### P2-1 节点画布前后端断层
- 前端 Vue Flow + builder/* 组件齐全
- 后端 `api/workflows.py` 只存 doc
- **必须做的**：DSL → Runtime 编译器

#### P2-2 Browser 工具未默认安装
- soft-import，使用前需手动装 Playwright
- 应内置到 Docker image / 提供一键 install 命令

#### P2-3 Codebase 索引未对接到知识库
- `codebase_indexer.py` 已有 tree-sitter / embedding，但没暴露成 RAG 来源
- Aider 的 repo map 应该是默认能力

#### P2-4 没有桌面 App
- AnythingLLM Electron 桌面版下载量是 Docker 版的 3 倍
- 个人用户根本不愿意装 Docker

#### P2-5 测试覆盖率不明
- backend/tests 有，但没有 coverage 报告
- 改一处不知道动了什么

#### P2-6 Skill 不符合 Anthropic 最新规范
- Anthropic Skills 规范要求：description 自动触发 + bundled scripts + reference docs
- 当前 skills/public/ 只有 SKILL.md，没把脚本 / 资源同包

### 🔵 P3 — 安全 / 合规

#### P3-1 Prompt Injection 防御薄
- `services/safety/prompt_sanitizer.py` 存在，但只过滤外部内容，**没有输出验证**
- 搜索 / 网页内容直接喂 LLM 风险大

#### P3-2 审计日志可被覆盖
- trace 在 PG 但可改可删
- 合规需要：append-only + 哈希链 + 导出

#### P3-3 Secrets 管理无中心化
- API key 散落在 .env 和 model_provider 表
- 缺：Credentials Vault（参考 n8n / HashiCorp Vault）

#### P3-4 SSE 多 worker 安全
- Redis Pub/Sub OK，但**没有断线重连退避策略**

---

## 5. 比较矩阵：9 个平台**有**而 agent-hub **完全没有**的能力（按平台维度）

| 平台 | agent-hub 完全没有的能力清单 |
|------|----------------------------|
| **Coze Studio** | Coze Loop（AgentOps）/ Eino 引擎 / Plugin 市场 / Resource 4 类 DDD 划分 / Chat SDK 嵌入 |
| **Dify** | 40+ 节点 workflow 引擎 / Loop+Iteration 节点 / Variable Aggregator / Parameter Extractor / Question Classifier / Agent Strategy 插件化 / Plugin Marketplace / Draft-Publish 双轨 / Conversation Variables / RAG Pipeline 节点 |
| **FastGPT** | 完整知识库 RAG / 多分段策略（QA 模式）/ 文件预处理流水线（PDF/PPT/Word）/ 混合检索 + Rerank / 知识库分享 token / OneAPI 200+ 模型 / 应用模板库 |
| **LangFlow** | Component-as-Code（写 Python 即组件）/ 浏览器内 IDE / Tweaks 覆盖 / Run Flow API / CrewAI/LangGraph 双向适配 |
| **n8n** | 400+ 集成节点 / Queue Mode + Worker 集群 / Sub-workflow as Tool / Form Trigger / 中心化 Credentials Vault / 1000+ 社区模板 |
| **RAGFlow** | DeepDoc 文档解析（DLA+OCR+TSR+表格旋转）/ RAPTOR 树状索引 / Knowledge Graph + 实体抽取 / 引用回溯 + PDF 像素高亮 / 法律论文简历专业模板 / Multi-Agent Deep Research |
| **AnythingLLM** | Workspace 隔离架构 / Skill 社区 Hub / 多向量库适配（7 种）/ Embed Widget + 白标 / Desktop App / Simple SSO / 三角色 RBAC |
| **Anthropic Skills + Karpathy** | Skill 自动触发机制（description 驱动）/ Bundled Resources / PowerPoint+Spreadsheet 等 Anthropic 官方技能 / nanochat 教学路径包装成"AI 教育 agent" |
| **Firecrawl** | scrape/crawl/map/search/extract 5 API / Fire-PDF Rust 引擎 / LLM-optimized Markdown / Deep Research Template / Browser Action API |

---

## 6. agent-hub 反过来 —— 9 平台都没有的能力（你的护城河）

| 你独有 | 对标平台 | 价值 |
|--------|---------|------|
| **iOS 快捷指令 / 飞书 / QQ / OpenClaw 多 IM 入口 + Plan/Act 闭环** | 0/9 有 | 用户从手机一句话发需求到 AI 出方案 |
| **14 角色 SDLC 业务 Agent（CEO/产品/前后端/QA/法务/SRE…）** | 0/9 有 | 真"AI 团队"，不是单 agent |
| **真部署到生产（Vercel/Cloudflare/微信小程序/AppStore/GooglePlay）** | 0/9 有 | 端到端"需求 → 上线"，对标 Devin/v0 |
| **6 层 Pipeline + DAG 双轨编排** | 0/9 有 | self-verify + guardrails 内嵌产线 |
| **Plan/Act + 最终验收闸门 + autoFinalAccept** | 0/9 有 | 翻车成本控制 |
| **Claude Code CLI 主路径 + auto-fix×3** | 0/9 有 | 比纯 LLM 拼接稳很多 |

---

## 7. 战略建议（不要做"另一个 Dify"）

### 选错方向的代价
如果跟 Dify/Coze 比"通用 agent 平台"，你输；
如果跟 RAGFlow/FastGPT 比"知识库"，你输得更惨；
如果跟 n8n 比"集成节点数"，你被秒杀。

### 正确的战略 — "AI 团队 OS" 三层架构

```
                ┌─────────────────────────────────────────┐
                │  L3 业务层（你的护城河）                │
                │  - 14 角色 SDLC                         │
                │  - 多渠道 IM 入口 + Plan/Act            │
                │  - 真部署到生产                          │
                │  - 飞书 / QQ / iOS Shortcut             │
                └─────────────────────────────────────────┘
                              ▲
                ┌─────────────────────────────────────────┐
                │  L2 编排层（要补齐）                    │
                │  - 节点执行引擎（抄 Dify）              │
                │  - Eval / Cost / RBAC（抄 Coze Loop）   │
                │  - Skill / Plugin Market（抄 AnythingLLM Hub）│
                └─────────────────────────────────────────┘
                              ▲
                ┌─────────────────────────────────────────┐
                │  L1 能力层（直接吸 OSS）                │
                │  - RAG: 嵌 FastGPT or RAGFlow           │
                │  - Web: 嵌 Firecrawl                    │
                │  - Skills: 同步 Anthropic Skills        │
                │  - MCP: 已有 client，加 server          │
                └─────────────────────────────────────────┘
```

### 90 天 Top 5 必做
1. **嵌 Firecrawl 自托管**（Docker compose 加一个 service）→ 解锁所有 web 任务（**1 周**）
2. **集成 RAGFlow 或 FastGPT 作为 KB 后端**（用它们的 API，不重写）→ 解锁知识库（**2 周**）
3. **节点执行引擎 v1**（10 个节点：LLM/HTTP/Code/Iteration/Loop/Condition/Variable/Form/Tool/RAG）→ 让前端画布真能跑（**3 周**）
4. **Skill Marketplace v1**（manifest + version + remote registry + install/update）→ 形成飞轮（**2 周**）
5. **Eval Suite v1**（30 个固定任务 nightly run + dashboard）→ 改 prompt 不再赌博（**2 周**）

### 同步必做的工程化
- 多语言 i18n（前端 vue-i18n）
- Workspace 模型 + 三角色 RBAC
- IM user → users 映射
- Cost Governor 加超额自动降级

---

## 8. 抄哪些代码（最后一张资源表）

| 你需要的能力 | 直接抄的项目 + 路径 | License |
|------------|-------------------|---------|
| 知识库 RAG 全栈 | `labring/FastGPT` 的 `packages/service/core/dataset/*` | Apache 2.0 |
| 深度文档解析 | `infiniflow/ragflow` 的 `deepdoc/` | Apache 2.0 |
| Workflow 节点执行引擎 | `langgenius/dify` 的 `api/core/workflow/nodes/*` | 企业版限制，社区版可参考 |
| Plugin / Marketplace | `langgenius/dify-official-plugins` 仓库结构 | Apache 2.0 |
| Component-as-Code | `langflow-ai/langflow` 的 `src/backend/base/langflow/components/*` | MIT |
| AgentOps / Eval | `coze-dev/coze-loop`（独立项目） | Apache 2.0 |
| Eino 框架 | `cloudwego/eino` | Apache 2.0 |
| Web 抓取 | `mendableai/firecrawl` 自托管 | MIT |
| Workspace + Skill Hub | `Mintplex-Labs/anything-llm` 的 `server/utils/agents/skills/*` | MIT |
| 集成节点目录 | `n8n-io/n8n` 的 `packages/nodes-base/nodes/*`（结构参考） | Sustainable Use License |
| Skill 规范 | `anthropics/skills` README + 示例 SKILL.md | MIT |
| MCP 协议（已用）| `modelcontextprotocol/specification` | MIT |

---

## 9. 一句话收尾

> **"你已经把'AI 团队工厂'做到了 70 分，但还缺一个'AI 团队的工具室'。" **
>
> 把 9 个平台**当组件**而不是**当对手**：FastGPT/RAGFlow 给你 KB，Firecrawl 给你眼睛，Coze Loop 给你考场，AnythingLLM 给你工坊，Dify 给你画板，n8n 给你水管 —— 而**你**给所有人一个能"派活到飞书 → 跑产线 → 部署上线"的 AI 团队闭环。
>
> 这不是抄谁，是站在 9 个巨人肩上，去做唯一一件**他们没有做的事**。
