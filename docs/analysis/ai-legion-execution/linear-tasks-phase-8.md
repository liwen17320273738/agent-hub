# Phase 8 Linear 任务 —— 统一工作流产品体验

> 基于 2026-05-19 代码审计。`workflow_compiler.py`(165行)、`workflow_runner.py`(240行) 存在但与 Pipeline/DAG 是两套独立语义。

---

## EPIC: Phase 8 — Workflow Builder = 交付引擎的可视化入口

**目标**：Workflow Builder 不再平行 demo，而是同一套 Orchestrator Kernel 的可视化入口。

**入口**：`docs/analysis/ai-legion-execution/phase-8-unified-workflow-experience.md`

**核心问题**：
- `workflow_runner.py` 自己跑节点（`run_workflow`），不走 `pipeline_engine.execute_stage`
- `workflow_compiler.py` 的 `CompiledNode` 没有映射到 `PipelineStage`
- Builder 的 `tool`/`knowledge_retrieve`/`loop` 节点是 stub
- 两套系统各自的状态机、artifact、SSE、失败恢复互不感知

**依赖关系**：
```
8.1 → 8.2 → 8.3 → 8.4
```

---

## Task 8.1 — CompiledNode → PipelineStage 映射表 + 统一执行入口

**Priority**: P0
**Estimate**: 3h
**Depends on**: 无（但逻辑依赖 Phase 2 状态机 + Phase 3 artifact contract）

### 背景
当前 `workflow_runner.run_workflow` 独立执行节点，不经过 `pipeline_engine.execute_stage`。需要建立映射，让所有 Workflow 节点走统一状态机。

### 验收标准
- [ ] 定义 `NodeStageMapping` 表（`workflow_compiler.py`）：
  ```python
  NODE_TO_STAGE = {
      "llm": "llm_call",           # 通用 LLM 调用
      "tool": "tool_execution",     # 工具执行
      "http": "api_call",           # HTTP 请求
      "condition": "branch",        # 条件分支（编译期展开为多路径）
      "loop": "loop_iteration",     # 循环迭代
      "knowledge_retrieve": "context_retrieval",  # 知识检索
  }
  ```
- [ ] `workflow_runner.run_workflow` 改为调用 `pipeline_engine.execute_stage` 而非直接调 LLM/HTTP
- [ ] 每个 Workflow 节点执行时创建对应的 `PipelineStage` 记录（stage_type 用映射表）
- [ ] Builder 创建的 saved workflow 和一句话任务使用**同一个** `PipelineTask` 创建入口
- [ ] 保留 `workflow_runner` 作为 thin adapter（不做新逻辑，只做映射+调用）

### 涉及文件
- `backend/app/services/workflow_compiler.py`
- `backend/app/services/workflow_runner.py`
- `backend/app/services/pipeline_engine.py`
- `backend/app/api/workflows.py`

---

## Task 8.2 — tool 节点真实化

**Priority**: P0
**Estimate**: 3h
**Depends on**: Task 8.1

### 背景
Builder 中的 `tool` 节点只是一个 label + config，没有真正调用工具注册表。需要让 tool 节点映射到 `tools/registry.py` 中的实际工具。

### 验收标准
- [ ] `tool` 节点执行时从 `tool_schema.py` 或 `tools/registry.py` 查找对应工具
- [ ] 支持以下工具节点（Hero Path MVP 首先支持前 4 个）：
  - `file_write` — 写文件
  - `bash` — 执行命令
  - `browser` — 浏览器操作
  - `github` — GitHub 操作（PR/commit）
  - `deploy` — 部署触发
- [ ] tool 节点执行结果写入 artifact（`tool_execution` 类型或 `attachment`）
- [ ] tool 失败 → 节点 stage 标记 `failed`，走统一 FailureCard

### 涉及文件
- `backend/app/services/workflow_runner.py`
- `backend/app/services/tools/registry.py`
- `backend/app/services/tool_schema.py`

---

## Task 8.3 — knowledge_retrieve 节点真实化

**Priority**: P1
**Estimate**: 2h
**Depends on**: Task 8.1

### 背景
`knowledge_retrieve` 节点当前是 stub。需要接入真实的上下文检索：Task Context、Artifact Context、Memory Context、Uploaded Context。

### 验收标准
- [ ] `knowledge_retrieve` 节点配置支持 `sources` 字段：
  ```json
  { "sources": ["task_context", "artifact_context", "memory_context", "uploaded_context"] }
  ```
- [ ] 执行时从对应 source 检索内容：
  - `task_context` → `memory.py` 的 `get_context_from_history`
  - `artifact_context` → `manifest_sync.py` 的 `rebuild_manifest`
  - `memory_context` → `memory.py` 的 `retrieve_patterns`
  - `uploaded_context` → 任务附件表
- [ ] 检索结果写入 node output artifact（`context_retrieval` 类型 markdown）
- [ ] 检索失败不阻断流程（warning 级别），输出空上下文提示

### 涉及文件
- `backend/app/services/workflow_runner.py`
- `backend/app/services/memory.py`
- `backend/app/services/manifest_sync.py`

---

## Task 8.4 — loop 节点有限迭代

**Priority**: P1
**Estimate**: 2.5h
**Depends on**: Task 8.1

### 背景
Builder 的 `loop` 节点只有 UI 形态，后端缺少迭代控制和退出条件。

### 验收标准
- [ ] `loop` 节点支持配置：
  ```json
  {
    "max_iterations": 5,
    "exit_condition": { "field": "status", "operator": "equals", "value": "done" },
    "sub_nodes": ["node_a", "node_b"]
  }
  ```
- [ ] 每轮迭代：
  - 记录 iteration index
  - 执行 sub_nodes（按拓扑序）
  - 检查 exit_condition（从上一轮最后节点 output 取值）
  - 写入 iteration artifact（`loop_iteration_{n}`）
- [ ] 达到 `max_iterations` 仍未满足 exit_condition → 节点 `failed`，记录 `loop_exhausted`
- [ ] 迭代中途某 sub_node 失败 → 节点 `failed`，保留已完成的迭代 artifact

### 涉及文件
- `backend/app/services/workflow_runner.py`
- `backend/app/services/workflow_compiler.py`

---

## Task 8.5 — 前端 Workflow Builder 运行态展示统一状态

**Priority**: P1
**Estimate**: 3h
**Depends on**: Task 8.1

### 背景
当前 Builder 有视觉节点但运行时不显示真实状态/artifact/失败卡片。需要和 `PipelineTaskDetail` 复用同一套 SSE 和状态组件。

### 验收标准
- [ ] Builder 运行态（`WorkflowRunView`）复用 SSE 通道：`agenthub:pipeline:events`
- [ ] 每个节点显示：
  - 当前状态（pending/running/succeeded/failed）
  - artifact 状态（从 `ArtifactContractPanel` 逻辑复用）
  - evidence 状态
- [ ] 节点失败时内嵌 `FailureCard`（复用 `FailureCard.vue`，含 retry/resume/cancel）
- [ ] 点击节点展开节点详情（stage input/output）
- [ ] 不再出现"UI 上有节点但后端 stub"的情况——每个 Builder 节点类型都有对应后端实现

### 涉及文件
- `src/views/Workflow.vue`
- `src/components/task/FailureCard.vue`
- `src/components/task/ArtifactContractPanel.vue`
- `src/stores/workflows.ts`

---

## Task 8.6 — Hero Path E2E 覆盖 Builder → 执行 → 交付闭环

**Priority**: P0
**Estimate**: 2h
**Depends on**: Task 8.1-8.4

### 验收标准
- [ ] 新增 `backend/tests/test_phase8_unified_workflow.py`：
  - `test_builder_creates_same_artifacts_as_one_sentence`：Builder 创建的 Hero Path 流程和一句话任务产生同一套 artifact/状态机/SSE
  - `test_loop_node_exhaustion`：loop 达到 max_iterations 后正确失败
  - `test_tool_node_real_execution`：tool 节点真实调用了工具
- [ ] 更新 `test_hero_delivery_path.py`：增加参数化 fixture，验证 `one_sentence` 和 `builder` 两种创建方式产生相同交付包

### 涉及文件
- `backend/tests/test_phase8_unified_workflow.py`（新增）
- `backend/tests/test_hero_delivery_path.py`

---

## 跨 Phase 依赖

| 依赖 | 来源 | 状态 |
|------|------|------|
| Pipeline 状态机 | Phase 2 | ✅ 完成 |
| Artifact Contract | Phase 3 | ✅ 完成 |
| SSE pub/sub | Phase 2 | ✅ 完成 |
| FailureCard.vue | Phase 2 | ✅ 完成 |
| workflow_compiler.py (165行) | 已有 | ⚠️ 需重构 |
| workflow_runner.py (240行) | 已有 | ⚠️ 需重构 |
| tools/registry.py | 已有 | ✅ 可直接用 |
| memory.py | 已有 | ✅ 可直接用 |

## Phase 8 完成标志

> Builder 创建的 Hero Path 流程和一句话任务产生相同的 artifact/evidence/状态体验。
> Builder 不再是单独 demo，而是同一条交付引擎的可视化入口。
