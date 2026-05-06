# Agent Hub 项目缺陷与问题深度分析报告

## 一、 安全问题（高危）

### 1. SSRF + API Key 泄露 — `llm_router.py`
用户可以通过 `api_url` 参数将请求定向到任意 URL，而服务端会带着自己的 provider API Key 去请求该地址。攻击者可以：
*   扫描内部网络（云元数据 `169.254.169.254` 等）。
*   搭建恶意 endpoint 收集 `Authorization` header 中的 API Key。

**代码位置：** `llm_router.py` (Lines 217-219)
```python
url = api_url or PROVIDER_ENDPOINTS.get(provider, PROVIDER_ENDPOINTS["openai"])
headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
```

### 2. QQ Webhook 未认证 — `gateway.py`
当 `PIPELINE_API_KEY` 未设置时，QQ webhook 完全开放，任何人都能创建任务并触发完整 E2E pipeline（含 LLM 调用，存在资金滥用风险）。

**代码位置：** `gateway.py` (Lines 245-250)
```python
secret = settings.pipeline_api_key
if secret:
    auth_header = request.headers.get("authorization", "")
    # ...
```
*注：OpenClaw 正确地在 key 缺失时返回 503，但 QQ 逻辑跳过了认证。*

### 3. `api_key_encrypted` 名不副实 — `model_provider.py`
字段名暗示加密，但代码中完全没有加密/解密实现，实际以明文存储。

**代码位置：** `model_provider.py` (Lines 14-22)
```python
class ModelProvider(Base):
    """Provider configuration with encrypted API keys."""
    # ...
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
```

### 4. Pipeline API Key 绕过多租户隔离
持有 `PIPELINE_API_KEY` 的调用者 `user=None`，`_apply_org_filter` 跳过 `org` 过滤，导致可以查看所有组织的任务数据。

**代码位置：** `pipeline.py` (Lines 68-72)
```python
def _apply_annot_org_filter(stmt, user: Optional[User]):
    """Scope query to user's org — API-key callers (user=None) see all."""
    if user and user.org_id:
        stmt = stmt.where(PipelineTask.org_id == user.org_id)
```

### 5. Git/Test 工具 CLI 参数注入
`git_tool.py` 中 `branch`、`remote` 等参数直接拼入命令列表，以 `-` 开头的分支名可被 Git 解释为选项（缺少 `--` 分隔符）。`test_runner.py` 的 `extra_args` 存在同类风险。

### 6. Docker Compose 弱凭据暴露
`docker-compose.yml` (Lines 6-9) 中：
*   `POSTGRES_USER: agenthub`
*   `POSTGRES_PASSWORD: agenthub`
*   Redis 无密码、JWT 默认值、管理员密码均使用易猜的默认值，且端口全部映射到宿主机。

---

## 二、 架构问题

### 1. 多 Worker + 内存回退 = SSE 失效
`Dockerfile` 配置 `--workers 4`，而 `_MemoryFallback.publish` 直接返回 `0`，不进行任何消息投递。
**后果：** 本地开发若 Redis 不可用，所有 SSE 实时推送完全静默，且系统不会报错。

**代码位置：** `redis_client.py` (Lines 66-67)
```python
async def publish(self, channel: str, message: str) -> int:
    return 0
```

### 2. `create_all` + `Alembic` 并存 — Schema 双源
`main.py` 每次启动都执行 `Base.metadata.create_all`，同时又有 Alembic 迁移，两者可能产生不一致。
**后果：** 生产环境应只依赖迁移，`create_all` 会跳过已存在的表但不处理列变更。

**代码位置：** `main.py` (Lines 69-71)
```python
async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
```

### 3. 重复路由冲突
`pipeline.py` 和 `events.py` 都注册了 `GET /api/pipeline/health`，返回不同 JSON 结构，后注册者覆盖前者，导致行为不可预测。

### 4. 速率限制失败开放
`rate_limit.py` 中，当 Redis 异常时直接 `return await call_next(request)`。
**后果：** 如果 Redis 宕机，所有请求将无限制通过，失去了限流保护。

### 5. Self-Verify 仍为启发式规则
文档声称 "LLM 驱动的质量验证"，实际 `self_verify.py` 只做字符串长度、关键词、截断检测等规则检查，无任何 LLM 调用。

### 6. Guardrails 角色权限硬编码
`guardrails.py` 中的 `ROLE_PERMISSIONS` 是硬编码的，无法从数据库加载或动态配置。

---

## 三、 代码质量

### 1. 广泛的异常吞没
多处 `except Exception` 仅记录 `logger.warning` 或直接 `pass`，关键场景包括：
*   `guardrails.py`: DB 持久化审批失败，可能丢失合规数据。
*   `observability.py`: Trace/Span 持久化失败静默。
*   `llm_router.py`: 流式返回中 JSON 解析失败 `pass`。
*   `rate_limit.py`: 任何异常直接放行。
*   `memory.py`: `pgvector` 检测失败静默禁用。

### 2. Executor 工作目录回退逻辑
`executor_bridge.py` 中，当白名单未配置时，不论传入什么路径都回退到 `os.getcwd()`。
**后果：** 调用者以为在沙箱中执行，实际在服务进程目录执行。

### 3. Collaboration 模块未与 Pipeline 集成
`collaboration.py` 定义了完整的多 Agent 会话模型，但 `pipeline_engine.py` 和 `dag_orchestrator.py` 均未调用，导致两套并行路径。

---

## 四、 前端问题

1.  **双套 API 认证体系：** `api.ts` (JWT)、`pipelineApi.ts` (Fetch/AuthToken) 和 `auth.ts` (EnterpriseApi) 三套路径可能导致 Token 不同步。
2.  **TypeScript 接口不匹配：** `api.ts` 中的 `AppConfig.features` 定义过少，无法接收后端返回的完整配置（如 `memory_layer` 等）。
3.  **功能缺失：** `CLAUDEMD` 声称的 Memory 管理、DAG 可视化、Token 用量、Model Provider 管理均无对应前端路由。
4.  **无前端测试：** 缺少 Vitest/Jest 配置、`vue-tsc` 类型检查及 CI 集成。

---

## 五、 测试覆盖评估

| 未覆盖模块 | 风险类型 |
| :--- | :--- |
| `llm_proxy` | 安全 (SSRF 回归) |
| `executor` API + 工作目录隔离 | 安全 (路径遍历) |
| `QQ webhook` 无 key 场景 | 安全 (权限绕过) |
| `SSE ticket` 流 + 实际事件投递 | 功能 (实时性失效) |
| `delivery_docs` 路径遍历 | 安全 (路径遍历) |
| `rate_limit` fail-open | 可用性 (拒绝服务攻击) |
| Redis 回退 vs 真实 Redis 行为 | 集成 (系统可靠性) |
| LLM 流式传输错误路径 | 可靠性 (用户体验) |
| 前端核心组件 | 质量 (回归风险) |

---

## 六、 优先级修复建议

| 优先级 | 问题 | 建议措施 |
| :--- | :--- | :--- |
| **P0 (安全)** | SSRF via `api_url` | 添加 URL 白名单，禁止内网/私有地址请求 |
| **P0 (安全)** | QQ webhook 无认证 | 统一策略：Key 缺失时返回 503 |
| **P0 (安全)** | `api_key_encrypted` 误导 | 使用 Fernet 加密或重命名字段 |
| **P1 (架构)** | 重复 `/api/pipeline/health` | 删除冗余路由，统一入口 |
| **P1 (架构)** | `create_all` + `Alembic` 双源 | 生产环境仅依赖 Alembic 迁移 |
| **P1 (安全)** | Git tool 参数注入 | 在命令参数前添加 `--` 符号 |
| **P1 (可靠性)** | Rate limit fail-open | 改为 fail-closed 或实现降级限流 |
| **P2 (质量)** | Self-verify 无 LLM 验证 | 实现 docstring 承诺的 LLM 验证链 |
| **P2 (架构)** | Collaboration 未集成 | 决定删除或接入 pipeline 流程 |
| **P3 (前端)** | 双套 API 层混乱 | 统一为单一 fetch wrapper |
| **P3 (测试)** | 补充关键路径测试 | 覆盖 SSRF、Gateway Auth、Executor 沙箱等 |



# Agent Hub 修复完成总结报告

## 🚀 修复概览
本次修复工作围绕 **安全 (P0)**、**架构稳定性 (P1)**、**代码质量 (P2)** 及 **用户体验 (P3)** 四个维度展开，旨在消除高危安全隐患，解决多 Worker 环境下的状态不一致问题，并统一系统的技术规范。

---

## 🔴 P0 — 安全修复 (3 项)
*目标：消除 SSRF、未经授权访问及凭据泄露风险。*

| 序号 | 问题描述 | 修复方案 | 涉及文件 |
| :--- | :--- | :--- | :--- |
| 1 | **SSRF via `api_url`**<br>用户可将请求定向到任意内网地址并窃取 API Key | 添加 `_validate_api_url()` 白名单验证，严禁请求私有 IP、localhost 及非允许域名 | `backend/app/services/llm_router.py` |
| 2 | **QQ Webhook 无认证**<br>`PIPELINE_API_ 密钥未设置时，Webhook 接口完全开放 | 统一认证逻辑：当 Key 未设置时，不再跳过校验，而是直接返回 `503 Service Unavailable` | `backend/app/api/gateway.py` |
| 3 | **API Key 伪加密**<br>`api_key_encrypted` 字段实际上以明文存储 | 引入 `Fernet` 对称加密机制（基于 `JWT_SECRET` 派生密钥），并实现 `set_api_key()` / `get_api_key()` 接口 | `backend/app/models/model_provider.py` |

---

## 🟠 P1 — 架构修复 (5 项)
*目标：解决路由冲突、权限注入及系统可靠性问题。*

| 序号 | 问题描述 | 修复方案 | 涉及文件 |
| :--- | :--- | :--- | :--- |
| 4 | **重复路由冲突**<br>`/api/pipeline/health` 在两处注册导致行为不可预测 | 移除 `pipeline.py` 中的简陋版实现，统一保留 `events.py` 的标准实现 | `backend/app/api/pipeline.py` |
| 5 | **速率限制失败开放**<br>Redis 异常时，系统失去所有流量保护 | 引入**内存计数器回退机制**：当 Redis 无法连接时，切换至本地内存计数，确保基本限流能力不丢失 | `backend/app/middleware/rate_limit.py` |
| 6 | **Git 工具参数注入**<<br>分支名以 `-` 开头可被解释为 Git 选项 | 添加 `_sanitize_ref_name()` 拒绝非法名称；所有命令增加 `--` 分隔符；`write_file` 强制使用 `resolve()` 验证路径 | `backend/app/services/tools/git_tool.py` |
| 7 | **Executor 工作目录风险**<br>白名单未配置时静默回退到 `cwd` | 将“静默回退”改为 `raise ValueError`，强制调用方处理路径合法性问题 | `backend/app/services/executor_bridge.py` |
| 8 | **Schema 双源冲突**<br>`create_all` 与 `Alembic` 存在竞争 | 限制 `create_all` 仅在 `SQLite/debug` 模式下执行；生产环境（PostgreSQL）强制仅依赖 `Alembic` 迁移 | `backend/app/main.py` |

---

## 🟡 P2 — 质量修复 (2 项)
*目标：提升代码健壮性与安全性。*

| 序号 | 问题描述 | 修复方案 | 涉及文件 |
| :--- | :--- | :--- | :--- |
| 9 | **角色权限硬编码**<br>权限表包含 `Agent-ceo` 等特定租户数据 | 移除硬编码，改为通用角色模型，并允许通过 `GUARDRAIL_ROLE_PER 环境变量` 进行动态覆盖 | `backend/app/services/guardrails.py` |
| 10 | **SQL 注入 + 静默异常**<br>`min_quality` 使用 f-string 拼接 | 切换为**参数化查询** (`:min_quality`)；针对异常捕获增加详细的 `logger.error` 日志 | `backend/app/services/memory.py` |

---

## 🔵 P3 — 体验修复 (2 项)
*目标：优化前后端交互一致性。*

| 序号 | 问题描述 | 修复方案 | 涉及文件 |
| :--- | :--- | :--- | :--- |
| 11 | **前端 AppConfig 类型缺失**<br>前端无法感知后端新增的 6+ 个功能特征 | 补全 TypeScript 接口定义，包含 `memory_layer`、`dag_orchestrator`、`self_verify` 等字段 | `src/services/api.ts` |
| 12 | **Docker Compose 弱凭据**<br>硬编码密码且端口完全暴露 | 采用 `${VAR:?error}` 语法强制环境变量注入；注释掉敏感端口映射；为 Redis 配置访问密码 | `docker-compose.yml` |

---
**状态：** ✅ 所有修复已通过单元测试及集成校验。
**下一步建议：** 建议启动 `Alembic` 迁移脚本，以同步最新的数据库架构变更。 🌫️

---
# Agent Hub 改进实施完成总结报告

## 🚀 核心改进概览
本次迭代完成了对 Agent Hub 架构、安全、功能及测试体系的全面重构。通过 14 项关键改进，成功将项目从“实验性原型”提升到了“生产级 SDLC 平台”的水平。

---

## 🔴 P0 — 基础设施修复 (4 项, 全部完成)
*目标：解决分布式环境下的状态丢失与多租户安全隐患。*

| 编号 | 模块 | 修复内容 | 涉及文件 |
| :--- | :--- | :--- | :--- |
| **P0-1/2** | **状态持久化** | 将 Trace/Span、Approvals、Executor Jobs、SSE Tickets 从进程内存迁移至 **Redis**，支持多 Worker 共享与 TTL 自动过期。 | `services/observability.py`, `services/guardrails.py`, `services/executor_bridge.py`, `api/events.py`, `redis_client.py` |
| **P0-3** | **数据库迁移** | 修复 Alembic 迁移脚本，从 `pass` 升级为包含 **17 张核心表** 的完整 DDL 迁移。 | `alembic/versions/6ff59fe0db1e_initial_schema.py` |
| **P0-4** | **多租户隔离** | 实现 `org_id` 强制过滤（Memory/Skills/Executor）及 Admin 权限校验。 | `api/memory.py`, `api/pipeline.py`, `services/executor_bridge.py`, `api/executor.py` |

---

## 🟠 P1 — 核心能力补全 (4 项, 全部完成)
*目标：构建基于 AI 驱动的闭环开发链路。*

| 编号 | 功能模块 | 改进描述 | 关键技术实现 |
| :--- | :--- | :--- | :--- |
| **P1-1** | **语义记忆检索** | 引入 **Embedding 向量检索**，结合 7 语义相似度 + 30% 质量分数混合排序。 | `services/memory.py` (OpenAI-compatible API) |
| **P1-2** | **Working Memory** | 建立 Pipeline 与任务上下文的强绑定，实现各阶段输出自动存入任务上下文。 | `services/pipeline_engine.py`, `services/memory.py` |
| **P1-3** | **Pipeline ↔ Skills** | 实现阶段驱动的技能注入，根据当前 Pipeline Stage 自动匹配并加载相关技能。 | `services/pipeline_engine.py`, `services/skill_marketplace.py` |
| **P1-4** | **DAG 智能编排** | 实现 `skip_condition` 与 `REJECTED` 逻辑回退，支持基于文本匹配的动态跳过。 | `services/dag_orchestrator.py` (Adaptive Template) |

---

## 🟡 P2 — SDLC 关键缺口 (3 项, 全部完成)
*目标：赋予 Agent 实际的操作与执行能力。*

| 编号 | 模块 | 改进内容 | 关键能力 |
| :--- | :--- | :--- | :--- |
| **P2-1** | **Git 工作流 Agent** | 提供 10 种 Git 工具（Clone, Commit, PR 等），具备目录白名单安全控制。 | `services/tools/git_tool.py` |
| **P2-2** | **测试执行 Agent** | 自动检测并支持 pytest/jest/vitest/go/cargo 等框架，生成结构化 Markdown 报告。 | `services/tools/test_runner.py` |
| **P2-3**| **部署审批关卡** | 将 Deployment 与 Security-review 权限从 `WARN` 升级为 `REQUIRE_REVIEW`。 | `services/guardrails.py` |

---

## 🔵 P3 — 体验提升 (3 项, 全部完成)
* **P3-1 前端类型对齐：** 修复 `pipelineApi.ts` 交互接口，确保 TraceInfo 等字段与后端完全一致。
* **P3-2 认证体系统一：** 根据 `VITE_ENTERPRISE` 自动切换 JWT/Cookie 模式，清理死代码。
* **P3-3 测试覆盖升级：** 新增 **36 个** 专项测试用例，覆盖 Memory, Observability, DAG, Planner 等核心逻辑。

---

## 📊 改进前后对比 (Before vs After)

| 类别 | 问题 | 修复前 (Legacy) | 修复后 (Modernized) |
| :--- | :--- | :--- | :--- |
| **P0** | 追踪数据/审批流 | 进程内存字典，多 Worker 不共享 | **Redis 持久化 + TTL 自动过期** |
| **P0** | Alembic 迁移 | 迁移内容为空 (`pass`) | **完整 1 7 张表 DDL 迁移** |
| **P1** | Memory 检索 | 仅支持简单的关键字 `ILIKE` | **Embedding 向量 + 语义混合排序** |
| **P1** | DAG 逻辑 | 无条件分支，仅线性执行 | **支持条件跳 越与 REJECTED 回退** |
| **P2** | 自动化能力 | 仅能以 Markdown 输出文档 | **具备 Git/Test 真实执行能力** |
| **P3** | 前端一致性 | 字段名不匹配，认证逻辑混乱 | **接口完全对齐，认证模式自适应** |

---

## ✅ SDLC 流程验收结论

### 1. 测试表现
* **测试总数**：76
* **通过率**：**100%** (76/76)
* **额外修复**：`database.py` 事务提交逻辑优化；`redis_client.py` 重复方法清理。

### 2. 关键代码完整性 (9/9 通过)
* **Observability/Guardrails/Executor/Events/Git/Test/DAG/Memory/Redis** 均通过集成测试验证。

### 3. 流程 API 验收
* **认证/任务创建**：`org_id` 自动绑定成功。
* **Pipeline 推进**：`Planning` $\rightarrow$ `Deployment` 全流程 API 链路打通。
* **驳回/回退**：`REJECT` 流程触发 `architecture` $\rightarrow$ `planning` 回退成功。
* **多租户隔离**：`Memory Search` 与 `Task List` 均实现了 `org_id` 隔离验证。

---
**报告生成日期：** 2026-04-16
**状态：** 🚀 **DEPLOYMENT READY**

---
# 第二轮修复总结报告 (Round 2 Fix Summary)

## 🚀 修复概览
本次第二轮修复重点解决了一系列隐蔽的**安全漏洞 (Security)**、**系统可用性 (Availability)** 以及**前端认证逻辑的健壮性 (Robustness)**。

---

## 🛠️ 修复细节 (共 7 项)

| 序号 | 问题描述 | 修复方案 | 涉及文件 |
| :--- | :--- | :--- | :--- |
| **13** | **Pipeline API Key 绕过隔离**<br>当 `user=None` (API Key 调用) 时，可越权查看所有组织的任务。 | 限制 API Key 调用者只能访问 `org_id IS NULL` 的任务，确保租户数据隔离。 | `backend/app/api/pipeline.py` |
| **14** | **SSE 内存回退静默**<br>`_MemoryFallback.publish` 直接返回 `0`，导致开发模式下无法收到推送。 | 实现进程内 `asyncio.Queue` 的 pub/sub 机制，确保 Redis 不可用时 SSE 事件仍能正常投递。 | `backend/app/redis_client.py` |
| **15** | **测试执行参数注入**<br>`test_runner.py` 的 `extra_args` 可被注入危险参数 (如 `--exec`)。 | 引入**阻止列表** + **特殊字符检测** (`;`, `` ` ``, `&`, `$`)。 | `backend/app/services/tools/test_runner.py` |
| **16** | **文件路径遍历风险**<br>`delivery_docs` 接口通过 `{path}` 参数可捕获系统敏感文件。 | 强制使用 `{name}` 模式 + **白名单校验** + 路径 `resolve()` 后前缀验证。 | ` backend/app/api/delivery_docs.py` |
| **17** | **文档欺骗问题**<br>`self_verify.py` 文档声称是 LLM 验证，实际仅为规则检查。 | **更正 docstring**，如实说明当前仅为启发式规则检查。 | `backend/app/services/self_verify.py` |
| **18** | **认证逻辑过敏**<br>网络抖动或 5xx 错误会导致前端自动清除用户登录状态。 | 调整策略：仅在收到 **401/403** 错误时清除用户，其他网络错误应保留现有状态。 | `src/stores/auth.ts` |
| **19** | **关键链路异常静默**<br>`observability/guardrails` 在 DB 持久化失败时仅记录 `warning`。 | 提升日志级别至 `error`；增加**阈值告警**（连续失败 5 次后额外触发告警）。 | `observability.py`, `guardrails.py` |

---

## ⚖️ 修复后状态评估

| 维度 | 修复前 (Vulnerable/Fragile) | 修复后 (Secure/Robust) |
| :--- | :--- | :--- |
| **安全性** | 存在路径遍历、参数注入、API Key 越权风险 | **引入白名单、参数清洗、租户隔离校验** |
| **可用性** | 关键服务 (SSE/Auth) 在环境异常时会静默失效或误触发 | **具备内存回退机制与智能重试策略** |
| **准确性** | 文档与实现不符，存在“欺骗性”注释 | **文档与实现一致，符合技术规范** |

---
**报告生成日期：** 2026-04-16
**状态：** ✅ **SECURITY & ROBUSTNESS STRENGTHENED**



改进实施完成总结
P0 — 基础设施修复 (4 项, 全部完成)
P0-1 & P0-2: 内存状态迁移到 Redis
修改了 6 个文件:
services/observability.py — traces/spans 存入 Redis (trace:{id}, span:{id}, 排序集合 traces:recent)
services/guardrails.py — approvals 存入 Redis (approval:{id}, 集合 approvals:pending), audit 日志存入排序集合
services/executorbridge.py — jobs 存入 Redis (executor:job:{id}), logs 用 Redis List
api/events.py — SSE tickets 用 Redis + TTL 自动过期
redisclient.py — 添加 zadd/zrevrange/sadd/smembers/rpush/lrange 内存回退支持
所有调用方添加了 await
P0-3: 修复空 Alembic 迁移
alembic/versions/6ff59fe0db1einitialschema.py — 从空 pass 改为创建全部 17 张表的完整迁移
P0-4: 多租户隔离
api/memory.py — /search, /patterns, /stats 按 orgid 过滤
api/pipeline.py — togglepipelineskill 限制为 admin 角色
services/executorbridge.py + api/executor.py — 添加 createdBy 字段和所有权检查
P1 — 核心能力补全 (4 项, 全部完成)
P1-1: 语义记忆检索
services/memory.py — 添加 getembedding() (OpenAI-compatible API), cosinesimilarity(), embedding 缓存到 Redis
searchsimilarmemories() — 70% 语义相似度 + 30% 质量分数混合排序，关键字搜索作为后备
P1-2: Working Memory 接入 Pipeline
services/pipelineengine.py — 向 getcontextfromhistory() 传入 taskid, 每个阶段输出存入 working memory
services/memory.py — 新增 storelearnedpattern() 用于积累学习模式
P1-3: Pipeline ↔ Skills 集成
services/pipelineengine.py — Layer 3 注入匹配当前阶段的技能 prompt
services/skillmarketplace.py — 新增 getskillsforstage() 和 STAGESKILLMAP
P1-4: DAG 条件分支 + skipcondition
services/dagorchestrator.py — 实现 shouldskip(), extractrejectiontarget(), _resettostage()
支持 4 种条件: simpletask, nocode, approved, 自定义 stage.{id}.contains:{text}
新增 adaptive 模板，支持智能跳过阶段
executedagpipeline() 改为动态 while 循环，支持 REJECTED 回退
P2 — SDLC 关键缺口 (3 项, 全部完成)
P2-1: Git 工作流 Agent
新建 services/tools/gittool.py — 10 个 Git 工具 (clone/status/checkout/add/commit/push/diff/log/createpr/writefile)
注册到 tool registry，支持目录白名单安全控制
P2-2: 测试执行 Agent
新建 services/tools/testrunner.py — 支持 pytest/jest/vitest/go test/cargo test
自动检测项目使用的测试框架
结构化解析测试结果 (pass/fail/skip 计数)
生成 Markdown 测试报告供 pipeline 消费
P2-3: 部署审批关卡
services/guardrails.py — deployment 和 security-review 从 WARN 升级为 REQUIREREVIEW
Pipeline 到达部署阶段时自动暂停等待审批
P3 — 体验提升 (3 项, 全部完成)
P3-1: 前端类型修复
services/pipelineApi.ts — TraceInfo/ApprovalItem/AuditEntry 接口对齐后端实际返回
views/PipelineDashboard.vue — 修复可观测性面板全部字段绑定
P3-2: 统一 API 认证
services/pipelineApi.ts — 根据 VITEENTERPRISE 自动切换 cookie/JWT 模式
移除死代码 unifiedApiFetch 导入
P3-3: 测试覆盖
新建 5 个测试文件, 共 36 个测试用例:
testmemoryapi.py — 5 个 Memory API 测试
testobservability.py — 7 个可观测性 API 测试
testdagorchestrator.py — 12 个 DAG 编排单元测试
testselfverify.py — 4 个自验证单元测试
testplannerworker.py — 8 个模型选择单元测试

全部 14 项改进已验证通过。 下面是改进前后的对比：
类别 问题 修复前 修复后
P0-1 追踪数据/审批流内存存储 进程内存字典，多 Worker 不共享 Redis 持久化，24h/7d/30d TTL
P0-2 Executor 任务/SSE Ticket 内存存储 进程内存，重启丢失 Redis 持久化 + 自动过期
P0-3 Alembic 迁移为空 upgrade()/downgrade() 均为 pass 创建全部 17 张表的完整 DDL
P0-4 多租户隔离缺陷 Memory/Skills/Executor 全局可见 orgid 过滤 + admin 权限 + 所有权检查
P1-1 Memory 仅关键字搜索 ILIKE 关键字匹配 embedding 向量 + 70%语义/30%质量混合排序
P1-2 Working memory 未接入 Pipeline taskid 未传入，Redis 缓存空转 每阶段读写 working memory
P1-3 Pipeline 与 Skills 脱节 两套并行路径 阶段执行时自动注入匹配技能 prompt
P1-4 DAG 无条件分支 skipcondition 定义了但从未执行 4 种条件评估 + REJECTED 回退 + adaptive 模板
P2-1 无 Git 集成 代码只能以 Markdown 输出 10 个 Git 工具 (clone/commit/push/PR...)
P2-2 无测试执行能力 只能生成测试文档 支持 5 种框架，结构化结果解析
P2-3 部署无审批关卡 deployment 仅 WARN REQUIREREVIEW，必须人工审批
P3-1 前端类型不匹配 可观测性面板字段名错误 接口与模板全部对齐后端实际返回
P3-2 两套认证体系 JWT vs Cookie 混用 自动根据 enterprise 模式切换
P3-3 测试覆盖不足 仅 3 个基础测试文件 新增 36 个测试用例，覆盖 5 个核

SDLC 全流程验收报告

测试套件
项目 结果
测试总数
76
通过
76
失败
0
额外修复
database.py 中 getdb() 事务提交逻辑 + redisclient.py 重复方法清理
关键代码完整性 (9/9 通过)
文件 状态 验证点
observability.py
OK
Redis traces/spans，async，trace:/span: key
guardrails.py
OK
Redis approvals/audit，deployment=REQUIREREVIEW
executorbridge.py
OK
Redis jobs，executor:job: key
events.py
OK
Redis SSE tickets + TTL
gittool.py
OK
10 个 Git 工具
testrunner.py
OK
5 框架检测 + 结构化报告
dagorchestrator.py
OK
skip/reject/reset + adaptive 模板
memory.py
OK
embedding + cosine similarity
redisclient.py
OK
已清理重复定义
SDLC 流程 API 验收
步骤 API 结果
认证
POST /api/auth/login
JWT token 获取成功
创建任务
POST /api/pipeline/tasks
orgid 自动绑定
Planning → Architecture
POST .../advance
阶段推进成功
Architecture → Development
advance
OK
Development → Testing
advance
OK
Testing → Reviewing
advance
OK
Reviewing → Deployment
advance
OK
Deployment → Done
advance
全流程完成
驳回测试
POST .../reject
architecture → planning 回退成功，architecture 标记 blocked
Artifact 存储
POST .../artifacts
PRD 文档保存成功
可观测性 Traces
GET /api/observability/traces
返回正常
审批列表
GET /api/observability/approvals
返回正常
审计日志
GET /api/observability/audit-log
返回正常
SSE Ticket
POST /api/pipeline/events/ticket
Redis ticket 生成成功
Working Memory
GET /api/memory/working/{taskid}
上下文返回正常
Memory 搜索
GET /api/memory/search
orgid 隔离生效
模型解析
POST .../planner/resolve-model
zhipu/glm-4-flash 正确返回
多租户
tasks 列表
只返回当前 org 的任务
Skills
GET /api/skills/
6 个技能正常加载
Health
GET /health
PostgreSQL + Redis 正常连接
额外修复（本次执行中发现并修复）
database.py: getdb() 的自动提交条件 session.dirty or session.new or session.deleted 在 flush() 后不生效，导致数据对后续请求不可见。改为无条件 await session.commit()。
redisclient.py: _MemoryFallback 中 sadd、smembers、rpush、lrange、zadd、zrevrange 各有 2-3 个重复定义，存储在不同字典中 (memorystore vs _memorysets/memoryzsets)。清理为只保留使用专用字典的版本。

#	严重度	问题	文件
20
P0
preview.py Node -e 命令注入 — url/path 直接拼入 JS
interaction/preview.py
21
P0
observability memory/search 无 org_id — 跨租户搜索
api/observability.py
22
P0
任意用户可 resolve 任意 approval — 审批绕过
api/observability.py
23
P1
Feishu webhook 缺 header 时跳过验证
api/gateway.py
24
P1
bash_tool 弱黑名单 + 继承全部环境变量
tools/bash_tool.py
25
P1
build_tool project 路径遍历
tools/build_tool.py
26
P1
docker_sandbox write/read_file 路径遍历
tools/docker_sandbox.py
27
P1
codegen_agent filepath 路径遍历
codegen/codegen_agent.py
28
P1
working memory API 任务不存在仍可读写
api/memory.py
29
P1
executor jobs by task_id 无权限检查 (IDOR)
api/executor.py
30
P1
interaction feedback rerun 无 org 过滤
api/interaction.py
31
P2
API key 使用 == 比较 — 时序攻击
security.py + gateway.py
32
P2
/health 暴露具体 provider 名称
main.py
33
P2
preview URL/webhook SSRF 无防护
interaction/preview.py
34
P3
前端 detail 为数组时显示 [object]
src/services/api.ts
35
P3
sandbox startswith 路径比较边界问题
tools/sandbox.py
36
P3
alembic downgrade 无条件 DROP EXTENSION
alembic/.../add_observability_tables.py