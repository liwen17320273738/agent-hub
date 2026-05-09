四件套全部交付，端到端验证通过。Lint 干净，dev server 已自动热加载新接口。

交付总结
1. DAG 跨 task 并行（全局 TaskScheduler）
核心问题：之前每个 /auto-run / /dag-run 都是 asyncio.create_task(...) — 50 个并发请求 = 50 条流水线同时打 LLM，没有上限、没有公平、没有可见性。

新增：

backend/app/services/task_scheduler.py — 进程级 TaskScheduler 单例
asyncio.Semaphore(SCHED_MAX_CONCURRENT)，默认 4，环境变量可调
FIFO 队列 + 寿命计数器（提交/完成/失败）
每个任务自带独立 AsyncSession（沿用 #1 的并行原则）
SSE 事件：scheduler:queued / scheduler:started / scheduler:finished
backend/app/api/scheduler.py — GET /api/scheduler/status
5 个调用点改写：smart-run、auto-run、run-stage、dag-run、resume-dag、resume，全部走 _submit_task()，立即返回 submissionId
实测：5 个 job 并发提交，cap=2 → 2 个 enter / 3 个 queued，FIFO 依次释放 ✓

2. 学习回路 A/B 灰度（shadow mode）
新增 status="shadow" 状态：

与 active 共存，按 LEARNING_SHADOW_TRAFFIC（默认 30%）分流
注入选择在每次调用前掷骰子（不缓存选择，只缓存候选对）
关键修复：通过 injected_override_id 显式传递到 review_stage_output，避免重新掷骰导致归因错误
自动毕业 / 退役策略（在 evaluate_auto_promotion 第 0 步）：

shadow 比 active 通过率高 ≥ SHADOW_GRADUATE_MARGIN（默认 0.10）→ 毕业为 active，旧 active 归档
shadow 比 active 通过率低 ≥ SHADOW_RETIRE_MARGIN → 退役归档
没有 active 基线时，shadow 自身达到 MIN_APPROVE_RATE 即直升
新增 API：

POST /api/learning/overrides/{id}/shadow — 把 proposed 推入灰度
learning:override-injected SSE 事件，UI 看到每次调用走的是 active 还是 shadow
实测：shadow 100% vs active 60% → 6 个 approve 后 shadow 自动晋升、active 自动归档 ✓ 反向：shadow 0% vs active 100% → 6 个 reject 后 shadow 自动退役、active 不动 ✓ 1000 次掷骰：497/503，分流分布健康 ✓

3. 沙箱前端可视化
src/views/InsightsObservability.vue 新增两个 tab：

工具沙箱：14 角色 × 35 工具的矩阵图
sticky 表头/列；工具名竖排省空间
单元格三态：绿（允许）/ 暗灰（拒绝）/ 蓝（COMMON 全角色共享）
下方实时滚动最近 100 条 SANDBOX_DENIED 审计
tab 上有 badge 显示 denial 计数
调度器：6 张 KPI（max / running / queued / 累计提交/完成/失败）+ "running"/"queued" 两列实时清单，5s 自动 poll
src/services/insightsApi.ts 新增：

fetchSandboxPolicy()、fetchSandboxDenials()、fetchSchedulerStatus()、shadowOverride()
完整的 TypeScript 类型 (SandboxPolicy / SandboxDenial / SchedulerStatus)
提案 override 上加了「灰度 (A/B)」按钮，一键推入 shadow。

4. MCP 动态工具沙箱
backend/app/services/tools/registry.py 新增 mcp_tool_allowed(role, tool_name)：

READ_ONLY_ROLES = {security, legal, finance, marketing, acceptance, qa-lead, ceo}
工具按名字前缀分类：get_/list_/read_/search_/... → read，delete_/create_/send_/push_/... → write
只读角色 + read 工具 → 允许；只读角色 + write/unknown 工具 → 拒绝（默认 deny）
其他角色 → 全部允许（向后兼容）
agent_runtime._execute_tool_call dynamic 分支：在调用 MCP handler 前先过 mcp_tool_allowed，拒绝时返回 SANDBOX_DENIED 错误 + 复用 _audit_sandbox_denial 写 AuditLog 和 SSE。

实测：

security 调 create_issue → 拒绝 ✓ + 审计落库
security 调 get_pull_request → 通过 ✓
legal 调 weird_thing → 拒绝（默认 deny unknown）✓
developer 调 delete_repo → 通过 ✓（非只读角色不限制）
无 role → 通过 ✓（back-compat）
系统形态对比（继上轮三件套）
维度	上轮	本轮
并发模型
单 task 内 stage 并行
+ 跨 task 全局 worker pool + 队列 + 实时 KPI
Override 升级
阈值触发 demote/promote
+ A/B shadow 灰度 + 头对头胜出/退役
沙箱可见性
REST /api/sandbox/policy
+ 14×35 矩阵 UI + denial 时间线
沙箱覆盖
仅静态 TOOL_REGISTRY
+ MCP / 动态工具按 read/write 前缀分类强制
下一步候选：

TaskScheduler 持久化：现在重启就丢队列。落 Redis ZSET 可以重启后接续
Shadow 金丝雀按 task 分群：当前是无差别 30%，可以按 task.template 或 complexity 做更细分组
沙箱矩阵编辑模式：UI 直接编辑 ROLE_TOOL_WHITELIST → 写回 DB 表，不再要改代码
MCP 工具自描述 metadata：让 MCP server 自己声明 category: read/write，比前缀启发式更可靠
要继续接哪一个？

没有跑偏吧？

没跑偏，对了原文 issuse06-phase02.md 末尾那 4 条候选，逐条交付：

原文候选（issuse06-phase02.md）	本轮交付	一致性
① DAG 跨 task 并行：加全局 worker pool 提高吞吐
TaskScheduler 单例 + Semaphore + FIFO 队列 + /api/scheduler/status + 5 个调用点改写
✓ 完全对齐
② 学习回路 A/B 灰度：新 proposed 影子运行 N 次再决定
status="shadow" + LEARNING_SHADOW_TRAFFIC 流量分流 + 头对头胜出/退役（SHADOW_GRADUATE_MARGIN / SHADOW_RETIRE_MARGIN）
✓ 完全对齐
③ 沙箱前端可视化：基于 /api/sandbox/policy 出 14×35 矩阵图
InsightsObservability.vue 新增「工具沙箱」tab，14×35 矩阵 + sticky 表头 + 三态着色 + denial 滚动列表
✓ 完全对齐
④ MCP 动态工具沙箱：让 MCP 工具也走 role 校验
mcp_tool_allowed() 前缀分类 + AgentRuntime._execute_tool_call dynamic 分支前置校验 + 复用 _audit_sandbox_denial
✓ 完全对齐
额外加的、原文没要求但顺手做的：

调度器 tab（#1 的 UI 配套，5s 自动 poll）
override 卡片上的「灰度 (A/B)」按钮（#2 的 UI 配套）
learning:override-injected SSE 事件（让前端能看到每次走 active 还是 shadow）
_run_in_background 的所有调用点全清理（不只是新加的，旧的也统一走 scheduler，避免两套并存）
没改的、原文也没要求：

没动 issuse04/05/06.md 任何文档文件
没动 git status 里的那些已有 modified（alembic、collaboration.py 等）
没创建任何新的 .md 文档（除非你要我写一份 phase03 收尾纪要）
要我把这轮的总结也落成 issuse06-phase03.md 吗？还是直接接下一轮？

本轮 4 项全部完成 — 端到端 smoke + lint 全绿。

落地清单
#1 TaskScheduler 持久化（上一段已完成）

Redis ZSET (scheduler:queue) + Hash 元数据；register_kind() 注册可序列化任务族；启动时 _resume_pending() 续跑
五个 pipeline 入口（smart_run/run_single_stage/auto_run_pipeline/dag_run/resume_pipeline）改用 kind+params 提交
#2 Shadow 按 template/complexity 分群（上一段已完成）

prompt_overrides.targeting JSON 列 + Alembic 7b8c9d0e1f2a
_targeting_matches / _targeting_overlap / _archive_overlapping：分段命中、互斥归档
set_override_targeting API + cache key 包含 (template, complexity)
pipeline_engine / dag_orchestrator 透传 template 到 get_active_addendum
#3 沙箱矩阵编辑模式

sandbox_rules 表 + Alembic 8c9d0e1f2a3b；sandbox_overrides 服务带内存缓存 + 启动时 preload_overrides
role_allowed 优先查 DB override；role_tool_summary.overrides 回带 UI 角标用
新增 GET/PUT/DELETE /api/sandbox/rules/{role}/{tool}（写操作 admin-only）
前端 InsightsObservability.vue 单元格可点击 → 弹窗（强制允许/拒绝/恢复默认 + 备注），保存后即时刷新
新增 legend "已被运维覆盖"（紫色环 cell-override）
#4 MCP 工具自描述 category

mcp_client.build_tool_handlers 把 MCP 标准 annotations（readOnlyHint/destructiveHint）和自定义 category 字段透传到 definitions
agent_runtime 维护 dynamic_tool_meta，调用 mcp_tool_allowed(role, tool, metadata=...)
classify_mcp_tool() 三级回退：metadata.category（含 17 种同义词，execute 等同 write）→ MCP annotations → 前缀启发；返回 (category, source) 让 audit 日志能解释为什么
8/8 单元覆盖：显式 read 覆盖写动词、destructiveHint 反向覆盖只读名、未知降级到前缀、非只读角色直通
Smoke 结果
沙箱 override 闭环：baseline → upsert(allow) → role_allowed=True → summary.overrides 出现 → delete → baseline 恢复 ✓
MCP metadata-aware: 8/8 ✓
Scheduler status() 暴露 registeredKinds + lifetime.{submitted,finished,failed,resumed_from_restart} ✓
learning_loop targeting helpers 8/8 ✓
17 个 Python 文件 py_compile 通过；所有改动文件 ReadLints 0 报错