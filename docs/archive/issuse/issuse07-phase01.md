四件全部落地，156 tests passed / 0 lints。落地清单如下。

#1 — pytest 回归套（替换 4 轮手工 smoke）
新增 4 个测试模块，把之前 python3 -c "..." 跑 assert 的内容固化成可重跑断言：

backend/tests/unit/test_mcp_classify.py — 13 cases，覆盖 classify_mcp_tool 三层优先级（category → annotations → 前缀启发）+ mcp_tool_allowed 在 read-only role 下的拒绝矩阵
backend/tests/unit/test_learning_targeting.py — 11 cases，_targeting_matches / _targeting_overlap 段位过滤 & 冲突检测
backend/tests/unit/test_sandbox_overrides.py — 9 cases，upsert/delete/preload/list/role_allowed/role_tool_summary 全闭环
backend/tests/unit/test_task_scheduler.py — 7 cases，kind 注册、coro_factory 旧路径、kind+params 新路径、并发 cap、失败计数器、status shape
下一次 refactor 直接 pytest tests/unit 就能回归。

#2 — SandboxRule 跨进程失效广播（多 worker 一致性）
backend/app/services/sandbox_overrides.py：

加 _INVALIDATION_CHANNEL = "sandbox:rule-changed" + 进程级 _PROCESS_ID
upsert_rule / delete_rule 写完本地 cache 后调 _publish_change(...) 发 Redis pubsub
新增 _invalidation_listener_loop —— 长跑协程，订阅频道，收到 peer 广播就 _apply_remote_change；自己的 echo 通过 origin == _PROCESS_ID 跳过
新增 start_invalidation_listener() / stop_invalidation_listener()，幂等
app/main.py 的 lifespan：preload 后 await start_invalidation_listener()，shutdown 调 stop
兜底：Redis 挂掉时退回 in-memory pubsub（单进程仍正确，多 worker 退化为旧行为，不会 5xx）
新增 tests/unit/test_sandbox_pubsub.py —— 7 cases，包括 _apply_remote_change 三种 op、echo 抑制、publish 失败被吞、端到端 publish→listen
#3 — 单 task 自愈（REJECT 理由回注下一次 prompt）
之前 REJECT_TO 只重置 stage 状态，agent 看不到为什么被拒；现在闭环：

backend/app/services/dag_orchestrator.py：

DAGStage 加 reject_feedback: Optional[str] + reject_count: int
新增 _extract_rejection_feedback(content) —— 提取 REASON: ...（兼容中英文全角冒号）或退化到「REJECTED 之后的全部内容」，硬截 8KB
_reset_to_stage(..., feedback=...) —— 同时写到 target stage 上、reject_count++
DAG runner 检测到 REJECTED 时把 feedback 一起塞进，并在 SSE pipeline:dag-branch 里带 feedbackPreview + rejectCount
_run_stage 调 execute_stage(reject_feedback=stage.reject_feedback, reject_count=stage.reject_count)，调完清空 stage.reject_feedback（避免后续无关重试再次重放）
backend/app/services/pipeline_engine.py：

execute_stage 新增 reject_feedback、reject_count 参数
在 learning-loop addendum 之后注入 ## ⚠️ 上一次产出被审查驳回（第 N 次返工），包含 reviewer 原文 + 三条强制修订要求（先列「本轮修订摘要」、再给完整产出、不允许仅做表面更名）
发 SSE learning:self-heal-injected
backend/tests/unit/test_self_heal.py —— 10 cases 覆盖 regex 提取（含中文全角冒号、长文本截断）+ _reset_to_stage 三种语义（无 feedback、有 feedback、重复拒绝累积 reject_count）+ unknown stage 防御。

#4 — Jira / GitHub Issue 双向连接器包
新建独立 package backend/app/services/connectors/：

base.py —— IssueConnector Protocol + ExternalIssueRef / ExternalCommentRef / ConnectorResult（ok + skipped + error 统一形态，对齐 IM notify adapter 契约）
jira.py —— Jira Cloud REST v3，Basic auth（email + API token），create_issue 自动把 markdown body 包成 ADF document，add_comment 直接命中 /issue/{key}/comment
github.py —— GitHub REST v3，Bearer + X-GitHub-Api-Version: 2022-11-28，project 接 owner/repo slug，issue key 形如 acme/web#42
registry.py —— get_connector(kind) 懒构造 + 缓存，缺 env 自动返回 None；register_connector / reset_cache 给测试注入 fake；available_connectors() 列已配置项
REST API backend/app/api/integrations.py：

GET /api/integrations/connectors —— 列出已配置 + 配置提示
GET /api/integrations/connectors/{kind}/healthcheck
POST /api/integrations/connectors/{kind}/issues —— 创建 issue
POST /api/integrations/connectors/{kind}/comments —— 评论现有 issue（GitHub 自动从 owner/repo#N 拆 project）
已 include_router 进 main.py
tests/unit/test_connectors.py —— 17 cases，自建 _FakeAsyncClient mock httpx，分别验证 Jira/GitHub 的 healthcheck / create_issue / add_comment 成功路径、API 4xx/5xx、传输异常、缺配置软跳过、URL/headers/body 形态、per-call project 覆盖默认。

验证
backend/$ pytest tests/ -q
156 passed, 1 warning in 9.17s
ReadLints 在所有 17 个修改/新增文件上 — No linter errors found。

风险提示（继续推之前可关注的）
真正的多 worker 验证：pubsub 单进程 + in-memory fallback 都 green，但没有用真 Redis 做两进程的端到端跑（CI 没起 Redis）。上线前建议在 staging 起 2 worker 跑：worker A PUT /api/sandbox/rules/...，worker B 立刻 GET /api/sandbox/policy 看是否同步。
连接器还没自动 wire 到 DAG REJECT：PipelineTask 没有 external_links 列，自动「REJECT 时回写 issue 评论」需要先加 migration + external_links: JsonDict，再在 pipeline:dag-branch 时调 connectors.add_comment。这是有意分两步——先把库 + API + 测试做扎实，再决定持久化 schema。
self-heal 注入对 token 预算的影响：8KB cap 是上限，长 reviewer 长文 + 多次返工会让 system prompt 显著变大，可能触碰小模型的上下文窗口。如果跑 7B 级别的本地模型要再加一档「短模式」（只取摘要前 1KB）。
要继续推哪一条？我建议 (1) 真 Redis 双 worker 验证——这是 P0 级别的部署阻塞项；之后做 external_links migration + 自动回写，就能把 #4 的「demo 级」彻底升到「生产级闭环」。

