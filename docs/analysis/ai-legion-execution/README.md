# AI Legion Execution Plan

日期：2026-05-13

来源：`docs/analysis/2026-5-13-03.md`

本目录把总分析文档拆成可执行阶段文档。后续开发不再继续泛化讨论，而是按 Phase 顺序推进，每一阶段都必须有明确产物和验收结果。

## 执行原则

- 先跑通唯一 Hero Path，再扩展更多 Agent、模板、模型、MCP。
- 每个阶段只解决一个主问题，避免同时重构所有系统。
- 每个阶段都必须输出可检查产物。
- 没有证据不能进入下一阶段。
- 文档、代码、测试、UI 必须围绕同一条主路径服务。

## 阶段列表

| Phase | 文档 | 目标 |
|---|---|---|
| 0 | `phase-0-freeze-hero-path.md` | 冻结范围，定义唯一 Hero Path |
| 1 | `phase-1-hero-path-e2e.md` | 建立 Hero Path E2E 测试，让失败可见 |
| 2 | `phase-2-durable-state-machine.md` | 把 Pipeline 改成强状态机和可恢复流程 |
| 3 | `phase-3-artifact-contract.md` | 定义每阶段 Artifact Contract |
| 4 | `phase-4-golden-code-template.md` | 固定 Vue/Vite 黄金代码生成模板 |
| 5 | `phase-5-visual-and-architecture-evidence.md` | 把 UI 图和架构图变成强制证据 |
| 6 | `phase-6-real-qa-browser-validation.md` | 引入真实测试、构建和浏览器验证 |
| 7 | `phase-7-preview-deploy-closure.md` | 部署/预览链接闭环 |
| 8 | `phase-8-unified-workflow-experience.md` | 统一 Workflow Builder 与交付引擎体验 |

## 推荐执行顺序

1. Phase 0：先冻结范围。
2. Phase 1：先写失败可见的 Hero Path E2E。
3. Phase 2：让流程状态可恢复。
4. Phase 3：收紧 artifact 合同。
5. Phase 4：稳定代码生成黄金模板。
6. Phase 6：引入真实测试和浏览器证据。
7. Phase 5：补强 UI 图和架构图证据。
8. Phase 7：补齐 preview/deploy URL。
9. Phase 8：最后统一 Workflow Builder 体验。

Phase 5 和 Phase 6 可以根据资源情况调整顺序。若视觉模型/Figma 资源暂缺，先完成 Phase 6 更能提升主路径成功率。

## 执行进度

| Phase | 状态 |
|---|---|
| 1 | ✅ 已实现 `backend/tests/test_hero_delivery_path.py`，见 `docs/selftest-report.md` 本节说明 |
| 2 | ✅ 深化：`POST .../cancel-queue`（queued + 等槽位协作取消）、`failed`/`error` 下 linear `resume`、`FailureCard` 识别 `error`/`blocked`、任务详情恢复按钮与 `retry-stage` API 对齐；详见 `phase-2-durable-state-machine.md` |
| 3 | ✅ 可交付版：`artifact_contract.py`、execute_stage 缺件失败、`GET .../artifact-contract`、manifest `contract`；见 `phase-3-artifact-contract.md` |

其余阶段按计划排队；Phase 4 起收紧黄金代码模板与生成物稳定性。

## 暂停扩展清单

Hero Path 成功率达到 80% 前，暂缓：

- 新增更多 Agent 角色。
- 新增复杂 Workflow 模板。
- 新增更多模型面板。
- 新增 MCP 市场化能力。
- 新增多平台部署。
- 扩展移动端、小程序、App Store。
- 做泛化任意代码库改造。
