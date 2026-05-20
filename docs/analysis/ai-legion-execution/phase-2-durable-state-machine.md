# Phase 2：Pipeline 耐久状态线索

## 目标

让流程断了也能知道、能恢复、能重试。

当前问题不是“流程会失败”，而是失败后用户不知道断在哪里，系统也不能可靠恢复。本阶段先完成一个可交付版本：把调度器运行状态写回数据库，并在阶段推进时记录输入快照，让后台执行不再只是不可见的内存协程。

> 独立 DeliveryRun 表 / 对已启动协程的任务级强行中止（无协作点）仍在后续范围。当前本轮已补齐：**队列内 run 的可信撤销**（含等并发槽）、**failed/error 下的 linear resume + UI**、以及与既有 retry-stage / resume-dag 组合的恢复路径。

## 完成状态

状态：已完成 Phase 2 **深化版**（在可交付版之上补齐 resume/retry/cancel-queue 产品与测试）。

已落地：

- `PipelineTask` 增加 scheduler 运行线索：`scheduler_run_submission_id`、`scheduler_run_kind`、`scheduler_run_started_at`、`scheduler_run_finished_at`、`scheduler_last_error`。
- `PipelineStage` 增加 `input_snapshot`，在 `/api/pipeline/tasks/{id}/advance` 激活下一阶段时写入结构化 handoff。
- `TaskScheduler` 在任务开始、成功、失败时通过独立 DB session 更新 task 运行线索。
- 新增 Alembic 迁移 `h9a0b1c2d3e4_add_scheduler_and_stage_snapshot.py`。
- 合并 Alembic 双 head：`42959d437fcc_merge_scheduler_snapshot_and_pipeline_.py`。
- 新增回归测试 `backend/tests/test_phase2_durable_cues.py`。
- Phase 2 深化：`TaskScheduler.cancel_queued_for_task`（协作取消等槽位 submission）、API ``cancel-queue``、线性 ``resume`` 支持 ``failed``/``error``、任务详情失败态按钮与 ``FailureCard`` 对 ``error``/``blocked`` 的识别；单测见 `backend/tests/unit/test_task_scheduler.py`（``cancelled`` 生命周期字段）。

验证结果：

- `cd backend && python3 -m pytest tests/test_phase2_durable_cues.py -v --tb=short`：5 passed（含 `cancel-queue` HTTP 形状用例）。
- `cd backend && python3 -m pytest tests/unit/test_task_scheduler.py -v --tb=short`：覆盖 `cancelled` 生命周期与合作式取消等行为。
- `cd backend && PYTHONPATH=. python3 -m alembic heads`：单一 head（以当前仓库迁移为准）。

## 输入

- Phase 1 的 Hero Path E2E 测试。
- 当前 PipelineTask / PipelineStage 模型。
- 当前 scheduler / DAG / pipeline engine 实现。
- 当前失败卡片和 SSE 状态展示。

## 状态定义

完整强状态机最终应支持：

- `pending`
- `running`
- `succeeded`
- `failed`
- `blocked`
- `retrying`
- `awaiting_user`
- `cancelled`

## 任务拆分

### 1. 定义 DeliveryRun / DeliveryStage 概念

当前完成度：部分完成。没有新增独立表，但在现有 `PipelineTask` / `PipelineStage` 中补上了 run 线索和阶段输入快照。

如果不新增表，也必须在现有模型中表达：

- run id
- task id
- current stage
- stage input snapshot
- stage output artifact ids
- stage evidence ids
- retry count
- failure reason

### 2. 持久化阶段输入输出

当前完成度：部分完成。阶段输入快照已保存；artifact ids、evidence ids、model policy 和资源检查结果仍留到 Phase 3/后续强状态机深化。

每个阶段启动前：

- 保存输入快照。
- 保存使用的 model policy。
- 保存可用资源检查结果。

每个阶段完成后：

- 保存 artifact ids。
- 保存 evidence ids。
- 保存 gate result。

### 3. 去掉默认假完成策略

当前完成度：未纳入本次 Phase 2 可交付版。该项会影响主执行语义，建议放到 Artifact Contract 和真实 QA 阶段一起收紧。

`force_continue=True` 只能用于调试模式。

生产主路径中：

- artifact 缺失必须失败。
- evidence 缺失必须阻断。
- 失败不能静默跳过。

### 4. 增加 resume API

当前完成度：**深化已实现（API + UI 可操作）**。说明：

- ``POST /api/pipeline/tasks/{id}/retry-stage/{stage_id}``：单阶段复位并由网关线性后台重跑（既有端点）。
- ``POST /api/pipeline/tasks/{id}/resume``：线性流水线续跑（既有）；现已允许任务状态为 ``failed`` / ``error`` 时调用，并重置剩余阶段中非 ``done`` 的 ``failed`` / ``error`` / ``blocked`` 等为 ``pending``。
- ``POST /api/pipeline/tasks/{id}/resume-dag``：DAG 断点续跑（既有）。
- ``POST /api/pipeline/tasks/{id}/cancel-queue``：**新增**——取消该任务在全局调度器中**尚未执行**（含等并发槽位的）submission；对已拿到槽位正在跑的协程**不强行中止**，在响应体的 ``stillRunning`` 中提示。
- **skip stage**（仅调试或管理员）：仍建议单独门禁，未在本轮实现。

### 5. 统一失败卡片

当前完成度：**部分深化**。后端已有 `scheduler_last_error`、`last_error`、`retry_count` 等数据源；任务详情失败/错误态已提供可操作恢复按钮；结构化 ``stuck_where`` / RCA 话术可与 Wave-5 RCA 报表继续对齐。

失败卡片字段：

- stuck_where
- why
- owner
- next_step
- retry_action
- required_resource

## 可能涉及文件

- `backend/app/models/pipeline.py`
- `backend/app/services/task_lifecycle.py`
- `backend/app/services/task_scheduler.py`
- `backend/app/services/pipeline_engine.py`
- `backend/app/services/dag_orchestrator.py`
- `backend/app/api/pipeline.py`
- `src/components/task/FailureCard.vue`
- `src/views/PipelineTaskDetail.vue`

## 强制产物

- 阶段状态定义：保留为目标定义。
- 阶段输入快照：已完成。
- 调度器运行线索：已完成。
- 阶段输出 artifact 引用：转入 Phase 3。
- resume / retry API：已完成深化（含失败任务线性 resume）。
- cancel-queue API（Queued run 撤销；非协作中止 in-flight）：已完成。
- 可操作失败卡片：任务详情失败/错误态已提供「线性恢复 / DAG 检查点 / 移除队列 / 重试阶段」；（RCA「统一失败卡片文案」仍可继续 polishing）。

## 验收标准

- 后台任务成功后，`scheduler_run_submission_id` 清空，`scheduler_run_finished_at` 写入，`scheduler_last_error` 为空。
- 后台任务失败后，`scheduler_run_submission_id` 清空，`scheduler_last_error` 写入可排查错误。
- 阶段通过 `/advance` 进入下一阶段时，下一阶段保存 `input_snapshot`。
- Alembic 迁移只有一个 head。
- Phase 2 focused tests 和 backend 全量测试通过。

## 风险

- 状态机改造会影响现有 auto-run / smart-run 行为。
- 如果为了兼容旧路径继续保留大量 fallback，会削弱阶段门禁。
- 前端和后端状态命名必须统一，否则用户体验会继续断裂。

## 执行完成标志

当一次故意失败的调度任务能在 DB 中留下可排查错误，并且阶段推进能留下可复盘输入快照，本阶段可交付版完成。

后续仍可加强：对已占用并发槽位的 in-flight pipeline 的可信 **协作式取消**（需持有 ``asyncio.Task`` 或可中断检查点）；以及与管理员工具链打通的 skip-stage。
