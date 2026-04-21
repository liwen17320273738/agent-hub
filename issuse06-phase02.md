三件套全部交付，端到端验证通过。

1. 真并行 DAG 执行器
核心修复（backend/app/services/dag_orchestrator.py）：

之前 asyncio.gather 已经存在，但所有并行 stage 共享同一个 AsyncSession —— SQLAlchemy AsyncSession 不允许并发使用，实际跑起来就会互相吞 cursor，所以名义并行、实际串行甚至崩。
现在每个并行 stage 走 async with async_session() as stage_db 拿独立会话，独立 commit/rollback。
加了 asyncio.Semaphore(_DAG_PARALLEL_LIMIT)（默认 4，环境变量 DAG_PARALLEL_LIMIT 可调），防止 8 个 stage 一起冲 LLM 触发限流。
新 SSE 事件 pipeline:dag-batch-stats：上报 batch wall time / 串行总和 / speedup，UI 能看到"design ∥ architecture 加速 1.85×"。
单 stage 批次走老路（不开新会话，零开销）。
实测模板拓扑：

parallel_design / web_app    → batch1 ∥ [design, architecture]
fullstack_saas               → batch1 ∥ [design, architecture] + batch3 ∥ [testing, security-review]
2. 学习回路自动激活策略
新增（backend/app/services/learning_loop.py）：

阈值：AUTO_PROMOTE_MIN_USES=5、AUTO_PROMOTE_MIN_APPROVE_RATE=0.70、AUTO_DEMOTE_MAX_REJECT_RATE=0.50，LEARNING_AUTO_POLICY=0 一键关掉。
evaluate_auto_promotion(stage_id) 单阶段策略：
先降级：active 的 use≥5 且 reject_rate≥0.5 → archived。
再升级：(a) 没有 active 且 proposed 带 auto_apply=True → active；(b) active 表现差（approve_rate<0.7） → 用最新 proposed 替换。
record_override_outcome 改成在每次同行评审后自动跑 evaluate_auto_promotion，加上 expire_all() 解决 SQLAlchemy identity map 缓存掉新计数器的坑。
新 SSE 事件 learning:auto-policy，UI 可订阅看到"v2 自动晋升上线"。
新 REST：

GET /api/learning/policy — 当前阈值
POST /api/learning/auto-promote/evaluate — 手动 sweep 全部 stage 或单个 stage_id
端到端实测：

v1 active(uses=4, rejects=3) + v2 proposed
→ 一次 reject → uses=5, rejects=4(80%)
→ events: [auto_demoted v1 (rate=0.20), auto_promoted v2]
→ 注入 system_prompt 切换到 v2 ✓
3. Skill 沙箱按角色白名单
新增（backend/app/services/tools/registry.py）：

ROLE_TOOL_WHITELIST 覆盖 14 个角色（ceo / cto / product-manager / designer / architect / developer / qa-lead / acceptance / devops / security / data / legal / marketing / finance），最小权限原则：
security: 只读审计，禁 bash/file_write/git_push/deploy
developer: 全部编码权限，禁 git_push / git_create_pr（这是 devops 的活）
acceptance: 只能 browser/test/file_read，禁 任何代码改动
legal/finance/marketing: 纯研究只读
未配置的角色 → 不限制（向后兼容）
COMMON_TOOLS 全角色都能用：delegate_to_agent、agent_publish/wait_for、deerflow_*（任何受限角色都能"找别人帮忙"）。
execute_tool(..., role=, agent_id=, task_id=) 加第二层授权：拒绝时返回 Error: SANDBOX_DENIED — …，并：
写一行 AuditLog(action="tool.denied:<tool>", outcome="denied") —— 永久审计
发 SSE sandbox:tool-denied —— UI 实时告警
AgentRuntime 加 role 参数 → pipeline_engine 调用处把 stage_conf["role"] 透传进去 → 自动启用沙箱。
新 REST（backend/app/api/sandbox.py）：

GET /api/sandbox/policy — 全 role × tool 矩阵（前端可画格子图）
GET /api/sandbox/policy/{role} — 单角色 allowed/denied 列表
GET /api/sandbox/denials?task_id=… — 最近被拦的 tool 调用
实测：

security/git_push → SANDBOX_DENIED + audit row ✓
developer/git_push → SANDBOX_DENIED ✓ (developer 不该 push)
devops/git_push → 通过到底层（参数错是工具自己的事）✓
no role / mystery role → 通过（back-compat）✓
系统形态对比
维度	之前	现在
并行执行
asyncio.gather 但共用 session，实测会冲突
每 stage 独立 session + 信号量限流 + speedup 监控
学习闭环
proposed → 等人审批 → active
阈值触发自动升降级，60s Redis 缓存自动失效，全程审计 SSE
工具权限
一层 agent_tools 白名单（编辑 seed 才能改）
二层：role 白名单 + 运行时强制 + 拒绝写 AuditLog + REST 可视化
下一步候选（继续推可以做）：

DAG 跨 task 并行：现在每个 task 内部并行，多 task 之间还是按到达顺序串行；加全局 worker pool 可以显著提高吞吐
学习回路 A/B 灰度：新 proposed 影子运行 N 次再决定是否替换，比阈值激活更稳
沙箱前端可视化：基于 /api/sandbox/policy 出 14×35 的 role × tool 矩阵图，让审计/合规一眼看完
MCP 动态工具沙箱：当前 role 白名单不约束 MCP 加载的 dynamic_tools，可以让 MCP 工具也走 role 校验
要继续接哪一个？

