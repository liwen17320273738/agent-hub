ave 5 整套已落地，闭环打通。下面是这次「在飞书/QQ 发任务 → 完成需求 → 成功上线」全链路的完成清单：

落地概览
G1 · e2e_orchestrator 增加 pause_for_acceptance 闸门
backend/app/services/e2e_orchestrator.py

新参数 pause_for_acceptance: bool = False
DAG 阶段执行前暂时翻转 auto_final_accept=True，让设计/评审 DAG 跑完不在中途停；e2e 自己在 Phase 5.5 之后接管"是否上线"决策
当 pause_for_acceptance=True 时：
状态写入 awaiting_final_acceptance 而不是 done
推送 SSE pipeline:awaiting-final-acceptance（带预览 URL、阶段数、质量分）
不再走"已上线"通知，改发"等待最终验收"卡片
G2 · final_accept_task / final_reject_task 联动 IM
backend/app/api/pipeline.py

接受 → 自动从 PipelineArtifact 中提取最近一次 deployment URL，回推「✅ 已上线」卡片到原 IM 频道
打回（带阶段）→ 回推「🔄 重新处理中」
打回（暂停）→ 回推「❌ 任务失败」并提示等待人工
G3 · notify dispatcher + 飞书/Slack 验收卡片
backend/app/services/notify/feishu_im.py：新增 final_acceptance_buttons(task_id)（✅ 接受交付 / ↩ 打回重做）
backend/app/services/notify/slack.py：新增 final_acceptance_buttons(task_id)
backend/app/services/notify/dispatcher.py：新增 awaiting_acceptance 事件类型，飞书/QQ/Slack 三端各自渲染合适样式与提示语
G4 · 飞书/Slack webhook 路由 final_accept / final_reject 按钮
backend/app/services/feishu_event.py + notify/slack.py：extract_card_action 现在透传 task_id
backend/app/api/gateway.py · _handle_plan_card_action：在 plan_session 检查之前优先识别 final_accept / final_reject，直接走 _apply_final_acceptance_from_im
Slack 交互回执也补了 "✅ 已接受验收" / "↩ 已打回" 两个 ack
G5 · 关键词分流 + _apply_final_acceptance_from_im
backend/app/api/gateway.py

新增 _FINAL_ACCEPT_KEYWORDS / _FINAL_REJECT_KEYWORDS + _classify_final_acceptance_intent
"通过/上线/lgtm/ok/可以/接受/ship/release..." → accept
"重做/打回/不行/改/调整/回炉/redo/rework..." → reject
混合时 reject 优先——避免误上线
_try_parse_feedback：先探测目标任务状态，若处于终点则路由到 acceptance API；不在终点的回复才走旧的 feedback_loop
_apply_final_acceptance_from_im：复刻 final-accept/final-reject 的状态机
支持 @stage:xxx 提取重做起点，否则暂停等待人工
接受/打回各自回推 IM 确认卡片
G6 · OpenClawIntakeRequest 暴露 autoFinalAccept
_run_pipeline_background 新增 keyword-only pause_for_acceptance=True（默认对 IM 任务暂停）
OpenClawIntakeRequest.autoFinalAccept: bool = False：受信任的自动化可以一键关掉人类闸门，直接上线
测试
新增 backend/tests/test_im_final_acceptance.py — 13 个用例全绿：

关键词分类（accept / reject / 混合 reject 优先 / 未知）
_apply_final_acceptance_from_im 三条路径（接受、打回-暂停、@stage: 打回-重跑下游、未知阶段降级到暂停）
状态守卫：未在终点的任务不能被 IM 接受
_try_parse_feedback 短路到 acceptance（旧 feedback_loop 不会被误触发）
飞书/Slack 按钮 → 状态机（接受、打回、缺 task_id 防御）
汇总 tests/test_acceptance_endpoints.py + test_im_final_acceptance.py：25 passed in 5.96s ✅ 全量 tests/：273 passed，3 个失败是与 wave 5 无关的历史 flake（test_observability::test_traces_list 等，git stash 后基线复现同样错误）。

端到端剧本（现在能演示了）
用户在飞书发：「做一个待办应用」
   ↓
OpenClaw 网关 → clarifier → planner → 用户回复「开干」
   ↓
_run_pipeline_background(pause_for_acceptance=True) ← G6
   ↓
DAG: planning → architecture → ...（Wave 4 自愈、质量门照常工作）
   ↓
codegen → build/test/fix → 部署到 vercel preview
   ↓
post-deploy acceptance（带 URL+截图给 reviewer-agent 浏览验证）
   ↓
任务停在 awaiting_final_acceptance ← G1
   ↓
飞书弹卡：🏁 等待最终验收 + 预览链接 + ✅接受 / ↩ 打回 ← G3
   ↓
用户点「✅ 接受交付」 OR 直接回复「通过」/「上线」 ← G4 / G5
   ↓
final_accept_task → status=done, final_acceptance_status=accepted ← G2
   ↓
飞书回推「✅ 已上线，干得漂亮」+ deploy URL
打回路径同样闭环：用户点「↩ 打回」或回复 重做：登录页崩了 @stage:draft，从 draft 阶段开始重跑，research 不动；打回后会再次触发 awaiting_acceptance 卡片。

唯一需要外部联调的点是飞书 / QQ / Slack 真实 webhook（验签 + token），代码层闭环已完整。运行环境只要配好 feishu_app_id/secret + verification_token + 部署平台 token，就可以现场演示「手机发任务 → 自动跑 → IM 一键确认 → 上线」。

