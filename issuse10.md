This is the deeper bug. Two separate failures cascading:

LLM rate-limit (provider side) → Zhipu GLM returns 1302 → development stage fails
Backend's own rate-limit middleware is firing on the frontend's polling traffic → returns 500 Internal Server Error instead of a clean 429 → frontend can't refresh → page looks frozen
Let me see the rate-limit threshold + why the 429 becomes a 500:

完整诊断完了。先给你诚实结论，再列具体证据 + 修复方案。

结论 — 都不是好消息但都能修
「现在能跑完吗？」 → 架构能，实践不能
DAG / checkpoint / resume / quality-gate 这套架构是完整的（pipeline_engine 已正常完成 3 个阶段并生成产出），但三个独立 bug 串成了一条死锁链，让你这次跑不下去。

「架构有问题吗？」 → 架构 OK，但有三处实现 bug + 一处 UX 缺位
Bug 1 · LLM Provider 限流没有自动 fallback
15:36:10  development → glm-4-flash → 1302 "您的账户已达到速率限制"
15:39:59  (续跑) → glm-4-flash → 同样 1302  ← 没换 provider
15:40:17  (续跑) → glm-4-flash → 同样 1302  ← 还是 glm-4-flash
根因：pipeline_engine 选模型只看 stage override，没接 llm_router 的 fallback 链。Zhipu GLM 一限流就死循环。 应有行为：rate-limit / insufficient-balance 错误码应自动降级到下一家（DeepSeek / Qwen / Claude…），并把降级事件写进日志。

Bug 2 · 后端自己的 rate-limit middleware 把 429 变成 500
日志里夹了 20+ 个 ASGI Exception，全是这一行：

# backend/app/middleware/rate_limit.py:48
raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")
根因：在 BaseHTTPMiddleware.dispatch 里 raise HTTPException 是 Starlette 的著名陷阱 —— 抛出的异常不会被 FastAPI 异常处理器接住，会冒到 ASGI 层变成 500。 雪上加霜：阈值 rate_limit_per_minute=60 （= 1 req/秒）。你这页一次轮询 7 个端点（health / templates / tasks / 单任务 / observability / sdlc-templates / events），刷新 1 次就吃 7 个配额，10 秒就触顶 → 每个 GET 都 500 → 页面看起来卡死了，其实是后端在 500 中。 修复：① 把 raise HTTPException 改成 return JSONResponse(429, ...)；② 阈值放宽到 600/min 或对 localhost / 已认证用户豁免。

Bug 3 · 「续跑」响应误导
# pipeline.py:1011  resume-dag 接口
return {"ok": True, "started": True, ...}   # 任务刚进队列就返回 ok:true
// PipelineTaskDetail.vue:1109  前端
ElMessage.success(res.ok ? `DAG 续跑完成（…）` : '…未全部完成')
结果：你点续跑 → 后端把任务塞进队列就返回 ok:true → 前端弹绿色 toast「DAG 续跑完成」→ 实际上 worker 1 秒后才跑，3 秒后又被 LLM 1302 干掉，你完全不知道。 修复：改成 {"ok": true, "queued": true, "submissionId": ...} + 前端 toast 改「已加入续跑队列…」+ 引导用户看实时日志区。

UX「死板」 → 真问题，不是错觉
对比看：

维度	Workflow Builder（动）	AI 军团（死）
节点形态
拖拽 DAG 画布，节点连线
7 个固定圆圈竖排
状态反馈
SSE 推送，节点变色 + edge 流光
圆圈静态变绿
Agent 形象
画布 + 角色色
一行小字 developer / qa-lead
进行中提示
节点边框旋转
一个旋转 icon
为什么觉得死：

没有 agent 头像 / 个性 —— 「product-manager」这种纯文字不会让人觉得这是个角色
没有 stage 之间的流光 / 进度条动效
「门禁通过」「90%」「10.6min」是数字但没有视觉权重，跟 Excel 一样
整页纵向 stepper是 2018 年 Antd Pro 的味道，2026 年看像静止的工单系统
我建议的处理顺序（按 ROI 排）
优先级	任务	工作量	价值
P0
修 Bug 2（429 → JSONResponse + 阈值放宽）
10 min
立刻解开页面 freezing，最大痛点
P0
修 Bug 3（resume-dag 响应语义 + 前端 toast 文案）
15 min
续跑不再骗人
P1
修 Bug 1（接 llm_router 的 provider fallback 链 + 上抛 1302/insufficient_balance 类错误到 SSE）
1-2 h
真正能跑完
P1
AI 军团 UI 升级：横向卡片布局 + Agent 头像 + 进行中边框 pulse + stage-to-stage 渐变流光 + 完成时打勾粒子
半天
配上「军团」这个名字
P2
补 e2e 测试：mock 一个 LLM 限流 → 触发 fallback → 完成 7 阶段
1 h
防止再退化
问你两件事：

先修 P0 两个 bug 吗？（10+15 min，立刻让页面不再 freeze、续跑不再骗人）
AI 军团 UI 大改，方向你来定一下：
(a) 横向胶囊（agent 头像 + 状态条），保持单线流水，但活起来
(b) 直接复用 Workflow Builder 的 DAG 画布（节点 = agent，连线 = 依赖），让"军团"=一张可视化作战图
(c) 圆形/树形布局，agent 围绕中心 Lead Agent 协作
我个人推荐 P0 全修 + P1 LLM fallback + UI (b) 路线（复用 Workflow Builder 的 SSE 引擎，工作量 1 天，效果最戏剧化，跟"军团"名字最搭）。你说怎么走。

