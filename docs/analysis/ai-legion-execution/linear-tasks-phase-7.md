# Phase 7 Linear 任务 —— 部署链接闭环

> 基于 2026-05-19 代码审计。`deploy/vercel.py`(179行) 已有 Vercel 部署基础。

---

## EPIC: Phase 7 — 无 URL 不算完成

**目标**：交付包必须有一个可访问链接，经过健康检查和截图验证。

**入口**：`docs/analysis/ai-legion-execution/phase-7-preview-deploy-closure.md`

**已有基础**：
- `deploy/vercel.py`: `deploy_to_vercel` 完整流程（创建项目→上传→部署→返回 URL）
- `executor_bridge.py`: subprocess 管理
- Phase 6 的浏览器 smoke 能力

**MVP 策略**：先做本地 `pnpm preview` + health check + 截图；Vercel 作为可选云端通道。

**依赖关系**：
```
7.1 → 7.2 → 7.3 → 7.4
              └──→ 7.5 (可并行)
```

---

## Task 7.1 — 定义 preview_url artifact 类型 + DevOps 资源体检

**Priority**: P0
**Estimate**: 1.5h
**Depends on**: 无

### 背景
当前 `TaskArtifact` 的 `deploy_manifest` 类型已经注册，但没有 `preview_url` 作为独立 artifact。需要定义其 schema 并在 DevOps 阶段启动前做资源体检。

### 验收标准
- [ ] `ArtifactTypeRegistry` 新增 `preview_url` 类型：
  - `url`: string
  - `provider`: `"local"` | `"vercel"` | `"cloudflare"`
  - `environment`: `"preview"` | `"production"`
  - `health_status`: `"healthy"` | `"unhealthy"` | `"unknown"`
  - `screenshot_artifact_id`: string | null
  - `deployed_at`: ISO8601
- [ ] DevOps 阶段启动前资源体检：
  - 本地 `pnpm preview` 可用（node 存在）
  - Vercel token 可用（`VERCEL_TOKEN` env）
  - 两者都不可用 → 阶段 `blocked`
  - 仅本地可用 → 标记 `provider: "local"` 继续
- [ ] 体检结果写入 stage `input_snapshot.metadata.deploy_resource_check`

### 涉及文件
- `backend/app/models/task_artifact.py`
- `backend/app/services/pipeline_engine.py`

---

## Task 7.2 — 本地 preview 闭环

**Priority**: P0
**Estimate**: 2.5h
**Depends on**: Task 7.1

### 背景
Phase 6 已在 QA 阶段启动了 `pnpm preview` 做浏览器 smoke。Phase 7 需要将其作为正式部署步骤：启动 → health check → 截图 → 写入 artifact。

### 验收标准
- [ ] DevOps 阶段执行 `deploy_local_preview(project_dir)`：
  1. `pnpm preview --port 4173` 后台启动（记 PID）
  2. 轮询 `http://localhost:4173` 最多 15s 直到 200
  3. Playwright 打开页面 → 截图 `deployed_screenshot.png`
  4. health check：HTTP 200 + 页面包含非空文本
  5. 写入 `preview_url` artifact：`{"url": "http://localhost:4173", "provider": "local", "health_status": "healthy", ...}`
  6. SIGTERM 清理 preview 进程
- [ ] 端口被占用 → 尝试 `4174`/`4175` 降级
- [ ] 15s 内无响应 → 阶段 `failed`
- [ ] 截图失败不影响 URL 有效性（warning 级别）

### 涉及文件
- `backend/app/services/deploy/local_preview.py`（新增）
- `backend/app/services/pipeline_engine.py`
- `backend/app/services/artifact_writer.py`

---

## Task 7.3 — Vercel 部署通道（可选增强）

**Priority**: P1
**Estimate**: 2h
**Depends on**: Task 7.1

### 背景
`deploy/vercel.py` 已有完整部署逻辑。需要对接 pipeline 和 artifact。

### 验收标准
- [ ] DevOps 阶段 Vercel token 可用时，优先走 Vercel 部署
- [ ] 部署结果写入 `preview_url` artifact：`provider: "vercel"`, `url: <vercel_deploy_url>`
- [ ] 部署失败时降级到本地 preview（Task 7.2），artifact 标注 `deploy_fallback: "vercel->local"`
- [ ] Vercel 部署超时 180s
- [ ] 部署成功后 Playwright 访问 Vercel URL 做 health check + 截图

### 涉及文件
- `backend/app/services/deploy/vercel.py`
- `backend/app/services/pipeline_engine.py`

---

## Task 7.4 — DevOps 产物 + contract 升级

**Priority**: P0
**Estimate**: 1.5h
**Depends on**: Task 7.2, Task 7.3

### 验收标准
- [ ] DevOps 阶段结束后写入：
  - `preview_url`（Task 7.1 定义）
  - `deploy_manifest`（已有类型，注：不是新类型，是已有 `deploy_manifest` artifact）
  - `deployed_screenshot.png`（`screenshot` 类型）
  - `ops_runbook`（Markdown：部署步骤 + 回滚方案）
- [ ] Phase 3 artifact contract 更新：DevOps stage required 增加 `preview_url`、`screenshot`
- [ ] `manifest.json` 重建后包含 `preview_url`
- [ ] 没有 `preview_url` → Acceptance 阶段 `blocked`

### 涉及文件
- `backend/app/services/artifact_contract.py`
- `backend/app/services/artifact_writer.py`
- `backend/app/services/manifest_sync.py`

---

## Task 7.5 — 前端 SharePage + 任务详情展示部署状态

**Priority**: P1
**Estimate**: 2h
**Depends on**: Task 7.4

### 验收标准
- [ ] `SharePage` 新增「预览链接」区域：
  - 显示 `preview_url`（可点击跳转）
  - 显示 health status 徽标（绿色 healthy / 红色 unhealthy）
  - 显示 `deployed_screenshot.png`
  - 显示部署时间
- [ ] `DeliverableCards` 新增部署卡片
- [ ] 部署失败时显示「预览暂不可用」+ 错误原因
- [ ] i18n zh/en：`deploy.previewUrl` / `deploy.healthStatus` / `deploy.deployedAt` / `deploy.notAvailable`

### 涉及文件
- `src/views/SharePage.vue`
- `src/components/task/DeliverableCards.vue`
- `src/i18n/zh.ts` / `src/i18n/en.ts`

---

## 跨 Phase 依赖

| 依赖 | 来源 | 状态 |
|------|------|------|
| QA 通过 | Phase 6 | ⚠️ 待完成 |
| `source_manifest.json` | Phase 4 | ⚠️ 待完成 |
| `build.log` | Phase 4 | ⚠️ 待完成 |
| stealth_browser.py | Phase 6 | ⚠️ 待完成 |
| deploy/vercel.py (179行) | 已有 | ✅ 可直接用 |
| Artifact Contract | Phase 3 | ✅ 完成 |

## Phase 7 完成标志

> Hero Path 任务的分享页显示可访问的 preview URL，带健康检查状态和页面截图。
> 没有 URL 不能进入 Acceptance。
