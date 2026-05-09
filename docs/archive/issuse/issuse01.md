# Agent Hub 项目深度分析报告

## 一、 项目当前存在的问题与弊端

### 1. 架构层面的 "名不副实" 问题
多个核心模块的文档/注释声称的能力与实际实现存在显著差距：

| 模块 | 声称的能力 | 实际情况 | 完成度 |
| :--- | :--- | :--- | :--- |
| `memory.py` | pgvector 语义向量检索 + 三层记忆 | 仅有 ILIKE 关键字搜索，无 embedding 生成，无向量列使用 | ~40% |
| `self_verify.py` | LLM 驱动的质量验证 | 仅启发式规则（长度、关键字、截断检测），无任何 LLM 调用 | ~45% |
| `executor_bridge.py` | "Jobs persisted in DB" | `_running_jobs` 完全在内存中，重启即丢 | ~55% |
| `observability.py` | OpenTelemetry 级别的追踪 | 进程内字典 `_traces`/`_active_spans`，跨 worker 不共享 | ~50% |
| `guardrails.py` | 生产级审批与审计 | `_pending_approvals`/`_audit_log` 内存存储，重启清空 | ~35% |
| `collaboration.py` | 多智能体协作框架 | 纯内存状态机，未与 pipeline/lead_agent 集成 | ~25% |

### 2. 多 Worker 状态不一致（严重）
`backend/Dockerfile` 配置 `--workers 4`，但以下状态全部在进程内存中：
*   追踪数据 (`_traces`, `_active_spans`)
*   审批流程 (`_pending_approvals`)
*   执行任务 (`_running_jobs`)
*   SSE Ticket (`_sse_tickets`)
*   SSE 内存回退 (`_MemoryPubSub` 仅发心跳，无真实事件)

**后果：** 4 个 worker 之间无法共享这些状态，用户请求被不同 worker 处理时会看到不一致数据或丢失审批/追踪记录。

### 3. 数据库与迁移问题
*   Alembic 迁移为空：`alembic/versions/6ff59fe0db1e_initial_schema.py` 的 `upgrade()`/`downgrade()` 均为 `pass`。
*   `main.py` 启动时先尝试 `alembic upgrade head`（空操作），失败则回退到 `Base.metadata.create_all`。

**后果：** Schema 变更完全依赖 ORM 反射，团队协作时数据库结构难以追踪和回滚。

### 4. 多租户隔离缺陷
*   Pipeline API Key 认证时 `user=None`，跳过 `org` 过滤——持有 API Key 可查看所有组织的任务。
*   `/memory/patterns` 和 `/stats` 端点无组织隔离——全局可见。
*   `/api/executor` 的任务轮询/终止无租户绑定——知道 UUID 即可操作他人任务。
*   Gateway 创建的任务 `org_id` 通常为 `None`——与 UI 创建的任务隔离逻辑不同。
*   技能开关 (`toggle_pipeline_skill`) 是全局操作，任意 pipeline 认证者均可修改。

### 5. 安全隐患
| 问题 | 位置 | 风险等级 |
| :--- | :--- | :--- |
| `ModelProvider.api_key_encrypted` 字段存在但无加密实现 | `models/model_provider.py` | **高** |
| `llm_proxy` 的 `api_url` 参数可透传——潜在 SSRF | `api/llm_proxy.py` | **高** |
| Deploy API 的 `project_dir`/`private_key_path` 来自客户端——路径遍历风险 | `api/deploy.py` | **高** |
| Feishu 验证仅 token（无请求体签名验证） | `api/gateway.py` | 中 |
| Gateway 每条消息自动触发完整 E2E pipeline——成本和滥用风险 | `api/gateway.py` | 中 |
| 多处 `except: pass` 静默吞错（streaming、deploy、sandbox、monitor） | 多处 | 中 |

### 6. 前端问题
*   **类型不一致：** `PipelineDashboard.vue` 的可观测性面板绑定 `trace.taskId`/`trace.lastSpan` 等字段，但 `TraceInfo` 接口定义的是 `traceId`/`spost`——运行时显示空数据。
*   **审计/审批面板** 同样存在字段名不匹配。
*   **两套 API 认证体系共存：** `api.ts`(JWT/localStorage) vs `auth.ts`(Cookie/Session)，企业模式下 pipeline 调用可能使用错误的认证方式。
*   **代码冗余：** `api.ts` 大量代码未被引用（死代码）。
*   **无前端测试：** 无 Vitest/Jest 配置，无 `vue-tsc` 类型检查脚本。
*   **可访问性弱：** 大量可点击 `div`（无 `button`/`role`），删除按钮仅 `hover` 显示（触屏不友好）。
*   **功能缺失：** `CLAUDE.md` 声称的功能缺少 UI：Memory 管理页、DAG 可视化、Token 用量仪表盘、Model Provider 管理均无对应路由。

### 7. 测试覆盖严重不足
*   **后端测试仅覆盖：** 登录成功/失败、`/me` 认证、Pipeline 基础 CRUD。
*   **完全未覆盖：** Memory API、Agent/Skill CRUD、Conversation 冲突处理、SSE Ticket、Executor、可观测性、部署、多租户隔离、DAG 执行、Lead Agent 分解、LLM Proxy 等核心路径。

---

## 二、 SDLC 全流程覆盖评估

### 1. 需求分析 (~60%)
*   **已有能力：** `prd-expert` 技能可生成 PRD 文档；Pipeline 模板包含 planning 阶段；Lead Agent 可将需求分解为子任务。
*   **关键缺失：** 无需求追踪 ID/关联机制；无需求版本管理和变更追踪；无用户故事地图、验收标准模板；分解结果为纯文本，无结构化需求数据模型；`lead-agent` 角色在 `ROLE_TIER_MAP` 中缺失，默认降级为 `ROUTINE` 模型，导致分解质量受损。

### 2. 评审 (~30%)
*   **已有能力：** `code-review` 技能存在；`guardrails.py` 有审批模型 (`REQUIRE_REVIEW`/`WARN`)；可观测性可记录 trace。
*   **关键缺失：** 审批状态在内存中，重启丢失；正常 pipeline 阶段几乎不触发审批；无 PR Review 集成 (GitHub/GitLab)；无 "暂停等待人类审批后继续" 的可靠实现；角色权限表是硬编码 demo 数据；无评审意见闭环。

### 3. UI 设计 (~10%)
*   **已有能力：** `architecture-design` 技能可生成架构文档。
*   **关键缺失：** 无 UI/UX 设计 Agent；无设计稿生成能力；无原型图生成；无设计规范/组件库管理；无设计走查流程；无从设计到代码的自动转换。

### 4. 开发 (~45%)
*   **已有能力：** LLM Router 支持多家模型实现度 ~85%；Agent Runtime 有 ReAct 工具循环；`codegen/` 目录有代码生成模板；DAG 编排可并行执行阶段。
*   **关键缺失：** 无 Git 工作流集成（clone/branch/commit/PR）；代码仅以 Markdown 文本输出，不写入真实文件系统（除 `executor_bridge`）；工具沙箱无进程/资源隔离；DAG 的 `skip_condition` 已定义但从未被执行；条件分支（如"评审不通过回到设计"）未实现；Pipeline 未与 `skill_marketplace` 集成；Working memory (Redis) 因 `task_id` 未传入而在主 pipeline 中实际未使用。

### 5. 测试 (~25%)
*   **已有能力：** `test-strategy` 技能可生成测试策略文档；`Self-verify` 有基础启发式检查。
*   **关键缺失：** 无测试执行器（不能真正运行并收集结果）；无 CI 集成；无覆盖率收集与展示；无回归测试管理；`Self-verify` 无 LLM 验证；`RetryPolicy` 在技能执行中未使用。

### 6. 运维 (~15%)
*   **已有能力：** 可观测性有 trace span 基础模型；Token 使用量追踪 (DB 持化)；Health check 端点。
*   **关键缺失：** Trace 数据不跨 worker 共享；无持久化审计日志；无告警机制；无 SLO/SLA 追踪；无日志聚合；无性能基线对比；无安全扫描集成。

### 7. 上线部署 (~20%)
*   **已有能力：** `deploy/` 目录有 Vercel/Cloudflare/微信小程序/App Store 集成代码；`e2e_orchestrator.py` 链接 DAG $\rightarrow$ codegen $\rightarrow$ build $\rightarrow$ deploy $\rightarrow$ preview。
*   **关键缺失：** 多处部署代码 `except: pass` 静默吞错；`project_dir`/`private_key_path` 存在路径遍历风险；无灰度/金丝雀发布；无环境晋升机制；无回滚策略；无部署审批关卡；无部署后健康检查。

---

## 三、 优先级建议 (如果要让 SDLC 闭环跑起来)

### 🔴 P0 — 基础设施修复 (核心可用性)
1.  **状态持久化：** 将 `traces`/`approvals`/`executor jobs`/`SSE tickets` 迁移到 Redis 或 PostgreSQL，解决多 Worker 状态不一致问题。
2.  **数据库规范化：** 修复 Alembic 迁移，建立真实的 Schema 版本管理。
3.  **多租户隔离：** 实现 Memory/Pipeline API Key/Executor 的租户隔离。

### 🟠 P1 — 核心能力补全 (功能可用性)
1.  **语义化升级：** 接入 embedding 模型，实现真正的语义记忆检索。
2.  **Pipeline 增强：** 接入 Redis Working memory；实现 Pipeline $\leftrightarrow$ Skills 集成；实现 DAG 条件分支和 `skip_undone`。

### 🟡 P2 — SDLC 关键缺口 (闭环化)
1.  **Git 自动化：** 开发 Git 工作流 Agent (clone/branch/commit/PR)。
2.  **测试自动化：** 开发测试执行 Agent (运行测试 $\rightarrow$ 收集结果 $\rightarrow$ 反馈 pipeline)。
3.  **审批闭环：** 将 `guardrails` 真正嵌入部署 (deploy) 流程。

### 🔵 P3 — 体验提升 (产品化)
1.  **前端重构：** 修复类型不匹配；统一 API 认证体系；增加管理页面 (Memory/DAG/Token)。
2.  **测试覆盖：** 补全后端核心路径的单元测试。


