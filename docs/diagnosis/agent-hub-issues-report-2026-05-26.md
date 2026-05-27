# Agent Hub 全面诊断报告

> 日期: 2026-05-26 | 版本: 2.0.0 | 测试轮次: 6轮

---

## 一、架构问题

### 1.1 流水线执行路径割裂

项目存在两条完全不同的任务执行路径：

| 路径 | 入口 | 执行机制 | 并发控制 |
|------|------|----------|----------|
| Gateway Intake | `POST /api/gateway/openclaw/intake` | `background_tasks.add_task` | **无限制** |
| Scheduler | `POST /api/pipeline/tasks/{id}/smart-run` | `TaskScheduler` (maxConcurrent=4) | **有** |

**问题**: Dashboard的"直接执行"走Gateway路径，绕过调度器的并发控制。100个用户同时提交 = 100个并行流水线，瞬间打满LLM rate limit和DB连接池。

**相关文件**: `backend/app/api/gateway.py:1122`, `backend/app/services/task_scheduler.py`

### 1.2 后台任务无超时机制

`_run_pipeline_background` 和 `run_full_e2e` 无限等待LLM响应，一个卡住的LLM调用永久占用worker。

**修复状态**: 已添加调度器超时 (1800s 默认，`SCHED_TASK_TIMEOUT`)，但gateway的`background_tasks`路径未覆盖。

**相关文件**: `backend/app/services/task_scheduler.py:548`, `backend/app/api/gateway.py:129`

### 1.3 API创建的任务永不执行

`POST /api/pipeline/tasks` 创建任务后所有stage保持`pending`，需用户手动触发执行。数据库中存在9个僵尸任务。

**相关文件**: `backend/app/api/pipeline.py:253`

### 1.4 Gateway孤岛任务

纯API key调用（无`X-Agent-Hub-Session`头）创建的任务`org_id=null`，对已登录用户不可见。数据库中存在3个孤岛任务。

**修复状态**: 已添加org fallback（回退到admin的org），待Dashboard实际场景验证。

**相关文件**: `backend/app/api/gateway.py:46`

---

## 二、流水线执行问题

### 2.1 完整流程断点

实测流水线执行到第4个stage（development）即blocked：

```
planning ✅ → design ✅ → architecture ✅ → 
development ❌(blocked) → testing → deployment
```

**根因**: e2e orchestrator在development阶段需要Claude Code CLI进行代码生成，当前环境未配置该工具。

**相关文件**: `backend/app/services/e2e_orchestrator.py:68`

### 2.2 SSE实时推送崩溃

`GET /api/pipeline/events?ticket=XXX` 端点触发 `ConnectionResetError`，Redis pub/sub订阅异常导致worker进程崩溃。用户无法看到流水线实时进度。

**相关文件**: `backend/app/api/events.py:40`

### 2.3 调度器死锁历史

Redis持久化队列(`scheduler:queue`)跨进程重启累积 + orphan扫描重复提交，导致9个任务全部卡死（running=4, queued=5, finished=0）。已通过清除Redis恢复。

**相关文件**: `backend/app/services/task_scheduler.py:299`

---

## 三、API运行时错误

| # | 端点 | 状态码 | 根因 | 修复 |
|---|------|--------|------|------|
| 1 | `GET /api/models/usage` | 500 DBAPIError | `token_usage.created_at` 列类型为 `TIMESTAMP WITH TIME ZONE`，asyncpg拒绝与Python naive datetime比较 | 代码修复已就位(string param + `::timestamp` cast)，需重启生效 |
| 2 | `GET /api/vector/collections` | 500 DBAPIError | 同上，datetime类型冲突 | 已添加try/except→503降级 |
| 3 | `POST /api/crawl/*` | ConnectionReset | crawl模块未捕获异常，导致worker进程crash | 已添加import保护 |

---

## 四、数据库问题

| # | 问题 | 详情 |
|---|------|------|
| 1 | Agent `pipeline_role` 全部为空 | 29个agent的role字段为NULL，Team页面角色筛选失效 |
| 2 | 连接池溢出 | 健康检查显示 `overflow: -4`，高峰期已出现连接泄漏 |
| 3 | datetime类型不一致 | `token_usage.created_at` 使用 `func.now()` (TIMESTAMPTZ)，但SQLAlchemy模型未声明 `DateTime(timezone=True)` |

**agent角色修复**: 已通过SQL UPDATE填充全部29个agent的`pipeline_role`（orchestrator/tech-lead/pm/developer/qa-lead/designer/devops/security/architect/acceptance/data-analyst/marketing/finance/legal）。

---

## 五、前端问题

### 5.1 组件规模

| 组件 | 行数 | 问题 |
|------|------|------|
| PipelineDashboard | 1697 | 单文件过大 |
| AgentChat | 1861 | 单文件过大 |
| PipelineTaskDetail | 3311 | 最大组件，140KB chunk |
| InsightsObservability | 1536 | 单文件过大 |
| WorkflowBuilder | 1258 | 单文件过大 |
| WayneConsole | 1252 | 单文件过大 + 177处硬编码中文 |
| EvalLab | 1209 | 单文件过大 |

共计22个组件超过500行。

### 5.2 状态覆盖缺失

11个组件缺少loading/empty/error状态处理：

| 组件 | 缺失状态 |
|------|----------|
| NotFound | loading, empty, error, 异常处理 |
| SkillsView | loading, empty, error, 异常处理 |
| WayneStack | loading, empty, error |
| AgentProfile | loading, error |
| Assets | loading, error |
| Team | loading, empty |
| AgentsConsole | empty |
| Inbox | loading |
| ModelLab | empty |
| Settings | empty |
| SharePage | empty |

### 5.3 硬编码中文未国际化

4个组件仍存在硬编码中文（其他组件的i18n替换因模板冲突已回退）：

| 组件 | 数量 |
|------|------|
| McpServers.vue | 29处 |
| PlanInbox.vue | 25处 |
| ExecutionLogTab.vue | 17处 |
| VoiceInput.vue | 14处 |

**i18n基础设施**: 已添加15个新section + voice完整section + 英文翻译，共1825个key，英文翻译完整。

### 5.4 视觉/布局问题

| # | 问题 |
|---|------|
| 1 | 侧边栏无移动端适配（220px固定宽度） |
| 2 | 59处固定宽度 > 300px（小屏布局破碎） |
| 3 | 字体10-11px过小（App.vue, AgentCard, ChatMessage等） |
| 4 | 106处 `v-for` 缺少 `:key`（渲染性能问题） |
| 5 | 30个文件使用 `overflow:hidden`（内容裁剪风险） |
| 6 | 无打印样式 |

**已修复**:
- 22个缺失CSS变量（已定义暗色/亮色双值）
- `:focus-visible` 键盘导航样式
- 主题切换按钮（深色/浅色）
- Dashboard提交toast
- 登录页账号指引
- 任务详情页"执行流水线"按钮
- 收件箱排队数显示
- `scrollBehavior` 页面切换回顶部
- HTML `lang` 动态切换

### 5.5 无障碍性

| # | 问题 |
|---|------|
| 1 | 6个图标按钮缺少 `aria-label` |
| 2 | 无 `:focus` 样式（键盘导航不可用）— **已修复** |

---

## 六、并发/扩展性问题

### 6.1 当前架构瓶颈

```
用户请求 → Nginx(仅Docker) → Vite Proxy(dev) → Uvicorn(单进程) → 
  ├── PostgreSQL(连接池20)
  ├── Redis(单实例)
  └── LLM Providers(4 healthy)
```

| 层级 | 瓶颈 | 影响 |
|------|------|------|
| 入口 | `background_tasks` 无限并发 | 100用户 = 100并行流水线 |
| DB | 连接池20，overflow已出现 | 50+并发时50%请求等连接 |
| LLM | 无rate limit保护 | 并行调用触发429限流 |
| 调度器 | maxConcurrent=4 | Gateway路径绕过了此限制 |
| SSE | Redis pub/sub单通道 | N个用户 = N个HTTP长连接 |
| 前端 | PipelineTaskDetail 140KB chunk | 首次加载慢 |
| 内存 | 单进程无隔离 | LLM响应内存影响所有请求 |

### 6.2 最危险场景

100个用户同时点"直接执行" → 100个`background_tasks`并行 → 100个`run_full_e2e` → 100个LLM调用同时发出 → **全部429 + DB连接池耗尽 + OOM**

### 6.3 建议

| 优先级 | 措施 |
|--------|------|
| P0 | Gateway intake改为走调度器（不绕过并发控制） |
| P0 | 为 `run_full_e2e` 添加总超时（当前仅调度器有超时） |
| P1 | DB连接池扩容至50+，或使用pgbouncer |
| P1 | 添加LLM调用rate limiter |
| P1 | 前端代码拆分 + 懒加载优化 |
| P2 | 多worker部署（gunicorn + uvicorn workers） |
| P2 | Redis集群用于SSE pub/sub |

---

## 七、修复总览

### 已修复 (15项)

| 轮次 | 修复项 |
|------|--------|
| R1 | 邮箱验证拒绝`.local`、登录页账号指引、执行按钮、浅色主题 |
| R2 | 负预算拒绝、无效UUID→400、长标题拒绝/截断 |
| R3 | 调度器超时(1800s)、models/usage优雅降级、vector/crawl保护、gateway org fallback、agent角色29/29填充 |
| R4 | Dashboard toast、Inbox排队数、`:focus`样式、`scrollBehavior`、动态`lang`、22个CSS变量、i18n 15新section |

### 未修复 (17项)

| 优先级 | 数量 | 问题 |
|--------|------|------|
| P0 | 2 | Gateway绕过调度器、后台任务无超时 |
| P1 | 5 | SSE crash、development阶段blocked、models/usage 500、API任务不执行、孤岛任务 |
| P2 | 6 | 106 v-for缺key、26文件缺错误处理、22个超大组件、4组件硬编码中文、11组件缺状态、侧边栏无移动端 |
| P3 | 4 | 59固定宽度、字体10-11px、6个aria-label缺失、无打印样式 |

---

## 八、测试覆盖

| 维度 | 覆盖量 |
|------|--------|
| 前端页面 | 23/23 |
| API端点验证 | 68 (OpenAPI注册262) |
| 路由器模块 | 39/39 |
| 数据库表 | 37 |
| E2E测试 | 2/2 |
| 前端构建 | 3.24s |
| i18n语言 | 4/4 (zh/en/ja/ko) |
| 并发测试 | 5并发创建通过 |
| 安全测试 | SQL注入、XSS、CORS通过 |
