# Phase 4 Linear 任务 —— 黄金代码模板

> 此文件已根据 2026-05-19 代码审计 + 决策更新：
> - Element Plus → 轻量自研组件
> - pnpm 统一
> - `source_manifest` / `build_log` 新增为 ArtifactTypeRegistry 类型

---

## EPIC: Phase 4 — 黄金代码模板稳定化

**目标**：Developer Agent 对固定 Vue/Vite 模板的生成 → 构建 → 测试闭环，10 个需求 ≥8 个构建成功。

**入口**：`docs/analysis/ai-legion-execution/phase-4-golden-code-template.md`

**依赖关系**：
```
4.1 → 4.2 → 4.3
     └──→ 4.2a → 4.2b (建议拆分)
4.3 + 4.2 → 4.4
4.3 + 4.2 → 4.5
```

---

## Task 4.1 — 加固 vue-app 模板，确保可独立跑通 install/build/test/preview

**Priority**: P0  
**Estimate**: 3h
**Depends on**: 无

### 背景
`backend/app/services/codegen/templates.py` 已有 `vue-app` 模板，但：
- 缺少 `vitest` 配置和测试入口
- 缺少 `pnpm`/`npm test` 脚本
- `build_cmd` 含 `vue-tsc` 但 tsconfig 缺少 `vueCompilerOptions` 配置
- 全部硬编码在 `templates.py` 字符串中，难以独立抽取验证

### 验收标准
- [ ] 模板产出一份新文件 `packages/agent-hub-pipeline/templates/vue-app/`（取代 `templates.py` 字符串嵌入），`scaffold_project` 改为从目录复制
- [ ] 模板含完整 `vitest` 配置：`vitest.config.ts`（`@vitejs/plugin-vue`）、`src/__tests__/example.spec.ts`
- [ ] `package.json` 脚本含 `"test": "vitest run"`，devDeps 含 `vitest`
- [ ] `build_cmd` 改为 `pnpm install && pnpm build && pnpm test`（统一 pnpm）
- [ ] `tsconfig.json` 追加 `vueCompilerOptions` 解决 `vue-tsc` 报错
- [ ] 不含 Element Plus，改为**空 scoped CSS 样式**（Agent 按需注入组件代码）
- [ ] `pnpm install && pnpm build && pnpm test` 在干净沙箱目录下能独立跑通
- [ ] `pnpm preview` 能启动本地服务器（持续 3s 后 SIGTERM 验证 HTTP 200）

### 涉及文件
- `backend/app/services/codegen/templates.py` （修改 `vue-app` + `scaffold_project` 支持从目录复制）
- `packages/agent-hub-pipeline/templates/vue-app/` （新增目录）
- `backend/app/services/codegen/codegen_agent.py` （适配目录来源）

---

## Task 4.2a — CodeGenAgent 输入输出协议 + source_manifest 写入

**Priority**: P0  
**Estimate**: 3h
**Depends on**: Task 4.1 (模板可独立生成)

### 背景
`codegen_agent.py` 已有 Claude Code bridge 和 `_scan_project_files` 函数，但没有 **标准的输入读取 guard** 和 **结构化的输出产物**。

### 验收标准
- [ ] `generate_from_pipeline` 执行前 guard：若 `planning` 或 `architecture` 的输出为空，直接返回 `ok: false, error: "missing required input"`
- [ ] 生成后调用 `_build_source_manifest(project_dir) → dict`，产出：
  ```json
  {
    "created_files": ["src/App.vue", ...],
    "modified_files": [],
    "build_command": "pnpm install && pnpm build",
    "run_command": "pnpm preview",
    "test_command": "pnpm test",
    "generated_at": "2026-05-19T10:00:00Z"
  }
  ```
- [ ] `source_manifest.json` 写入 `{project_dir}/source_manifest.json`
- [ ] `build.log` 写入 `{project_dir}/build.log`（`run_build` 或 executor stdout 即写即刷）
- [ ] 写入范围限制：`_enforce_allowlist(project_dir, template_baseline)` — 只允许新建/修改 `src/`、`public/`、`package.json`、`vite.config.ts`、`tsconfig.json`、`vitest.config.ts`、`src/__tests__/`。超出文件 → 返回 error（不硬删，但拒绝进入下一阶段）

### 涉及文件
- `backend/app/services/codegen/codegen_agent.py`
- `backend/app/services/executor_bridge.py`

---

## Task 4.2b — 自动修复循环 + 失败状态回传

**Priority**: P0  
**Estimate**: 2h
**Depends on**: Task 4.2a (产出 build.log)

### 背景
当前 `auto_fix` 方法存在但孤立运行，修复结果不会回传 pipeline stage 状态，最大次数与文档不一致。

### 验收标准
- [ ] `auto_fix` 最大次数调整为 **2**（代码 `MAX_FIX_RETRIES=3` → 改为 `2`）
- [ ] 自动修复读取 `build.log`（文件已存在，来自 4.2a）作为错误诊断输入
- [ ] 2 次修复均失败的 case 中，`generate_from_pipeline` 返回：
  ```json
  {
    "ok": false,
    "error": "build_failed_after_2_retries",
    "build_log_summary": "<前 5kB 日志摘要>",
    "pipeline_status": "failed"
  }
  ```
- [ ] pipeline engine 侧（`execute_stage` 或调用方）收到 `ok: false` 后自动将 stage 状态设为 `failed`、写入 `scheduler_last_error`

### 涉及文件
- `backend/app/services/codegen/codegen_agent.py`
- `backend/app/services/pipeline_engine.py`
- `backend/app/services/task_lifecycle.py`

---

## Task 4.3 — source_manifest + build.log 写入 TaskArtifact + artifact contract 升级

**Priority**: P0  
**Estimate**: 2h
**Depends on**: Task 4.2a, Task 4.2b

### 背景
Phase 3 的 artifact contract 只要求 13 种基本类型（brief/prd/ui_spec 等）。Phase 4 需要：
- 新增 `source_manifest` / `build_log` 为正式 artifact 类型
- Development stage 的 contract 将这两项设为 `required`
- QA/Deployment 阶段可依赖这些 artifact 做进一步验证

### 验收标准
- [ ] `ArtifactTypeRegistry` 新增 `source_manifest` 和 `build_log` 两个类型（`task_artifact.py`）
- [ ] 新增 Alembic migration（需合并 Phase 2/3 迁移后的单一 head）
- [ ] Development stage 的 artifact contract（`artifact_contract.py`）将 `source_manifest`、`build_log`、`implementation` 列为 `required`
- [ ] `artifact_writer.py` 新增 `write_code_artifacts(project_dir, task_id)` 自动写入二者
- [ ] `manifest_sync.py` 的 `rebuild_manifest` 读取 `source_manifest.json` 内容并包含在 manifest 中

### 涉及文件
- `backend/app/models/task_artifact.py`
- `backend/app/services/artifact_contract.py`
- `backend/app/services/artifact_writer.py`
- `backend/app/services/manifest_sync.py`
- `backend/alembic/versions/` （新增 migration）

---

## Task 4.4 — 批量验证：10 个固定需求跑分

**Priority**: P0  
**Estimate**: 4h
**Depends on**: Task 4.3

### 背景
Phase 4 验收标准是"10 个固定简单应用需求，≥8 个构建成功"。需要一个可重复运行的评分脚本。

### 验收标准
- [ ] 新增测试文件 `backend/tests/test_phase4_golden_template.py`
- [ ] 10 个固定一句话需求（待办事项、计数器、天气卡片、名言生成器、倒计时、配色工具、笔记列表、番茄钟、书签管理、每日打卡）以 fixture 形式定义
- [ ] 每个需求验证步骤：
  1. 模板 `scaffold` 到沙箱目录
  2. 调用 `CodeGenAgent.generate_from_pipeline`（绕开 LLM，用预置 PRD/architecture 片段或真实输出）-- 这里可以使用预置 good-enough 的 PRD/architecture 文本直接喂入，不依赖 LLM
  3. 断言构建成功、`source_manifest.json` 存在、`build.log` 存在
- [ ] 脚本输出格式：
  ```
  Phase 4 Scorecard
  =================
  1. 待办事项    ✅ PASS (build=ok, manifest=ok, log=ok)
  2. 计数器      ❌ FAIL (build=failed: vue-tsc error)
  ...
  Score: 9/10
  ```
- [ ] 可限制 LLM 调用：mock 模式允许但必须走真实 `pnpm install && pnpm build && pnpm test`

### 涉及文件
- `backend/tests/test_phase4_golden_template.py`
- `backend/app/services/codegen/codegen_agent.py` （可能需要导出 prebuilt PRD/architecture fixture）

---

## Task 4.5 — 前端展示代码交付物

**Priority**: P1  
**Estimate**: 2h
**Depends on**: Task 4.3 (artifact 在 DB 中存在)

### 背景
Phase 3 已有 `ArtifactContractPanel` 和 8-Tab 交付视图。Phase 4 需要在 `TaskCodeTab` 中展示 `source_manifest.json` 和 `build.log`。

### 验收标准
- [ ] `TaskCodeTab` 新增「代码清单」区域：显示文件路径列表（带 `created`/`modified` 徽标）、build/run/test 命令
- [ ] `TaskCodeTab` 新增「构建日志」区域（可折叠面板）
- [ ] 构建失败时日志面板默认展开、标题红色底色、首行高亮错误摘要
- [ ] i18n key 新增（zh/en 覆盖）：
  - `taskCodeTab.sourceManifest` / `taskCodeTab.buildLog`
  - `taskCodeTab.buildFailed` / `taskCodeTab.buildPassed`
  - `taskCodeTab.createdFiles` / `taskCodeTab.buildCommand`

### 涉及文件
- `src/components/task/TaskCodeTab.vue`
- `src/i18n/zh.ts`
- `src/i18n/en.ts`
- `src/i18n/ja.ts`
- `src/i18n/ko.ts`

---

## 跨 Phase 依赖

| 依赖 | 来源 | 状态 |
|------|------|------|
| Artifact Contract | Phase 3 | ✅ 完成 |
| Pipeline 状态机 | Phase 2 | ✅ 完成 |
| Hero Path E2E | Phase 1 | ✅ 完成 |
| Claude Code 执行桥 | executor_bridge.py | ✅ 已有 |
| vue-app 模板 | templates.py | ⚠️ Task 4.1 加固中 |
| `source_manifest` / `build_log` artifact 类型 | 本 Phase | ⚠️ Task 4.3 新增 |
| artifact_writer 多文件写 | 本 Phase Task 4.3 | ⚠️ 新增 |

## 执行顺序建议

```
1. Task 4.1 (模板加固) → 独立验证
   ├── 先改 templates.py，不碰其他文件
   └── 手动验证：create temp dir → scaffold → pnpm install/build/test/preview

2. Task 4.3 (新增 artifact 类型) → 可以并行开始
   └── 只改 model / contract / manifest_sync

3. Task 4.2a (输入协议 + source_manifest) → 依赖 4.1
4. Task 4.2b (自动修复 + 状态回传) → 依赖 4.2a

5. Task 4.4 (跑分) → 依赖 4.2 + 4.3
6. Task 4.5 (前端) → 依赖 4.3
```

## Phase 4 完成标志

> `cd backend && python3 -m pytest tests/test_phase4_golden_template.py -v` 输出 ≥ 8/10 PASS
