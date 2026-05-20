# Phase 3：Artifact Contract（可交付版）

## 完成状态

本节实现 **Phase 3 可交付版**（主干 contract + UI + 契约元数据；PRD 内部键级 schema 仍可增强）：

- **`backend/app/services/artifact_contract.py`**  
  - **强制**：线性阶段 → 必需 `TaskArtifact`；`validate_stage_artifact_contract` 只认 `is_latest` + `active` + 非空正文。  
  - **元数据 / 建议校验**：`ARTIFACT_TYPE_CONTRACT`（`schema_version`=`1.0`）含 `producing_stages`、`consuming_stages`、`content_kind`、`rules`（`min_chars`、`json_object`、`markdown_sections`）；命中规则时写入 `validation_errors`，**不单独阻塞** `execute_stage`（与「缺件失败」分离）。  
- **`artifact_contract_enforce`**（默认 `True`）：缺件仍按原逻辑让 `execute_stage` 失败。
- **API**：`GET /api/pipeline/tasks/{id}/artifact-contract`；**分享无鉴权**：`GET /api/share/{token}/artifact-contract`。  
- **`manifest.json`**：`rebuild_manifest` 附带完整 `contract`（含 `definitions`）。  
- **前端**：`ArtifactContractPanel.vue` 挂在 `TaskArtifactTabs`（任务详情「交付物」）与 `SharePage`（紧凑模式）；`fetchTaskArtifactContract` / `fetchShareArtifactContract`（`pipelineApi.ts`）；i18n `artifactContract.*`（zh/en/ja/ko）。  
- **测试**：`test_phase3_artifact_contract.py`（含公开 share contract）；Hero Path 含 `ops_runbook` 与 `all_required_satisfied`。

PRD 内嵌键（`user_stories` 等）的严格 JSON Schema、以及「建议校验」上升为执行硬门禁，仍可后续迭代。

- **验证**：以当前分支 `pytest tests/` 全绿为准。

---

# Phase 3：定义 Artifact Contract

## 目标

每个阶段必须交结构化产物，不合格不能过。

Artifact 不能只是展示数据，而要成为阶段通过条件。下游 Agent 不能靠读自然语言猜测上游意图，而要读取明确的 contract。

## 输入

- Phase 2 的阶段状态机。
- 当前 `TaskArtifact` v2 系统。
- 当前 artifact writer 和 manifest sync。
- 当前任务详情页和分享页。

## 合同总览

### PRD

必须包含：

- `brief`
- `user_stories`
- `acceptance_criteria`
- `scope`
- `non_goals`

### 设计

必须包含：

- `ui_spec`
- `design_tokens`
- `screen_list`
- `ui_mockup_png`
- `ui_mockup_html`

### 架构

必须包含：

- `architecture`
- `architecture_diagram`
- `api_contract`
- `data_model`
- `file_plan`

### 开发

必须包含：

- `source_files`
- `source_manifest`
- `code_link`
- `build_command`
- `run_command`

### 测试

必须包含：

- `test_report`
- `build_log`
- `test_log`
- `screenshot`
- `qa_result`

### 部署

必须包含：

- `deploy_manifest`
- `preview_url`
- `health_check`
- `rollback_plan`

### 验收

必须包含：

- `acceptance_result`
- `criteria_result`
- `reject_to_stage` 或 `approved`
- `delivery_summary`

## 任务拆分

### 1. 定义 contract schema

每类 artifact 都要有 schema：

- required fields
- artifact type
- producing stage
- consuming stage
- validation rule

### 2. 改造 artifact writer

`write_stage_artifacts_v2` 不应只写 Markdown，还应写结构化 metadata。

### 3. 改造 manifest

`manifest.json` 应从 DB source of truth 重建，包含：

- artifact status
- version
- path
- evidence references
- producing stage

### 4. 改造 UI 展示

任务详情页需要展示：

- artifact 完整度。
- 每类 artifact 是否缺失。
- 缺失导致哪个阶段失败。

分享页需要展示：

- 完整交付证据。
- 缺失项不能伪装为完成。

## 可能涉及文件

- `backend/app/models/task_artifact.py`
- `backend/app/services/artifact_writer.py`
- `backend/app/services/manifest_sync.py`
- `backend/app/api/task_artifacts.py`
- `backend/app/api/deliverables.py`
- `backend/app/api/share.py`
- `src/components/task/TaskArtifactTabs.vue`
- `src/components/task/ArtifactCompletionBar.vue`
- `src/views/SharePage.vue`

## 强制产物

- Artifact Contract schema。
- Stage to artifact mapping。
- Contract validation function。
- UI artifact 完整度展示。

## 验收标准

- Artifact 缺失则阶段失败。
- Artifact 不能只是自然语言。
- UI 能显示每个 artifact 的状态。
- 分享页展示的是完整交付证据。
- Hero Path E2E 能断言 artifact contract。

## 风险

- 过早定义过多 artifact 类型会拖慢开发。
- Contract 太宽会失去约束力。
- Contract 太窄会阻塞合理输出。

## 执行完成标志

当任意阶段缺少必需 artifact 时，系统会失败并显示明确缺失项，本阶段完成。
