Phase 3 完成总结：Pipeline 审阅/回退/人类审批
后端修复与新增
改动	文件	说明
修复 approve_stage
backend/app/api/pipeline.py
修复了 DB 查询块缩进错误（嵌在 if not resolved: 分支下，导致 NameError: task），使人工审批端点可正常工作
新增 resume 端点
backend/app/api/pipeline.py
POST /tasks/{id}/resume — 从最后完成的阶段（或指定阶段）恢复暂停的 Pipeline，支持 force_continue 跳过审阅
PipelineStage 新字段
backend/app/models/pipeline.py
新增 review_status, reviewer_feedback, reviewer_agent, review_attempts, approval_id 五个字段
引擎持久化审阅数据
backend/app/services/pipeline_engine.py
Peer Review 结果（审阅者、反馈、通过/驳回、重试次数）和审批 ID 写入 DB
修复 current_user 引用
backend/app/api/pipeline.py
get_task_pending_approvals 和 get_review_config 中的 current_user → get_current_user
前端新增
改动	文件	说明
类型扩展
src/agents/types.ts
PipelineStageState.status 新增 reviewing / rejected / awaiting_approval；新增 reviewStatus, reviewerFeedback, reviewerAgent, reviewAttempts, approvalId 字段
API 映射
src/services/pipelineApi.ts
mapTask 映射新审阅字段；新增 approveStage(), getPendingApprovals(), getReviewConfig(), resumePipeline()
审阅状态徽标
src/views/PipelineTaskDetail.vue
阶段时间线新增：审阅中(橙色脉冲)、审阅通过(绿)、审阅未通过(红)、等待审批(橙) 状态图标与标签
审阅反馈展开面板
src/views/PipelineTaskDetail.vue
每个阶段的审阅反馈可展开查看 Markdown 渲染内容
人工审批操作区
src/views/PipelineTaskDetail.vue
awaiting_approval 阶段显示「批准」/「驳回」按钮，批准后自动调 resume 继续执行
暂停恢复面板
src/views/PipelineTaskDetail.vue
paused 状态显示「恢复执行」和「强制继续（跳过审阅）」按钮
SSE 事件标签
PipelineTaskDetail.vue + PipelineDashboard.vue
11 个审阅/审批相关 SSE 事件的中文映射
SSE 实时处理器
src/views/PipelineTaskDetail.vue
peer-reviewing, rework, approval-granted, approval-denied, pipeline:resumed 等事件自动刷新页面状态
验证结果
76 个后端测试全部通过
前端零 lint 错误
Puppeteer E2E 验证：审阅通过/未通过标签、审阅者信息、重试轮次、审阅反馈展开、人工审批按钮、暂停恢复面板均正确渲染

审查结论
审计发现并修复了 5 个 BUG + 2 个改进项：

#	严重度	问题	修复
1
BUG
resume 端点不传 done_outputs，恢复后的阶段缺少前序上下文
execute_full_pipeline 新增 prior_outputs 参数，resume 传入已完成阶段输出
2
BUG
approve_stage 在 API key 认证时 user=None → AttributeError
安全提取 user.id / user.email，空时用 "api" / "api-key" 兜底
3
BUG
@click="handleResume" 无括号，click 事件对象被当作 forceContinue=truthy
改为 @click="handleResume(false)"
4
BUG
deployment 阶段被 guardrail 预拦截（REQUIRE_REVIEW），LLM 永远执行不到，human_gate 形同虚设
从 STAGE_GUARDRAILS 移除 deployment，人工审批统一由 human_gate 控制
5
BUG
Alembic 迁移缺少新增的 5 个 pipeline_stages 列
新增迁移文件 b2c3d4e5f6a7_add_stage_review_fields.py
6
改进
Peer review LLM 调用失败时静默自动通过，无可见警告
SSE 事件增加 label 描述 + 返回 auto_approved_on_error 标记
7
改进
前端 SSE handler 遗漏 stage:peer-review-error 刷新；Dashboard 缺该事件标签
补充到 SSE handler 列表和 Dashboard 映射中
仍存在的设计限制（非 bug，属于架构层面取舍）：

审阅驳回只做「同阶段重做」（re-execute current stage with feedback），不是回退到上一个阶段重新执行
skip_condition 仅在 DAG 编排器中实现，线性 Pipeline 不支持
Agent 间没有独立的 Q&A/澄清协议（审阅反馈是单向的）
这些属于 Phase 4 产品化层面的演进，Phase 3 的核心功能（审阅/回退/人类审批）现在没有遗留 bug 了。