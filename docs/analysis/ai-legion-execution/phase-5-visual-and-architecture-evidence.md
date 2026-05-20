# Phase 5：把设计图和架构图变成强制证据

## 目标

从“写设计说明”升级为“产出可看图形”。

用户要的是 UI 设计图和架构图，不是只有 Markdown 的说明。本阶段要让图形 artifact 成为强制证据，缺失时不能标记交付完成。

## 输入

- Phase 3 的 Artifact Contract。
- 当前 Designer Agent 和 UI Visualizer。
- 当前 image generation / Figma / Mermaid 能力。
- 当前任务详情页和分享页。

## 设计图要求

Designer Agent 必须产出至少一种可预览 artifact：

- `ui_mockup.png`
- `ui_mockup.html`
- Figma frame link 或 export

设计图必须覆盖：

- 至少一个核心页面。
- loading / empty / error / success 等关键状态，MVP 可先覆盖核心状态。
- 设计 token。
- screen list。

## 架构图要求

Architect Agent 必须产出：

- `architecture.mmd`
- `architecture.html`
- `architecture.md`
- `api_contract.json`
- `data_model.json`
- `file_plan.json`

Mermaid 渲染成功不等于架构正确，还必须和 API/data/file plan 做一致性检查。

## 任务拆分

### 1. 资源体检

设计阶段启动前检查：

- OpenAI Images key 是否可用。
- Gemini image 是否可用。
- Figma / Design MCP 是否可用。
- 本地 HTML mockup fallback 是否可用。

如果资源缺失：

- 阶段进入 `blocked` 或 `awaiting_user`。
- 明确提示缺什么。
- 不允许静默生成文字替代图。

### 2. UI mockup 生成

优先级：

1. Figma / Design MCP。
2. 图片生成模型。
3. HTML prototype + browser screenshot。

### 3. 架构图生成

流程：

1. Architect 输出结构化架构数据。
2. 生成 Mermaid。
3. 渲染 HTML。
4. 校验 API/data/file plan 一致性。

### 4. UI 展示

任务详情页和分享页都要能直接预览：

- UI 图。
- 架构图。
- 缺失状态。

## 可能涉及文件

- `backend/app/services/pipeline_engine.py`
- `backend/app/services/ui_visualizer.py`
- `backend/app/services/artifact_writer.py`
- `backend/app/services/manifest_sync.py`
- `backend/app/services/tools/registry.py`
- `src/components/task/TaskDocTab.vue`
- `src/components/task/TaskArtifactTabs.vue`
- `src/views/PipelineTaskDetail.vue`
- `src/views/SharePage.vue`

## 强制产物

- `ui_mockup.png` 或 `ui_mockup.html`
- `design_tokens.json`
- `screen_plan.json`
- `architecture.mmd`
- `architecture.html`
- `api_contract.json`
- `data_model.json`
- `file_plan.json`

## 验收标准

- 任务详情页能直接看到 UI 图和架构图。
- 分享页能看到图。
- 图缺失时，交付不能标记完成。
- 视觉资源缺失时，系统进入明确 blocked 状态。

## 风险

- 图片生成依赖 API key，容易因资源缺失阻断。
- Figma MCP 可用性和权限需要提前体检。
- HTML mockup fallback 可以提高稳定性，但要避免假装等同设计稿。

## 执行完成标志

当一个 Hero Path 任务能稳定产出可预览 UI 图和架构图，本阶段完成。
