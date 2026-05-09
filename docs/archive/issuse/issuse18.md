# Issue 18｜agent-hub 产品路线图：吸收九大平台优势，补齐核心短板

> 目标：把 `agent-hub` 从“已具备大量能力的 AI 交付平台雏形”，升级成一个真正可对外宣称、可持续演进的 **AI Team OS / AI Delivery OS**
>
> 对标来源：Coze Studio · Dify · FastGPT · LangFlow · n8n · RAGFlow · AnythingLLM · Anthropic/Karpathy Skills · Firecrawl
>
> 产出日期：2026-04-22

---

## 0. TL;DR

### 当前定位
`agent-hub` 最强的不是“聊天”，也不是“低代码”，而是：

`需求入口 -> 澄清 -> 计划 -> 多角色执行 -> 外部系统回流 -> 部署 -> 验收`

这条 AI 交付闭环。

### 当前最大问题
不是“没有能力”，而是以下 4 层还没做成第一等产品能力：

1. **知识库 / RAG**
2. **工作流治理**
3. **集成 / 插件生态**
4. **企业治理与交付体验**

### 战略建议
不要做“另一个 Dify”或“另一个 n8n”。

应该做：

**以 AI 交付链路为核心的 agent 平台**，
然后把市场上的最佳能力吸进来：

- `RAGFlow / FastGPT` 提供知识库能力
- `Dify / LangFlow` 提供 workflow runtime 设计参考
- `n8n` 提供集成与治理标杆
- `Firecrawl` 提供 web data 能力层
- `Anthropic Skills` 提供 skill 规范

---

## 1. agent-hub 已有的真正优势

这些不是空想，而是你仓库里已经能看到的能力：

- **可视化 Workflow Builder**
  - `src/views/WorkflowBuilder.vue`
  - 已有 DAG 画布、保存、加载、运行、SSE 状态更新

- **后端 pipeline + DAG 执行骨架**
  - `backend/app/services/pipeline_engine.py`
  - `backend/app/services/dag_orchestrator.py`

- **Plan/Act 双模**
  - `backend/app/api/gateway.py`
  - `backend/app/api/plans.py`
  - 这是你很少见、也很有辨识度的产品能力

- **OpenAI 兼容桥接**
  - `backend/app/api/openai_compat.py`
  - 可把外部“模型调用”桥成内部 agent-hub 任务执行

- **多渠道入口**
  - 飞书 / QQ / Slack / OpenClaw / 快捷指令 方向已存在

- **技能 / MCP / Eval / Observability 基础骨架**
  - 都已经不是从 0 开始

一句话总结：

> `agent-hub` 的强项是“把任务做完”，不是“把节点画出来”。

---

## 2. 现在最明显的不足

### 2.1 安全与对外可信度不足

- `README.md` 当前仍带有敏感信息和早期描述
- 文档和真实产品能力脱节
- 对外第一印象会严重拉低平台可信度

这件事优先级是 **P0**。

---

### 2.2 Workflow 还是“可视化存档”，不是成熟产品

当前 `backend/app/api/workflows.py` 做的是：

- 列表
- 创建
- 更新
- 删除
- 保存 doc

缺的是：

- draft / publish
- version history
- diff
- rollback
- review / approval
- workflow-as-api
- environment promotion

也就是说，现在 workflow 更像“画布存档”，还不是“工作流资产系统”。

---

### 2.3 RAG / KB 还不是平台主能力

你现在有 memory，但这和真正的知识库平台不是一回事。

缺失的关键项包括：

- Knowledge Base 实体
- Document / Chunk / Embedding 管线
- 多文件格式解析
- chunk 策略
- hybrid retrieval
- rerank
- citation UI
- 数据源接入

这一块和 `RAGFlow`、`FastGPT`、`Dify` 比，差距是结构性的。

---

### 2.4 集成生态太薄

当前能看到的集成能力更像“精选接口 + 消息通知 + issue 同步”，
还不是成熟平台那种：

- OAuth 连接器目录
- 统一 credentials 中心
- 连接测试 / 生命周期管理
- 大量 SaaS 节点
- trigger 丰富度

这方面和 `n8n`、`Coze` 差距最大。

---

### 2.5 企业治理与协作能力偏弱

缺少或不够清晰的部分：

- SSO / SAML / OIDC
- 细粒度 RBAC
- workspace / project 级隔离
- 密钥治理
- workflow 审批与发布权限
- 审计深度
- 多环境治理

---

## 3. 各平台最值得借鉴的“最佳资源”

### Coze Studio
最值得借鉴：

- 资源模型：`agent / app / workflow / plugin / knowledge / database`
- 插件体系与平台化资源组织方式

适合借鉴到：

- `src/views/*` 信息架构
- `backend/app/api/*` 资源划分

---

### Dify
最值得借鉴：

- 生产级 agentic workflow
- draft / publish / observability 一体化
- RAG 与 workflow 的天然融合

适合借鉴到：

- workflow runtime
- workflow 版本治理
- eval / trace / usage 闭环

---

### FastGPT
最值得借鉴：

- 知识库产品化
- chunk 策略
- 混合检索 + rerank

适合借鉴到：

- 新的 KB 数据模型
- ingestion pipeline

---

### LangFlow
最值得借鉴：

- component-as-code
- 节点心智模型清晰
- builder UX 轻量

适合借鉴到：

- workflow 节点注册机制
- builder 节点扩展模型

---

### n8n
最值得借鉴：

- 集成目录
- credentials 中心
- workflow 版本和治理
- 人工审批 / 企业控制

适合借鉴到：

- integrations
- workflow lifecycle
- RBAC / 审批 / 审计

---

### RAGFlow
最值得借鉴：

- 深度文档解析
- 引用回溯
- 企业级 RAG ingestion

适合借鉴到：

- KB 文档处理层
- citation 与 evidence 展示

---

### AnythingLLM
最值得借鉴：

- 本地优先与低门槛部署
- workspace 隔离
- 多模型 / 多向量库开箱即用

适合借鉴到：

- 新用户上手体验
- workspace 设计

---

### Anthropic / Karpathy Skills
最值得借鉴：

- skill 的结构化规范
- skill 发现与装载逻辑
- 更严格的 agent 执行约束

适合借鉴到：

- `skills/`
- skill manifest
- 运行前约束与质量规范

---

### Firecrawl
最值得借鉴：

- search / scrape / crawl / map / agent 五件套
- MCP / skill / API 三位一体分发

适合借鉴到：

- web data layer
- deep research 能力

---

## 4. 目前市场上常见、但 agent-hub 还不具备的能力

下面这部分是“别人有、你现在没有或没有做成熟”的核心清单。

### A. 工作流资产治理
- draft / publish 双轨
- workflow version history
- diff
- rollback
- workflow review / approval
- environment promotion
- workflow-as-tool / workflow-as-api

### B. 知识库 / RAG 产品层
- KB CRUD
- 文档上传 / 解析 / 切片 / 向量化
- hybrid retrieval
- rerank
- citation
- 多数据源同步
- 深度 PDF / OCR / 表格处理

### C. 集成生态
- 大量 SaaS 连接器
- OAuth 连接器配置
- credentials 中心
- trigger 丰富度
- template marketplace

### D. 企业能力
- SSO / LDAP / SAML
- workspace / project 级 RBAC
- 审计深度
- secret governance
- 多环境治理

### E. 交付体验
- embed widget
- 对外分享页
- 白标入口
- 桌面化或极简本地部署体验

### F. Web 数据基础设施
- crawl
- sitemap map
- structured extract
- JS-heavy 网站抓取
- deep research data gathering

---

## 5. 推荐路线图

分三期做，不建议同时铺太大。

---

## 5.1 P0：先把平台变得“可信、能卖、能继续长”

### P0-1 清理 README 和敏感信息

目标：

- 删除明文密钥、默认账号等风险信息
- 重写根 `README.md`
- 让 README 与当前架构一致

涉及文件：

- `README.md`
- `CLAUDE.md`
- `backend/CLAUDE.md`

完成标准：

- 对外 README 能准确描述平台
- 不再暴露敏感配置
- 新用户能知道项目真正卖点

---

### P0-2 Workflow 从 CRUD 升级到版本治理

目标：

- 给 `workflow` 增加版本和发布概念

建议新增：

- `WorkflowVersion`
- `status: draft | published | archived`
- `published_version_id`
- diff 能力

优先涉及文件：

- `backend/app/api/workflows.py`
- `backend/app/models/workflow.py`
- `src/services/workflowBuilder.ts`
- `src/views/WorkflowBuilder.vue`

完成标准：

- 能保存多个版本
- 能发布某个版本
- 能回滚到上一个版本
- UI 能看清当前是草稿还是已发布

---

### P0-3 定义 KB / RAG 数据模型

目标：

- 先把知识库实体建出来，不急着一步做到最强

建议新增模型：

- `KnowledgeBase`
- `KnowledgeDocument`
- `KnowledgeChunk`
- `KnowledgeSource`

建议新增 API：

- `/api/knowledge-bases`
- `/api/documents`
- `/api/retrieval`

涉及目录：

- `backend/app/models/`
- `backend/app/api/`
- `backend/app/services/`

完成标准：

- 可创建 KB
- 可上传文档
- 可切 chunk
- 可检索并返回引用片段

---

### P0-4 把 Skill 从“文件夹”升级到“可管理资源”

目标：

- 给 skill 增加 manifest / version / dependency / permission

建议结构：

- `SKILL.md`
- `skill.json` 或 frontmatter 扩展字段
- version
- permissions
- dependencies
- entrypoints

涉及目录：

- `skills/`
- `backend/app/services/skill_*`
- `backend/app/api/skills.py`

完成标准：

- skill 可被列出、安装、升级、禁用
- skill 元数据可以被 UI 读取

---

## 5.2 P1：把平台做成“真正好用”

### P1-1 补齐 workflow 节点体系

首批建议节点：

1. `LLM`
2. `HTTP`
3. `Condition`
4. `Loop`
5. `Code`
6. `Tool`
7. `Knowledge Retrieve`
8. `Template / Prompt`
9. `Form / Human Approval`
10. `Variable Aggregator`

涉及文件：

- `src/views/WorkflowBuilder.vue`
- `src/components/builder/*`
- `backend/app/services/dag_orchestrator.py`
- 新增 `backend/app/services/workflow_runtime.py`

完成标准：

- builder 画出来的 graph 能按节点类型执行
- 节点有统一 I/O 结构
- 支持变量引用

---

### P1-2 做集成中心与 credentials 中心

目标：

- 把零散 integrations 整成平台能力

建议先做的连接器：

- GitHub
- Jira
- Slack
- Notion
- Google Drive
- Confluence
- Webhook Trigger

涉及文件：

- `backend/app/api/integrations.py`
- `backend/app/services/connectors/*`
- 新增 credentials 相关 model / api

完成标准：

- 用户能在 UI 配置凭据
- 能测试连接
- workflow / pipeline 能复用连接器

---

### P1-3 做 KB ingestion 第一版

第一期建议支持：

- Markdown
- PDF
- DOCX
- HTML / URL

检索策略第一版建议：

- vector
- BM25
- hybrid

第二期再加：

- rerank
- OCR
- 表格
- 高级 citation

---

### P1-4 做 embed / share / external delivery

目标：

- 让 agent-hub 不只是内部用，也能交付给客户

建议能力：

- embed widget
- iframe page
- public share token
- published app endpoint

---

### P1-5 做 workspace / RBAC / SSO

最低可用建议：

- `workspace`
- `admin / manager / member`
- workspace scoped credentials
- workspace scoped workflows

再往上：

- OIDC / SAML
- 审计日志

---

## 5.3 P2：做出平台差异化和行业级竞争力

### P2-1 引入 Firecrawl 风格 Web Data Layer

建议 API：

- `/api/web/search`
- `/api/web/scrape`
- `/api/web/crawl`
- `/api/web/map`

用途：

- deep research
- competitor analysis
- 外部资料补充

---

### P2-2 引入 RAGFlow / FastGPT 级知识库增强

增强方向：

- chunk 策略
- rerank
- citation
- 多数据源同步
- OCR / 表格 / PDF 高级解析

---

### P2-3 模板市场与解决方案包

建议模板方向：

- 需求评审 -> 开发 -> 测试 -> 上线
- 客服知识助手
- 企业制度问答
- 竞品分析
- PRD to code delivery
- Deep research report

---

### P2-4 强化你的独有护城河

这部分不要被别的平台带偏，必须继续做厚：

- Plan/Act
- IM 多入口
- 外部 issue / 评论回流
- 部署与验收闭环
- 多角色交付链路

这才是 `agent-hub` 真正和 Dify / n8n / FastGPT 拉开差异的地方。

---

## 6. 建议的实施顺序

### 第一阶段（1~2 周）
- 清 README 与敏感信息
- workflow versioning
- skill manifest 第一版

### 第二阶段（2~4 周）
- KB 数据模型 + 文档 ingestion 第一版
- workflow runtime 第一版
- integrations / credentials 第一版

### 第三阶段（4~8 周）
- workspace + RBAC
- embed / share
- web data layer
- eval 自动化

---

## 7. 成功标准

当下面这些成立时，说明路线是对的：

### 产品层
- 用户能看懂平台定位
- 用户能画 workflow、发布版本、回滚版本
- 用户能挂知识库并拿到引用答案
- 用户能把 agent 或 workflow 嵌给别人用

### 平台层
- skill 不再是纯文件，而是可管理资源
- workflow 不再是 doc，而是可治理资产
- integration 不再是零散接口，而是连接器系统
- memory 不再替代 KB，KB 成为正式子系统

### 战略层
- 对外讲法不再是“我们也有工作流”
- 而是：
  - 我们有 **AI 交付闭环**
  - 我们有 **可治理的 workflow**
  - 我们有 **知识库与工具生态**
  - 我们能从“需求”一直走到“上线”和“验收”

---

## 8. 最终结论

`agent-hub` 不缺想法，也不缺骨架。

真正缺的是：

- 把已有能力产品化
- 把缺失的基础设施补齐
- 把平台定位收敛清楚

最优路线不是全面模仿别的平台，而是：

> 保住自己在 AI 交付链路上的优势，
> 再系统吸收 Coze / Dify / FastGPT / LangFlow / n8n / RAGFlow / AnythingLLM / Firecrawl / Skills 的最佳资源。

一句话：

**不是做“另一个平台”，而是做“把这些平台最强能力组织进 AI 交付闭环”的平台。**
