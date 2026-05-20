# Phase 5 Linear 任务 —— 设计图与架构图强制证据

> 基于 2026-05-19 代码审计。`ui_visualizer.py`(758行)、`image_gen_tool.py`(141行) 已有基础。

---

## EPIC: Phase 5 — 视觉证据强制化

**目标**：Design/Architecture 阶段产出可预览图形，缺失时阻断交付。

**入口**：`docs/analysis/ai-legion-execution/phase-5-visual-and-architecture-evidence.md`

**已有基础**：
- `ui_visualizer.py`: `generate_mockup`(PNG+HTML)、`generate_architecture_diagrams`(Mermaid→HTML)
- `image_gen_tool.py`: `generate_image` 工具函数
- Phase 3 artifact contract 框架可复用

**依赖关系**：
```
5.1 → 5.2
5.1 → 5.3
5.2 + 5.3 → 5.4
5.4 → 5.5
```

---

## Task 5.1 — 设计/架构阶段启动前资源体检

**Priority**: P0
**Estimate**: 2h
**Depends on**: 无

### 背景
当前 Designer/Architect 阶段没有资源可用性检查。如果图片生成 API key 缺失或 Figma MCP 不可用，会静默生成一段 Markdown 文字替代图。

### 验收标准
- [ ] `DesignerAgent` 执行前调用 `_check_visual_resources()` 体检：
  - OpenAI Images key（`OPENAI_API_KEY` + 模型可用性探测）
  - Gemini image（`GEMINI_API_KEY`）
  - 本地 HTML mockup fallback（`ui_visualizer.generate_html_prototype`）
- [ ] `ArchitectAgent` 执行前调用 `_check_diagram_resources()` 体检：
  - Mermaid CLI/线上渲染可用性
  - 本地 HTML 渲染 fallback
- [ ] 全部不可用时 → 阶段状态设为 `blocked`，`scheduler_last_error` 写明缺失资源
- [ ] 部分可用时 → 取可用优先级降级（不阻断）
- [ ] 资源体检结果写入 stage `input_snapshot.metadata.resource_check`

### 涉及文件
- `backend/app/services/pipeline_engine.py`（`execute_stage` 前注入体检）
- `backend/app/services/ui_visualizer.py`（新增 `check_resources`）
- `backend/app/services/tools/image_gen_tool.py`

---

## Task 5.2 — Designer 强制产出 ui_mockup.png 或 ui_mockup.html

**Priority**: P0
**Estimate**: 3h
**Depends on**: Task 5.1

### 背景
`ui_visualizer.py` 已有 `generate_mockup` 方法，但 pipeline 未强制调用。Designer stage 目前可能只输出 Markdown 文字说明。

### 验收标准
- [ ] Designer stage `execute_stage` 固定调用 `ui_visualizer.generate_mockup`（PNG 优先，HTML 降级）
- [ ] 产出写入 `TaskArtifact`：`screenshot` 类型存 PNG，`ui_spec` 类型存 HTML
- [ ] 产出 `design_tokens.json`（颜色、字体、间距），写入 `ui_spec` artifact 的 metadata
- [ ] 产出 `screen_plan.json`（页面列表 + 状态矩阵），写入 `ui_spec` artifact 的 metadata
- [ ] PNG 生成失败但 HTML 可用 → 阶段继续（降级）但 artifact 标注 `mockup_kind: "html_fallback"`
- [ ] PNG 和 HTML 都失败 → 阶段 `failed`
- [ ] Phase 3 artifact contract 更新：Design stage 增加 `ui_mockup_png` 或 `ui_mockup_html` 至少一个为 required

### 涉及文件
- `backend/app/services/ui_visualizer.py`
- `backend/app/services/pipeline_engine.py`
- `backend/app/services/artifact_writer.py`
- `backend/app/services/artifact_contract.py`

---

## Task 5.3 — Architect 强制产出架构图

**Priority**: P0
**Estimate**: 3h
**Depends on**: Task 5.1

### 背景
`ui_visualizer.py` 已有 `generate_architecture_diagrams`（生成 Mermaid flowchart/sequence→HTML）。Architect stage 需要强制产出并写入 artifact。

### 验收标准
- [ ] Architect stage `execute_stage` 固定调用 `ui_visualizer.generate_architecture_diagrams`
- [ ] 产出 `architecture.mmd`（Mermaid 源码，写入 `architecture` artifact 附件）
- [ ] 产出 `architecture.html`（渲染后，写入 `screenshot` 或新 artifact 类型）
- [ ] 产出 `api_contract.json`（REST 端点清单 schema），写入 `architecture` artifact metadata
- [ ] 产出 `data_model.json`（实体关系），写入 `architecture` artifact metadata
- [ ] 产出 `file_plan.json`（目录规划），写入 `architecture` artifact metadata
- [ ] 一致性校验：`api_contract` 的实体名必须在 `data_model` 中对应存在；`file_plan` 的目录名必须在 `api_contract` 中有对应的路由分组
- [ ] 校验失败 → 阶段 `failed`，错误信息列出不一致项
- [ ] Phase 3 artifact contract：Architecture stage required 增加 `architecture_diagram`

### 涉及文件
- `backend/app/services/ui_visualizer.py`
- `backend/app/services/pipeline_engine.py`
- `backend/app/services/artifact_contract.py`

---

## Task 5.4 — 前端任务详情/分享页展示设计图和架构图

**Priority**: P1
**Estimate**: 3h
**Depends on**: Task 5.2, Task 5.3

### 背景
Phase 3 已有 `ArtifactContractPanel` 和 8-Tab 视图。TaskDocTab 渲染 Markdown，但图片/HTML mockup 无法内嵌预览。

### 验收标准
- [ ] `TaskDocTab` 新增「设计预览」区域：渲染 `ui_mockup.html`（iframe sandbox）或显示 `ui_mockup.png`
- [ ] `TaskDocTab` 新增「架构预览」区域：渲染 `architecture.html`（Mermaid 图）
- [ ] 图片缺失时显示占位状态：「设计图尚未生成」
- [ ] `SharePage` 同步展示（复用同组件或同逻辑）
- [ ] 图加载失败时显示降级文字链接（不白屏）
- [ ] i18n 覆盖 zh/en：`artifactContract.uiMockup` / `artifactContract.architectureDiagram` / `artifactContract.notGeneratedYet`

### 涉及文件
- `src/components/task/TaskDocTab.vue`
- `src/components/task/TaskArtifactTabs.vue`
- `src/views/SharePage.vue`
- `src/i18n/zh.ts` / `src/i18n/en.ts`

---

## Task 5.5 — Hero Path E2E 增加视觉证据断言

**Priority**: P0
**Estimate**: 1.5h
**Depends on**: Task 5.4

### 验收标准
- [ ] `test_hero_delivery_path.py` 增加：
  - `test_design_stage_produces_mockup`：断言 Design 阶段产出至少一种 UI 图 artifact
  - `test_architecture_stage_produces_diagram`：断言 Architecture 阶段产出 `architecture_diagram`
- [ ] 新增 `backend/tests/test_phase5_visual_evidence.py`：
  - `test_missing_mockup_fails_design`：验证无 UI 图时 Design 阶段标为 failed
  - `test_missing_diagram_fails_architecture`：验证无架构图时 Architecture 阶段标为 failed
  - `test_resource_check_blocks_when_all_unavailable`：验证全部资源不可用时的 blocked 状态
- [ ] 测试允许 mock UI visualizer（不调用真实图片 API）

### 涉及文件
- `backend/tests/test_hero_delivery_path.py`
- `backend/tests/test_phase5_visual_evidence.py`（新增）

---

## 跨 Phase 依赖

| 依赖 | 来源 | 状态 |
|------|------|------|
| Artifact Contract | Phase 3 | ✅ 完成 |
| ui_visualizer.py (758行) | 已有 | ⚠️ 需对接 pipeline |
| image_gen_tool.py (141行) | 已有 | ✅ 可直接用 |
| ArtifactContractPanel.vue | Phase 3 | ✅ 可直接扩展 |

## Phase 5 完成标志

> Hero Path 任务详情页和分享页能直接看到 UI 效果图和架构图。
> 图缺失时 Design/Architecture 阶段标记 failed，交付不能完成。
