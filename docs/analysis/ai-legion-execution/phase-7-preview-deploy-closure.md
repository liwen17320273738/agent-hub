# Phase 7：部署链接闭环

## 目标

没有 URL 不算完成。

MVP 可以先做本地 preview URL 或静态 preview，再逐步接 Vercel / Cloudflare Pages。关键是交付包必须有一个可访问链接，并经过健康检查和截图验证。

## 输入

- Phase 6 的真实 QA 结果。
- 当前 DevOps Agent 能力。
- 当前部署/预览配置。
- 当前分享页和 deliverables zip。

## MVP 策略

第一阶段部署闭环可以分两层：

### 本地 Preview

适合开发环境验证：

- 启动 preview server。
- 生成本地 URL。
- Playwright 健康检查。
- 截图。

### 云端 Preview

后续接入：

- Vercel
- Cloudflare Pages
- Netlify
- 自建静态服务

如果云端 token 不存在，必须进入 `awaiting_user` 或 `blocked`，不能生成假 URL。

## 任务拆分

### 1. 定义 `preview_url` artifact

字段建议：

- url
- provider
- environment
- commit_or_workspace_id
- health_status
- screenshot_artifact_id
- created_at

### 2. 执行真实预览

流程：

1. 确认 QA passed。
2. 构建静态产物。
3. 启动 preview 或执行部署。
4. 访问 URL。
5. 保存 health check。
6. 保存截图。

### 3. 失败恢复

失败时必须给出：

- 缺 token。
- build artifact 缺失。
- URL 无法访问。
- 端口冲突。
- health check 非 2xx。

### 4. 分享页引用 URL

分享页必须展示：

- preview URL。
- health status。
- 页面截图。
- 部署时间。

## 可能涉及文件

- `backend/app/services/pipeline_engine.py`
- `backend/app/services/artifact_writer.py`
- `backend/app/services/task_workspace.py`
- `backend/app/api/share.py`
- `backend/app/api/deliverables.py`
- `src/views/SharePage.vue`
- `src/components/task/DeliverableCards.vue`

## 强制产物

- `preview_url`
- `deploy_manifest.json`
- `health_check.json`
- `deployed_screenshot.png`
- `ops_runbook.md`
- `rollback_plan.md`

## 验收标准

- 交付包里有可访问 URL。
- URL 健康检查通过。
- 分享页引用该 URL。
- 部署失败时显示原因和下一步。
- 没有 preview URL 不能进入 Acceptance。

## 风险

- 本地 URL 对外不可访问，适合 MVP 验证但不等于客户交付。
- 云端部署需要 token 和账号资源，必须资源体检。
- 部署平台过多会稀释主线，先支持一个。

## 执行完成标志

当 Hero Path 任务能产出健康检查通过的 preview URL，并显示在分享页，本阶段完成。
