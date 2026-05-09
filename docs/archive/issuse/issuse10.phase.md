全部干完。下面是这一轮的交付清单 + 你期待看到的差异。

交付总结（P0 + P1 + UI(b) + 测试）
✅ P0a · Rate-limit 中间件不再把 429 变 500
backend/app/middleware/rate_limit.py

raise HTTPException(429) → return JSONResponse(status_code=429, ...)，绕开 Starlette BaseHTTPMiddleware 的著名陷阱
Retry-After / X-RateLimit-Limit / X-RateLimit-Window 三个标准 header 都加上
Loopback 豁免：127.0.0.1 / ::1 / localhost / 0.0.0.0 完全绕过限流（Vue dev server 一刷新打 7+ 个端点的痛点解了）
默认阈值 60/min → 600/min（config.py）
✅ P0b · resume-dag 不再撒谎
backend/app/api/pipeline.py + src/services/pipelineApi.ts + src/views/PipelineTaskDetail.vue

后端响应 {"ok":true, "queued":true, "started":true(deprecated), "submissionId":..., "message":"..."} —— 语义从「完成」变「已入队」，保留 started 兼容老 caller
前端 toast：ElMessage.success("DAG 续跑完成…") → ElMessage({type:'info'}, "已加入续跑队列，请关注下方实时日志")
日志事件 pipeline:dag-resumed → pipeline:dag-queued，带 submissionId
✅ P1a · LLM Provider 自动降级
backend/app/services/llm_router.py + pipeline_engine.py

新增 chat_completion_with_fallback(...)：
检测 retriable: HTTP {402, 408, 429, 500, 502, 503, 504} + 错误正文里的 Insufficient Balance / 1302 / 您的账户已达到速率限制 / quota / overloaded / 上游请求超时 等子串
降级链：deepseek → openai → anthropic → qwen → zhipu → google，跳过没配 key 的
401/403/400 立即短路（配置错不要烧别人的额度）
返回 tried_providers: [{provider, model, status, ok, error_excerpt}] + fell_back: bool 审计字段
on_fallback 回调 → pipeline_engine 推送 stage:provider-fallback SSE 事件
pipeline_engine 在 fallback 成功后把 active model 替换成实际成功的那个，cost / trace span 入账正确
✅ P1b · AI 军团 → Vue Flow DAG 画布（"作战图"）
新增 src/components/pipeline/PipelineDagCanvas.vue，挂在 PipelineTaskDetail.vue 阶段进度上方

复用 Workflow Builder 的 AgentStageNode（已自带角色 emoji、状态徽章、运行中脉冲动画、失败/驳回/审批/跳过的颜色）
三层状态合并：parent 的 processingStage > 自建 SSE map > 后端 snapshot — 刷新页面就有正确颜色，不用等 SSE
监听 stage:processing/completed/error/retry/awaiting-approval/skipped + pipeline:dag-branch/dag-start/rollback
新增 stage:provider-fallback 处理：右上角弹出 🔄 自动降级 → deepseek/deepseek-chat 的橙色徽章 + tooltip 带原因
节点点击 → scrollToStage() 平滑滚动到下方 stepper 的同一阶段，并用青色 box-shadow flash 1.2s
新增 SSE 状态指示 + "适配视窗" 按钮
渐变深色背景 + 径向高光，跟仪表盘整体风格一致；不破坏旧 stepper（保留作为详情抽屉）
✅ P2 · 测试与构建
新增 backend/tests/unit/test_llm_fallback.py（5 用例）：retriable 检测、Zhipu 1302 → DeepSeek 成功、401 短路不烧链、全失败返回最后错误、跳过无 key provider
新增 backend/tests/unit/test_rate_limit_middleware.py（4 用例）：loopback 豁免、/health 豁免、429 响应 shape（正面回归 500-bug）、默认 exempt 集合 pin 防退化
关键 fixture：把 redis pipeline mock 成 raise，强制走 in-memory fallback 路径，避免 TestClient event loop ↔ redis-py 的捆绑陷阱
结果：200 passed (从 182 → 200)，frontend vitest 7 pass，vite build 成功，无 TS / lint 报错
你应该看到的视觉差异
打开任一 pipeline 任务详情页（/pipelines/<id>）：

顶部新增暗色画布 "🔌 AI 军团作战图"，7 个 agent 节点横向排开，连线动画指向当前运行节点
跑流程时：当前节点边框脉冲发光（青色），完成转绿，失败转红，被打回转橙
右上角动态出现 🔄 自动降级 → deepseek/deepseek-chat 徽章 = LLM 真的从 Zhipu 切到 DeepSeek 了
点击任意节点 → 下方旧 stepper 自动滚到对应卡片并蓝色 flash
点"从检查点续跑"按钮：toast 改成蓝色 info 已加入续跑队列，可在实时日志区观察进度，不再是绿色"完成"
即使后台限流，dashboard 不再 freeze（仪表盘自己的轮询走 loopback 豁免）
下一步（可选）
按 issuse10.md 的 P2 还剩一项："mock 一个 LLM 限流 → 触发 fallback → 完成 7 阶段" 的端到端测试。这个需要把 chat_completion 在 pipeline_engine 流程里更深入地 mock，工时 ~1h。当前测试已覆盖核心降级逻辑本身，要不要做这个 e2e 由你决定。

要的话我现在就开 P2 e2e。