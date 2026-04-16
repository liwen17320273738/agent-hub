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