# Phase 8：统一工作流产品体验

## 目标

Workflow Builder 不再是平行 demo，而是同一条交付引擎的可视化入口。

当前风险是：用户在 UI 上看到“工作流编排”，但后端 runner 和 Pipeline DAG 不是同一套语义。本阶段要统一执行模型，让 Builder 创建的流程也使用同一套状态机、artifact、SSE、失败卡片和恢复机制。

## 输入

- Phase 2 的强状态机。
- Phase 3 的 Artifact Contract。
- Phase 6/7 的真实证据链。
- 当前 Workflow Builder 和 workflow runner。

## 统一原则

- Builder 只是 Delivery Workflow 的可视化入口。
- 所有节点必须映射到 Orchestrator Kernel 的 stage 或 tool action。
- 所有节点输出必须写 artifact 或 evidence。
- 所有节点失败必须进入统一失败卡片。
- 不允许 UI 有节点、后端只是 stub。

## 任务拆分

### 1. 合并执行语义

统一：

- saved workflow runner
- DAG pipeline
- smart-run / auto-run
- slash command workflow

最终都应进入同一套 Orchestrator Kernel。

### 2. 实现真实 tool 节点

`tool` 节点必须真正调用工具：

- commands
- filesystem
- browser
- GitHub
- deploy

### 3. 实现知识检索节点

`knowledge_retrieve` 必须接入：

- Task Context
- Artifact Context
- Memory Context
- Uploaded Context

### 4. 实现 loop 节点

`loop` 节点必须有：

- 最大迭代次数。
- 退出条件。
- 每轮 artifact/evidence。
- 失败原因。

### 5. UI 展示统一

Builder 运行态显示：

- 当前节点。
- 当前 stage。
- artifact 状态。
- evidence 状态。
- 失败卡片。
- retry/resume/cancel 动作。

## 可能涉及文件

- `backend/app/services/workflow_runner.py`
- `backend/app/services/dag_orchestrator.py`
- `backend/app/services/pipeline_engine.py`
- `backend/app/services/task_lifecycle.py`
- `backend/app/api/workflows.py`
- `src/views/Workflow.vue`
- `src/stores/workflows.ts`
- `src/views/PipelineTaskDetail.vue`

## 强制产物

- Workflow node 到 DeliveryStage 的映射表。
- 真 tool node 执行能力。
- knowledge retrieve 真检索能力。
- loop 有限迭代能力。
- Builder 运行态失败卡片。

## 验收标准

- 用户从 Builder 创建的流程，和普通一句话任务使用同一套状态机。
- Builder 流程能产生同一套 artifact。
- Builder 流程能复用 SSE 和失败恢复。
- 不再出现 UI 上有节点、后端只是 stub 的情况。

## 风险

- 过早重做 Builder 会拖慢 Hero Path。
- Builder 应在核心交付引擎稳定后再统一。
- 如果试图支持任意复杂图，会破坏 MVP 成功率。

## 执行完成标志

当 Builder 创建的固定 Hero Path 流程和一句话任务产生同样的 artifact/evidence/状态体验，本阶段完成。
