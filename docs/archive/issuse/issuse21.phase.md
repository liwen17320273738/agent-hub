# Issue 21 Phase｜任务工件体系落地分期：目录、模型、界面、迁移

> 对应主文档：`issuse21.md`（§1-14 为体系设计，§15-18 为架构决策与可扩展性分析）
>
> 本文档是执行分期。**不动手之前，issuse21 §15-18 的 8 个决策必须先落地（Phase 0）**。
> 目标不是再讨论"应该如何"，而是把这套工件体系拆成能动手做的阶段。

---

## 0. 最终目标

交付完成后的最终状态必须是：

### 物理层
- 每个任务都有自己的 `tasks/TASK-xxx/`
- 每个任务都有自己的 `worktrees/TASK-xxx/`

### 数据层
- 数据库中能按 `task_id` 索引所有工件
- 不再依赖全局 `docs/delivery/*.md`

### UI 层
- 任务详情页固定 8 个 Tab + 顶部完成度缩略条
- 用户不需要去终端、文件系统、README 里找产物

### 交付层
- 产品稿、UI 稿、技术稿、代码、测试、验收、运维全部按任务归档
- 一个任务的所有交付物都能一眼看清

---

## Phase 0｜架构决策落地（不写代码，只定规矩）

> **任何 Phase 1-4 的实施，都必须在 Phase 0 完成之后才能开始。**
> Phase 0 的产出是：配置约定、数据模型定义、迁移策略确认。

### 0.1 确认 8 个架构决策（来自 issuse21 §16）

| # | 决策点 | 决策 | 验证方式 |
|---|--------|------|---------|
| D1 | workspace 根配置 | env 配置 + 默认 `data/workspace/` | `backend/app/config.py` 中出现 `WORKSPACE_ROOT` |
| D2 | DB vs 文件谁权威 | DB 权威，manifest 是缓存 | 所有写操作先写 DB 再刷 manifest |
| D3 | 版本策略 | 追加版本文件（v1/v2） | `TaskArtifact` 表有 `version` + `is_latest` 字段 |
| D4 | 打回重做 | 旧 artifact 标 superseded + 新版本 | `TaskArtifact` 表有 `status` 字段含 `superseded` |
| D5 | artifact_type 扩展 | str + 注册表 | `artifact_type_registry` 表存在 |
| D6 | 多 worktree | 一任务一 worktree（本期 say no 多仓库） | 代码中有多 repo 提示文案 |
| D7 | 任务详情 UI | 8 Tab + 顶部完成度缩略条 | 设计稿确认 |
| D8 | 迁移节奏 | Phase 1-4 渐进 + 双写 2 周 | `ARTIFACT_STORE_V2` 开关在 config 中 |

### 0.2 配置项定义

在 `backend/app/config.py` 中新增：

```python
# Task Workspace
WORKSPACE_ROOT: str = ""          # 默认 {PROJECT_ROOT}/data/workspace
WORKSPACE_TASKS_DIR: str = ""     # 默认 {WORKSPACE_ROOT}/tasks
WORKSPACE_WORKTREES_DIR: str = "" # 默认 {WORKSPACE_ROOT}/worktrees
WORKSPACE_SHARED_DIR: str = ""    # 默认 {WORKSPACE_ROOT}/shared

# Migration switch
ARTIFACT_STORE_V2: bool = False   # Phase 2 开启后改为 True
```

### 0.3 数据模型草案

确认以下两个新表的字段设计（详见 issuse21 §15.5）：

**`TaskArtifact`**（扩展现有 `PipelineArtifact` 或新建）：
- `id`, `task_id`, `stage_id`, `artifact_type` (str, FK to registry)
- `title`, `storage_path`, `mime_type`
- `version` (int), `is_latest` (bool), `status` (str: active/superseded)
- `created_by_agent`, `created_by_user`
- `metadata` (JSON), `created_at`, `updated_at`

**`ArtifactTypeRegistry`**：
- `type_key` (PK), `category`, `display_name`, `icon`, `tab_group`, `sort_order`, `is_builtin`

### 0.4 Phase 0 验收标准

- [ ] 8 个决策全部明文写入 `issuse21.md` §16（已完成）
- [ ] `config.py` 配置项草案确认
- [ ] 两个新表的 Alembic migration 草案确认（不执行，只写 migration 文件）
- [ ] `ARTIFACT_STORE_V2` 开关位置确认
- [ ] 团队（或自己）过一遍，无异议后进入 Phase 1

---

## 1. Phase 1｜先把"任务级目录"建起来

### 目标

不改大页面，先补底座。

让系统从"全局 delivery docs"切到"每任务目录"。

---

### 1.1 新增目录规范服务

新增：`backend/app/services/task_workspace.py`

职责：

- 读取 `WORKSPACE_ROOT` / `WORKSPACE_TASKS_DIR` / `WORKSPACE_WORKTREES_DIR` 配置（来自 D1）
- 创建任务目录 `tasks/TASK-{id}-{slug}/`
- 创建子目录：docs / screenshots / logs / exports / artifacts
- 创建 worktree 目录 `worktrees/TASK-{id}-{slug}/`
- 生成 `manifest.json`（作为缓存，DB 权威 -- 来自 D2）
- 启动时校验目录存在 + 可写 + 磁盘空间 > 1GB，否则 fail-fast

---

### 1.2 目录结构

统一约定（来自 issuse21 §3 + D1）：

```text
{WORKSPACE_ROOT}/
  tasks/
    TASK-{id}-{slug}/
      manifest.json
      docs/
        00-brief.md
        01-prd.md
        02-ui-spec.md
        03-architecture.md
        04-implementation-plan.md
        05-test-report.md
        06-acceptance.md
        07-ops-runbook.md
      screenshots/
      logs/
      exports/
      artifacts/
  worktrees/
    TASK-{id}-{slug}/
  shared/
    templates/          # 从 docs/delivery/*.md 迁移过来
```

---

### 1.3 任务创建时自动初始化

在任务创建成功时（`backend/app/api/pipeline.py` 或 service 层）：

- 调用 `task_workspace.init_task(task_id, slug)`
- 初始化任务目录 + 从 `shared/templates/` 复制 docs 模板
- 生成 `manifest.json`

---

### 1.4 文档模板迁移

保留现有：

- `backend/app/api/delivery_docs.py`
- `docs/delivery/*.md`

但把它们角色改成：

- 模板来源（复制到 `shared/templates/`）
- 不再作为正式任务文档的最终存储位置

---

### 1.5 双写开关（来自 D8）

Phase 1 期间 `ARTIFACT_STORE_V2=false`：

- stage output 仍然写旧路径 `docs/delivery/0X.md`
- **同时**也写新路径 `tasks/{id}/docs/0X.md`
- 这是"双写"阶段，确保新路径数据完整

---

### 1.6 Phase 1 验收标准

- [ ] 新建任务后，自动生成 `tasks/TASK-xxx/manifest.json` + 8 个 docs 模板
- [ ] 不再往全局 `docs/delivery/*.md` 写正式任务内容（但双写期仍写）
- [ ] `task_workspace.py` 100% 单测覆盖（路径创建 + 防越权 + 磁盘校验）
- [ ] 两个 task 并发创建，目录互不干扰

---

## 2. Phase 2｜把工件变成数据库里的第一等对象

### 目标

让文件不仅存在磁盘，也存在于数据库索引里。

否则前端永远只能扫目录、拼逻辑、不可控。

---

### 2.1 执行 Alembic migration

执行 Phase 0 准备好的 migration：

- 创建 `artifact_type_registry` 表 + seed 12 个预置类型（来自 D5）
- 扩展 `PipelineArtifact` 为 `TaskArtifact`（或新建表），增加字段（来自 D3/D4）：
  - `version`, `is_latest`, `status`
  - `artifact_type` FK 到 registry
  - `created_by_agent`, `created_by_user`

---

### 2.2 新增工件 API

新建 `backend/app/api/task_artifacts.py`：

#### 任务工件列表
`GET /api/tasks/{task_id}/artifacts`

#### 单个工件详情（含历史版本列表）
`GET /api/tasks/{task_id}/artifacts/{artifact_type}`

#### 创建/更新工件（版本自增 -- 来自 D3）
`POST /api/tasks/{task_id}/artifacts/{artifact_type}`

写入流程：
1. DB 写入 TaskArtifact（version++, is_latest=True, 旧行 is_latest=False）
2. 物理文件：旧文件加版本后缀 -> 新内容写入无后缀文件名
3. 异步刷新 `manifest.json`（来自 D2）

#### 代码工件元信息
`GET /api/tasks/{task_id}/code`

返回：repoPath, branch, changed files, recent commits, test status

---

### 2.3 代码工件不要存代码正文

数据库里不要保存整份代码内容。`code_link` 类型只保存：路径、branch、commit、摘要、文件清单。

---

### 2.4 manifest 同步服务（来自 D2）

新增 `services/manifest_sync.py`：

- artifact 写入后触发异步 manifest 重建
- 提供 `rebuild_manifest(task_id)` 手动重建接口
- manifest 损坏时 API 自动 fallback 到纯 DB 查询

---

### 2.5 开启 v2 开关

`ARTIFACT_STORE_V2=true`：

- 新任务的 stage output 物化**只写**新路径
- 老任务仍 fallback 到旧路径（来自 D8）

---

### 2.6 Phase 2 验收标准

- [ ] 任意任务都能通过 API 查到完整工件清单（8 类 + 附件）
- [ ] 工件更新后，`manifest.json` 在 3 秒内自动刷新
- [ ] 打回一个任务 -> 受影响阶段的 artifact 变成 `superseded`，新版本 `is_latest=True`（来自 D4）
- [ ] `ArtifactTypeRegistry` 中有 12 个预置类型，API 可查

---

## 3. Phase 3｜前端任务详情页升级为"8 个 Tab 交付视图"

### 目标

把"产物肉眼可看"真正做出来。

这是用户感知变化最大的一步。

---

### 3.1 任务详情页从"阶段大杂烩"改为"交付视图"

当前 `src/views/PipelineTaskDetail.vue` 太重，而且更偏系统内部视角。

改成两层（来自 D7）：

**顶部**：
- 任务标题 / 状态 / 当前阶段 / 负责人 / 快捷操作
- **完成度缩略条**：8 个图标横排，灰/亮/红反映每类工件状态（点击跳到对应 Tab）

**下方主体**：固定 8 个 Tab

1. 需求（`00-brief.md`）
2. PRD（`01-prd.md`）
3. UI（`02-ui-spec.md` + screenshots gallery）
4. 技术方案（`03-architecture.md`）
5. 代码（repoPath + branch + commits + changed files + test status + 打开按钮）
6. 测试（`05-test-report.md` + verify_checks）
7. 验收（`06-acceptance.md` + 签字记录 + 打回历史）
8. 运维（`07-ops-runbook.md` + 部署链接 + 回滚方案 + 最近部署日志）

**系统视图降级**：trace / 阶段时间线 / event stream 放到"系统详情"折叠区或第 9 个 Tab

---

### 3.2 拆组件

新增：

- `src/components/task/TaskArtifactTabs.vue` -- 8 Tab 容器
- `src/components/task/TaskDocTab.vue` -- markdown 渲染 + 版本切换 + 附件 gallery
- `src/components/task/TaskCodeTab.vue` -- 代码工件专用（repo + commits + diff）
- `src/components/task/ArtifactCompletionBar.vue` -- 顶部 8 图标缩略条

每个 doc Tab 右上角统一有"历史版本"下拉（来自 D3）。

---

### 3.3 任务列表页工件完成度

任务卡片增加完成度格子（来自 issuse21 §10）：

```
[需求] [PRD] [UI] [技术方案] [代码] [测试] [验收] [运维]
  OK    OK   OK      OK      OK    ...    --     --
```

数据来自 `GET /api/tasks/{id}/artifacts` 返回的 summary。

---

### 3.4 Phase 3 验收标准

- [ ] 打开任务详情，默认先看到交付物 Tab，而不是阶段大长页
- [ ] 用户 10 秒内能找到：PRD / UI 稿 / 代码位置 / 测试结果 / 验收结论 / 运维说明
- [ ] 完成度缩略条状态与 DB 工件状态一致
- [ ] 历史版本下拉能切换查看旧版文档（来自 D3）
- [ ] 被打回的工件显示 superseded 标记 + reject reason（来自 D4）

---

## 4. Phase 4｜迁移与淘汰旧体系

### 目标

完成从"全局 delivery docs"到"任务级工件体系"的迁移。

---

### 4.1 老体系保留为模板

继续保留：

- `docs/delivery/*.md` -> 迁移到 `{WORKSPACE_ROOT}/shared/templates/`
- `backend/app/api/delivery_docs.py` -> 只承担模板服务 + 兼容旧 API

---

### 4.2 新任务全走新体系

从这个阶段开始：

- 所有新任务只写 `tasks/TASK-xxx/docs/*`
- 不再把内容写回全局 `docs/delivery/*.md`
- 关闭双写（移除旧路径写入代码）

---

### 4.3 老任务兼容策略

对历史任务：

- 如果没有任务级工件目录
- 前端 fallback 读取老的 `delivery_docs` API
- 兼容期 30 天后：旧 API 返回 deprecation warning header

---

### 4.4 归档服务上线

新增 `services/workspace_archiver.py`（来自 issuse21 §17.1）：

- 已验收 30 天的任务：worktree tar+gzip 到 `_archive/`
- 已取消 7 天的任务：同上
- docs/ 永久保留
- 归档前确认 worktree 已推到 git remote

---

### 4.5 README / 文档同步

需要更新：

- `README.md` -- 新增工件体系说明
- `CLAUDE.md` -- 更新架构图 + 工件存储说明
- `backend/CLAUDE.md` -- 新增 TaskArtifact API 说明

写清楚：工件体系目录结构 / 代码工作区位置 / 用户在哪看任务产物。

---

### 4.6 Phase 4 验收标准

- [ ] 新任务默认走任务级工件目录
- [ ] 老任务仍可查看（fallback 正常）
- [ ] 前端不再依赖全局 delivery docs 才能显示产物
- [ ] 归档 cron job 运行正常，磁盘不再无限增长
- [ ] README / CLAUDE.md 更新完成

---

## 5. 推荐的实施顺序

推荐顺序不要乱：

### Week 0（半天）
- Phase 0：架构决策确认 + 配置项 + migration 草案

### Week 1
- Phase 1：目录服务 + manifest + docs 初始化 + 双写开启

### Week 2
- Phase 2：数据库索引 + 工件 API + manifest 同步 + v2 开关

### Week 3
- Phase 3：任务详情页 8 Tab + 完成度缩略条 + 列表页格子

### Week 4
- Phase 4：迁移完成 + 关闭双写 + 归档上线 + 文档同步

---

## 6. 涉及的主要文件

### 后端新增

- `backend/app/services/task_workspace.py` -- 目录服务
- `backend/app/services/manifest_sync.py` -- manifest 缓存刷新
- `backend/app/services/workspace_archiver.py` -- 归档 cron
- `backend/app/services/task_exporter.py` -- 任务完整导出
- `backend/app/api/task_artifacts.py` -- 工件 CRUD API
- `backend/app/models/task_artifact.py` -- TaskArtifact + ArtifactTypeRegistry 模型
- `backend/alembic/versions/xxx_add_task_artifact.py` -- migration

### 后端修改

- `backend/app/config.py` -- 新增 WORKSPACE_* + ARTIFACT_STORE_V2
- `backend/app/api/delivery_docs.py` -- 降级为模板服务
- `backend/app/api/pipeline.py` -- 任务创建时调用 task_workspace.init_task()
- `backend/app/services/pipeline_engine.py` -- stage 完成时触发 artifact 写入
- `backend/app/main.py` -- 注册新 router

### 前端新增

- `src/components/task/TaskArtifactTabs.vue` -- 8 Tab 容器
- `src/components/task/TaskDocTab.vue` -- 文档渲染 + 版本切换
- `src/components/task/TaskCodeTab.vue` -- 代码工件展示
- `src/components/task/ArtifactCompletionBar.vue` -- 顶部完成度缩略条

### 前端修改

- `src/views/PipelineTaskDetail.vue` -- 引入 TaskArtifactTabs 作为默认视图
- `src/views/Dashboard.vue` -- 任务卡增加完成度格子
- `src/views/SharePage.vue` -- 复用 TaskArtifactTabs（readonly 模式）

---

## 7. 最后结论

这套 Phase 的真正意义，不是多建几个目录。

而是把 `agent-hub` 从：

> "系统好像跑了，但产物不知道在哪"

改成：

> "每个任务都有自己的交付档案，用户随时打开就能看到产品稿、UI 稿、代码、测试、验收和运维。"

只有这样，AI 军团才不像一堆 Agent 和页面，
而像一个真正能交付结果的系统。

---

## 8. 与 issuse20 的映射关系

| Phase | 对应 issuse20 的周 | 说明 |
|-------|-------------------|------|
| Phase 0 | D1（启动检查同步做） | 决策确认不占整周，半天搞定 |
| Phase 1 | W1 的"修 P0 bug"部分 | issuse20 原计划只修 bug，这里升级为建完整目录体系 |
| Phase 2 | W2 的"交付包 tab"部分 | issuse20 原计划只加 UI，这里先补 DB 底座 |
| Phase 3 | W2-W3 的"任务详情页拆分"部分 | 两个文档的 UI 目标一致，以本文 8 Tab 为准 |
| Phase 4 | W4 的"归档 + 文档同步"部分 | issuse20 原计划 W4 做企业功能，工件迁移可并行 |

> **原则**：issuse21/21.phase 是工件体系的**架构与分期**，issuse20 是 30 天整体的**执行手册**。两者不冲突，互补。
