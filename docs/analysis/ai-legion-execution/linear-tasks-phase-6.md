# Phase 6 Linear 任务 —— 真实测试与浏览器验证

> 基于 2026-05-19 代码审计。`stealth_browser.py`(286行)、`executor_bridge.py`(已有) 为基础。

---

## EPIC: Phase 6 — QA 证据真实化

**目标**：QA Agent 的测试报告必须来自真实命令 + 浏览器截图，不再允许纯文本 fake。

**入口**：`docs/analysis/ai-legion-execution/phase-6-real-qa-browser-validation.md`

**已有基础**：
- `executor_bridge.py`: subprocess 执行 + Redis 持久化
- `stealth_browser.py`: Playwright 封装 (286行)
- Phase 4 的 `source_manifest.json` + `build.log`（QA 阶段直接读取）

**依赖关系**：
```
6.1 → 6.2 → 6.3 → 6.4
                  └──→ 6.5 (可并行)
```

---

## Task 6.1 — QA 阶段资源体检 + 命令定义

**Priority**: P0
**Estimate**: 1.5h
**Depends on**: 无（但逻辑依赖 Phase 4 的 source_manifest.json）

### 背景
QA Agent 当前可以"写测试报告"但不一定跑过真实命令。Phase 6 要求 QA 阶段必须执行 install/build/test/preview 四个命令并记录真实输出。

### 验收标准
- [ ] QA 阶段启动前从 `source_manifest.json` 读取 `build_command`、`test_command`、`run_command`
- [ ] 资源体检：`node`/`pnpm`/`npx playwright` 是否可用
- [ ] 缺少 source_manifest → 阶段 `blocked`，错误 `qa_blocked_no_source_manifest`
- [ ] 命令不可用 → 阶段 `blocked`，列出缺失工具
- [ ] 体检结果写入 stage `input_snapshot.metadata.qa_resource_check`

### 涉及文件
- `backend/app/services/pipeline_engine.py`
- `backend/app/services/executor_bridge.py`

---

## Task 6.2 — QA 命令执行器：真实 build + test

**Priority**: P0
**Estimate**: 3h
**Depends on**: Task 6.1

### 背景
当前 `executor_bridge.py` 已支持 subprocess 执行，但 QA 阶段需要结构化记录每个命令的 exit code/stdout/stderr/duration。

### 验收标准
- [ ] 新增 `QaExecutor` 类（`backend/app/services/qa_executor.py`）：
  - `run_command(project_dir, cmd, timeout_sec=120) → QaCommandResult`
  - `QaCommandResult`: `command`, `exit_code`, `stdout_summary`（前 5kB）, `stderr_summary`（前 5kB）, `duration_ms`, `ok`
- [ ] QA 阶段依次执行：
  1. `pnpm install`（timeout 120s）
  2. `pnpm build`（timeout 120s）
  3. `pnpm test`（timeout 60s）
- [ ] 每步结果写入 `build.log` 或 `test.log`（追加模式）
- [ ] install/build 任意失败 → 阶段 `failed`，`scheduler_last_error` 写入失败命令 + exit code + stderr 摘要
- [ ] test 失败 → 阶段 `failed`，但保留 `test.log` 供人工排查

### 涉及文件
- `backend/app/services/qa_executor.py`（新增）
- `backend/app/services/pipeline_engine.py`

---

## Task 6.3 — 浏览器 smoke 验证

**Priority**: P0
**Estimate**: 2.5h
**Depends on**: Task 6.2（build 成功后才有 preview）

### 背景
`stealth_browser.py` 已有 Playwright 封装。QA 阶段需要启动 preview server → 浏览器打开 → 截图 → 记录 console error。

### 验收标准
- [ ] QA 阶段 build 成功后：启动 `pnpm preview`（后台进程，记 PID）
- [ ] 等待 `http://localhost:4173` 响应 200（最多 15s）
- [ ] Playwright 打开页面 → `browser_screenshot.png`
- [ ] 收集 `console_errors.json`（`page.on('console')` 过滤 error 级别）
- [ ] 收集页面可见文本（`page.innerText` 前 2kB）
- [ ] preview server SIGTERM 清理（finally）
- [ ] 页面打不开（timeout/connection refused） → 阶段 `failed`，错误注明端口状态
- [ ] console error > 0 → 不阻断阶段但写入 warning 到 artifact metadata

### 涉及文件
- `backend/app/services/stealth_browser.py`
- `backend/app/services/qa_executor.py`（新增，Task 6.2）
- `backend/app/services/pipeline_engine.py`

---

## Task 6.4 — QA 产物写入 TaskArtifact + contract 升级

**Priority**: P0
**Estimate**: 2h
**Depends on**: Task 6.2, Task 6.3

### 验收标准
- [ ] QA 阶段结束后写入以下 artifact：
  - `test_report`：Markdown 报告（含命令表 + 退出码 + 截图引用）
  - `build_log`：覆盖 Phase 4 的 build.log（QA 版本更完整）
  - `test_log`：`pnpm test` 的完整输出（新 artifact 类型或 `attachment`）
  - `screenshot`：`browser_screenshot.png`
  - `console_errors.json`：`attachment` 类型
- [ ] Phase 3 artifact contract 更新：QA stage required 增加 `test_report`、`screenshot`、`build_log`
- [ ] `qa_result.json`（结构化结果）写入 `test_report` artifact 的 metadata

### 涉及文件
- `backend/app/services/artifact_writer.py`
- `backend/app/services/artifact_contract.py`
- `backend/app/services/manifest_sync.py`
- `backend/app/models/task_artifact.py`（如需新增 `test_log` 类型）

---

## Task 6.5 — 前端 TaskDocTab 展示 QA 证据

**Priority**: P1
**Estimate**: 2h
**Depends on**: Task 6.4

### 验收标准
- [ ] `TaskDocTab` 或新增 `TaskQATab` 展示：
  - 测试命令 + exit code 表格
  - `browser_screenshot.png` 缩略图（点击放大）
  - console error 列表（红色高亮）
  - `test.log` 可折叠面板
- [ ] 构建/测试失败时红色标识 + 错误日志默认展开
- [ ] `SharePage` 同步展示截图 + 测试状态
- [ ] i18n zh/en：`qa.testCommands` / `qa.browserScreenshot` / `qa.consoleErrors` / `qa.buildFailed`

### 涉及文件
- `src/components/task/TaskDocTab.vue` 或 `src/components/task/TaskQATab.vue`（新增）
- `src/components/task/TaskArtifactTabs.vue`
- `src/views/SharePage.vue`
- `src/i18n/zh.ts` / `src/i18n/en.ts`

---

## 跨 Phase 依赖

| 依赖 | 来源 | 状态 |
|------|------|------|
| `source_manifest.json` | Phase 4 Task 4.2a | ⚠️ 待完成 |
| `build.log` | Phase 4 Task 4.2a | ⚠️ 待完成 |
| Artifact Contract | Phase 3 | ✅ 完成 |
| executor_bridge.py | 已有 | ✅ 可用 |
| stealth_browser.py (286行) | 已有 | ⚠️ 需接 pipeline |

## Phase 6 完成标志

> QA Agent 的测试报告能追溯到真实 `pnpm build/test` 输出和 Playwright 截图。
> 构建失败 → 阶段 failed + 真实错误日志。页面打不开 → 明确退回原因。
