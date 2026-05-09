# Issue 21｜任务工件体系设计：产品稿、UI 稿、代码、测试、验收、运维到底放哪里，怎么让用户肉眼可看

> 目标：解决 `agent-hub` 当前最致命的“产物不可见”问题。
>
> 核心原则：
>
> 1. **每个任务一套独立工件**
> 2. **文档工件和代码工件分开存**
> 3. **数据库只做索引，不做唯一存储**
> 4. **UI 必须按任务直接可见，而不是让用户去找文件**

---

## 0. 问题定义

当前最核心的问题不是“有没有产出”，而是：

- 产品设计稿放哪？
- 需求稿放哪？
- UI 设计稿放哪？
- 代码放哪？
- 测试稿放哪？
- 验收稿放哪？
- 运维稿放哪？
- 用户到底在哪看？

如果这些没有统一答案，用户就只会感受到：

> 任务似乎跑了，但到底产出了什么，看不见。

---

## 1. 先否定当前方案

### 当前 `docs/delivery/*.md` 不能作为正式交付体系

你现在已有：

- `backend/app/api/delivery_docs.py`
- `docs/delivery/01-prd.md`
- `docs/delivery/02-ui-spec.md`
- `docs/delivery/03-architecture.md`
- `docs/delivery/04-implementation-notes.md`
- `docs/delivery/05-test-report.md`
- `docs/delivery/06-acceptance.md`

这个结构的问题很严重：

### 1.1 它是全局的，不是任务级的

多个任务都会写这些固定文件名：

- `01-prd.md`
- `06-acceptance.md`

结果就是：

- 后来的任务覆盖前面的任务
- 无法区分“这份 PRD 属于哪个任务”
- 无法追踪版本

### 1.2 它是 demo 友好，不是产品友好

`docs/delivery/` 更适合：

- 演示
- 模板
- 静态文档

不适合：

- 多任务并发
- 多用户协作
- 企业交付
- 验收留痕

### 1.3 UI 也无法自然映射

如果交付文档都放在全局目录里，任务详情页就没法自然展示：

- 这份 UI 稿是不是当前任务的？
- 这份测试报告是不是最新版本？
- 这份验收稿是不是当前这轮执行的？

所以结论非常明确：

> `docs/delivery/*.md` 只能保留为模板和示例，不能再作为正式交付物存储位置。

---

## 2. 正确的物理结构

必须按 **任务** 建立目录。

建议根结构：

```text
agent-hub-workspace/
  tasks/
  worktrees/
  shared/
```

其中：

- `tasks/`：每个任务自己的文档工件、截图、日志、元信息
- `worktrees/`：每个任务的真实代码工作区
- `shared/`：模板、公共资源、通用规范

---

## 3. 每个任务的标准目录

推荐结构：

```text
tasks/
  TASK-2026-04-22-001-login-refactor/
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
```

---

## 4. 每类文档该放什么

### `00-brief.md`
原始需求与澄清结果。

包含：

- 用户原始输入
- Clarifier 追问结果
- 背景上下文
- 非目标
- 风险提示

它是整个任务的源头文件。

---

### `01-prd.md`
产品需求稿。

包含：

- 目标
- 用户场景
- 范围 / 非目标
- 用户故事
- 验收标准
- 关键里程碑

责任角色：

- `product-agent`

---

### `02-ui-spec.md`
UI / 交互设计稿。

包含：

- 页面清单
- 核心交互流
- 组件和布局说明
- 状态设计
- 空态 / 错误态 / 加载态
- 视觉与实现注意点

责任角色：

- `design-agent`

如果未来接 Figma / `.pen` / 截图，也应在这个阶段输出引用和截图。

---

### `03-architecture.md`
技术设计稿。

包含：

- 模块边界
- API / 数据契约
- 状态流
- 风险
- ADR

责任角色：

- `architect-agent`

---

### `04-implementation-plan.md`
开发实施稿。

包含：

- 改动范围
- 代码入口
- 文件清单
- feature flag / env
- 实施步骤
- 回滚注意

责任角色：

- `developer-agent`

注意：这不是代码本身，而是“如何改代码”的说明。

---

### `05-test-report.md`
测试稿。

包含：

- 测试范围
- 已执行项
- 未执行项
- 风险点
- 缺陷列表
- 测试结论

责任角色：

- `qa-agent`

---

### `06-acceptance.md`
验收稿。

包含：

- 验收结论
- 是否通过
- 打回原因
- 业务确认记录
- 已知问题

责任角色：

- `acceptance-agent` + 人工验收人

---

### `07-ops-runbook.md`
运维 / 上线稿。

包含：

- 部署目标
- 发布步骤
- 回滚步骤
- 监控检查项
- 观察窗口
- 值班与故障处理建议

责任角色：

- `devops-agent`

---

## 5. 代码应该放哪里

### 结论：代码不要放在 `tasks/.../docs/`

代码必须放在真实工作区里。

推荐：

```text
worktrees/
  TASK-2026-04-22-001-login-refactor/
    ...真实代码仓库内容...
```

也就是说：

- 文档工件在 `tasks/TASK-xxx/docs/`
- 真实代码在 `worktrees/TASK-xxx/`

这样做的好处：

- 不污染主仓库
- 每个任务独立隔离
- diff、测试、部署都能绑定这个工作区
- 用户能真正“打开代码”看，而不是看复制粘贴进 Markdown 的代码块

---

## 6. `manifest.json` 应该记录什么

每个任务目录都应该有一个索引文件：

```json
{
  "taskId": "TASK-2026-04-22-001",
  "title": "重构登录页并补齐测试",
  "status": "active",
  "template": "web_app",
  "workspaceId": "default",
  "repoPath": "worktrees/TASK-2026-04-22-001-login-refactor",
  "docsPath": "tasks/TASK-2026-04-22-001-login-refactor/docs",
  "currentStage": "development",
  "ownerAgents": [
    "product-agent",
    "design-agent",
    "developer-agent",
    "qa-agent",
    "acceptance-agent",
    "devops-agent"
  ],
  "latestArtifacts": {
    "brief": "docs/00-brief.md",
    "prd": "docs/01-prd.md",
    "ui": "docs/02-ui-spec.md",
    "architecture": "docs/03-architecture.md",
    "implementation": "docs/04-implementation-plan.md",
    "test": "docs/05-test-report.md",
    "acceptance": "docs/06-acceptance.md",
    "ops": "docs/07-ops-runbook.md"
  }
}
```

作用：

- UI 快速读取
- API 快速汇总
- 不必每次扫目录

---

## 7. 数据库应该怎么索引

文件放磁盘，但数据库必须有结构化索引。

建议新增 / 规范化 `TaskArtifact`：

### 核心字段

- `id`
- `task_id`
- `stage_id`
- `artifact_type`
- `title`
- `storage_path`
- `mime_type`
- `version`
- `status`
- `created_by_agent`
- `created_by_user`
- `updated_at`
- `metadata`

### `artifact_type` 建议枚举

- `brief`
- `prd`
- `ui_spec`
- `architecture`
- `implementation_plan`
- `code_link`
- `test_report`
- `acceptance`
- `ops_runbook`
- `screenshot`
- `deploy_log`
- `preview_link`

注意：

> `code_link` 不保存代码内容，只保存 `repoPath / branch / commit / changed files summary`

---

## 8. 用户“肉眼可看”应该在哪里看

不是去文件系统看，而是直接在任务详情页看。

建议任务详情页新增固定 **8 个 Tab**：

1. `需求`
2. `PRD`
3. `UI`
4. `技术方案`
5. `代码`
6. `测试`
7. `验收`
8. `运维`

这 8 个 Tab 比“按 stage 展开一大坨”更符合用户认知。

---

## 9. 每个 Tab 要显示什么

### 需求 Tab

- 原始需求
- 澄清结论
- 当前范围
- 风险提示

来源：

- `00-brief.md`

---

### PRD Tab

- `01-prd.md` 的渲染结果
- 版本号
- 更新时间
- 责任角色

---

### UI Tab

- `02-ui-spec.md`
- 关键截图
- 页面清单
- 状态流

未来可扩：

- Figma 链接
- `.pen` 设计稿
- 页面快照

---

### 技术方案 Tab

- `03-architecture.md`
- 关键接口
- 风险
- 设计决策

---

### 代码 Tab

这个 Tab 最关键，不能只显示 Markdown。

应该显示：

- `repoPath`
- 当前 `branch / worktree`
- 最近 commit
- 改动文件列表
- diff 摘要
- 测试状态
- 打开工作区按钮

也就是说：

> 代码 Tab 展示的是“代码交付状态”，不是“代码文档”。

---

### 测试 Tab

- `05-test-report.md`
- 自动测试结果
- 手动测试结论
- 未覆盖风险

---

### 验收 Tab

- `06-acceptance.md`
- 当前验收状态
- 业务签字记录
- 打回原因

---

### 运维 Tab

- `07-ops-runbook.md`
- 部署地址
- 回滚方案
- 监控检查项
- 最近部署日志

---

## 10. 列表页怎么显示才清楚

任务列表页不要展示“文件列表”，而要展示工件完成度。

每个任务卡片建议显示：

- 标题
- 当前阶段
- 当前负责人
- 文档完成度

例如：

```text
重构登录页并补齐测试
当前阶段：测试验证
负责人：qa-agent

[需求] [PRD] [UI] [技术方案] [代码] [测试] [验收] [运维]
  ✅     ✅    ✅      ✅        ✅      🟡      ⬜      ⬜
```

这样用户一眼就知道：

- 产物有没有
- 卡在哪一步
- 还差什么

---

## 11. API 该怎么设计

建议新增任务工件 API：

### 列表

`GET /api/tasks/{task_id}/artifacts`

返回：

- 各 artifact 类型
- 最新版本
- 存储路径
- 更新时间

### 单个工件

`GET /api/tasks/{task_id}/artifacts/{artifact_type}`

### 上传或更新

`POST /api/tasks/{task_id}/artifacts/{artifact_type}`

### 代码工件元信息

`GET /api/tasks/{task_id}/code`

返回：

- repoPath
- branch
- changed files
- test status

---

## 12. 迁移建议

不要一口气推翻现有 `delivery_docs.py`。

建议三步走：

### Phase 1
- 保留 `docs/delivery/*.md` 作为模板
- 不再把它当正式任务产物

### Phase 2
- 新增 `tasks/{taskId}/docs/*`
- 新任务全部写到任务目录

### Phase 3
- 任务详情页完全改用任务级工件读取
- `delivery_docs.py` 降级为模板服务

---

## 13. 和现有系统怎么对接

### 现有可复用的部分

- `PipelineTask`
- `TaskArtifact`
- `PipelineTaskDetail.vue` 的 artifacts 区
- `delivery_docs.py` 里的文档模板定义

### 需要重做的部分

- 文档存储位置
- 按任务索引
- 代码工件展示
- UI 的 8 个 Tab 结构

---

## 14. 最终结论

这件事必须定死：

### 文档工件
放在：

`tasks/TASK-xxx/docs/`

### 真实代码
放在：

`worktrees/TASK-xxx/`

### 数据库
只做索引：

- 不存完整代码
- 不做唯一文件存储

### 用户肉眼看
在：

`任务详情页 8 个 Tab`

不是：

- 去 `docs/delivery/` 找
- 去终端看
- 去后端日志看
- 去某个实验室页面里翻

一句话：

> **AI 军团的交付物，必须按任务归档、按任务展示、按任务验收。**

否则再多 Agent、再多页面、再多执行流，用户也只会觉得“跑了半天，不知道产出了什么”。

---

## 15. 架构盲点分析（6 处必须补齐才能落地）

以上 §1–14 定义了"什么是对的结构"，但以下 6 个问题不回答，这套结构**建起来也会塌**。

### 15.1 workspace 根目录到底放在哪、怎么配置

§2 写了 `agent-hub-workspace/{tasks,worktrees,shared}` 三层结构，但没回答部署问题。

**必须覆盖 3 种部署形态**：

| 形态 | workspace 根位置 | 读写特性 |
|------|-----------------|---------|
| 本地开发 | repo 同级 `../agent-hub-workspace/` 或 `data/workspace/` | 直接文件系统 |
| Docker 单容器 | 挂载卷 `/data/workspace/` | bind mount / named volume |
| K8s 多副本 | PVC 共享卷 / S3-FUSE / 对象存储 | 多 pod 并发读写 |

**配置方案**：

```
WORKSPACE_ROOT          # 总根，默认 ${PROJECT_ROOT}/data/workspace
WORKSPACE_TASKS_DIR     # 可选覆盖，默认 ${WORKSPACE_ROOT}/tasks
WORKSPACE_WORKTREES_DIR # 可选覆盖，默认 ${WORKSPACE_ROOT}/worktrees
WORKSPACE_SHARED_DIR    # 可选覆盖，默认 ${WORKSPACE_ROOT}/shared
```

- 3 个子目录可以各自独立指向不同存储（例如 worktrees 挂 SSD，tasks 挂 S3-FUSE）
- 代码中统一通过 `task_workspace.get_tasks_root()` / `get_worktrees_root()` 获取，**不硬编码路径**
- 启动时校验目录存在 + 可写 + 磁盘空间 > 1GB，否则 fail-fast

**多副本场景结论**：本期只支持单副本 + 本地文件系统。如需水平扩展，下期改造为：
- 文档工件走对象存储（S3/MinIO）+ DB 存 URL
- 代码 worktree 只在执行节点本地，执行完推到 git remote

### 15.2 manifest.json vs DB TaskArtifact 谁是 Source of Truth

§6 定义了 `manifest.json`，§7 定义了 DB `TaskArtifact`，但没说冲突时谁说了算。

**三个选项分析**：

| 选项 | 优点 | 缺点 | 适用场景 |
|------|------|------|---------|
| A: DB 权威，manifest 是缓存 | 简单、事务安全、API 不依赖文件系统 | manifest 过期需要主动刷新 | **推荐（本期）** |
| B: 文件权威，DB 是索引 | 灾备友好、IDE 可直接编辑 | 并发不安全、全量扫描慢 | 纯本地工具 |
| C: 双写 + 启动对账 | 强一致 | 实现复杂、对账有性能代价 | 高可用生产 |

**决策：选 A — DB 权威**

- 所有写操作走 `TaskArtifact` ORM → 写完后异步刷新 `manifest.json`
- `manifest.json` 仅作为 UI 快速读取的缓存 + 运维调试的辅助
- 如果 manifest 不存在或损坏，API 应能仅从 DB 重建（`GET /api/tasks/{id}/artifacts` 不依赖 manifest）
- 新增 `services/manifest_sync.py`：定时或事件驱动重建 manifest

### 15.3 版本与历史

§7 提了 `version` 字段，但版本到底怎么落地？

**四个选项分析**：

| 选项 | 优点 | 缺点 |
|------|------|------|
| A: 覆盖（无版本） | 最简单 | 验收争议无法追溯 |
| B: 追加版本文件（`01-prd.v1.md`, `v2.md`） | 可读、IDE 友好 | manifest 维护 |
| C: 目录级 git（每个 task docs/ 是 git repo） | 天然版本 + diff | 重 |
| D: DB 存 diff | 精细 | 前端展示成本高 |

**决策：选 B — 追加版本文件**

- `TaskArtifact.version` 从 1 开始自增
- 物理文件命名：`01-prd.md`（始终是最新版）+ `01-prd.v1.md` / `01-prd.v2.md`（历史版）
- 写入新版本时：旧文件改名加版本后缀 → 新内容写入无版本后缀的文件名
- DB 中同一 `(task_id, artifact_type)` 保留所有版本行，`is_latest=True` 标记最新
- UI 上：Tab 展示最新版，右上角"历史版本"下拉可切换
- **版本上限**：单个 artifact 最多保留 10 个历史版本，超出的最早版本物理删除

### 15.4 任务被打回重做时 artifact 怎么处理

场景：客户拒绝验收 → pipeline 退回 development → 重跑 development → testing → reviewing。

**决策**：

1. 打回触发 `version++`：被影响的阶段（从打回目标到末尾）的 artifact 全部标记 `status=superseded`
2. 重跑产生新版本 artifact，`is_latest=True`
3. 客户的 reject reason 写入 `06-acceptance.vN.md` 的底部 `## 打回记录` 区块，并在 DB `TaskArtifact` 的 `metadata.reject_reason` 字段留痕
4. UI 上：被 superseded 的版本不默认展示，但「历史版本」下拉可查
5. 任务卡状态从 ✅ 退回 🟡，不变成 ⬜（区分"从没产出过"和"产出过但被打回"）

**状态机**：

```
not_started → in_progress → completed
                                ↓ (reject)
                            superseded → in_progress (v2) → completed (v2)
```

### 15.5 artifact_type 的扩展性

§7 列了 12 个固定枚举。但 3 个月后必然新增：`figma_link` / `pen_doc` / `pdf_export` / `video_demo` / `api_openapi` / `db_schema_dump` / `security_scan_report` / `cost_report` ...

**决策：str + 注册表（不硬编码枚举）**

```python
class ArtifactTypeRegistry(Base):
    __tablename__ = "artifact_type_registry"
    type_key: Mapped[str]       # "prd", "ui_spec", "figma_link"
    category: Mapped[str]       # "doc", "code", "media", "link", "report"
    display_name: Mapped[str]   # "PRD", "UI Spec", "Figma Link"
    icon: Mapped[str]           # emoji
    tab_group: Mapped[str]      # 映射到 UI 的哪个 Tab
    sort_order: Mapped[int]
    is_builtin: Mapped[bool]    # True = 系统预置, False = 用户自定义
```

- `TaskArtifact.artifact_type` 仍然是 `str`，但必须在 registry 中注册过
- 预置 12 个（§7 的列表），用户 / 插件 可通过 API 新增
- 前端的 8 个 Tab 按 `tab_group` 聚合，未归入任何 Tab 的 artifact 出现在"其他"Tab
- **好处**：不改代码就能扩展新类型；registry 表也是前端渲染 icon / display_name 的唯一来源

### 15.6 多 repo / 多 worktree 的任务建模

§5 假设一任务 = 一 worktree。但企业场景「重构登录」可能涉及 frontend / backend / mobile / protos 4 个仓库。

**决策：本期一任务一 worktree（显式 Say No 多仓库），远期走子任务**

- `manifest.json` 中 `repoPath` 保持单值
- 如果用户的需求涉及多个仓库，系统自动拆成多个子任务（subtask），每个 subtask 有自己的 worktree
- 父任务的「代码」Tab 展示子任务列表 + 各自的 worktree 链接
- **本期不实现 subtask 拆分**，只在文档中声明这是远期路径
- 如果用户手动指定了多 repo_url，提示"当前版本仅支持单仓库，建议拆成多个任务"

---

## 16. 8 个架构决策总表

以下是 §15 分析的决策汇总，作为后续所有实施的约束条件：

| # | 决策点 | 决策 | 理由 |
|---|--------|------|------|
| D1 | workspace 根配置 | env 配置 + 默认 repo 内 `data/workspace/` | dev/prod 都通，不改代码即可切换 |
| D2 | DB vs 文件谁权威 | DB 权威，manifest 是缓存 | 简单可控，API 不依赖文件系统 |
| D3 | 版本策略 | 追加版本文件（v1/v2） | 验收争议可追溯，实现简单 |
| D4 | 打回重做 | 旧 artifact 标 superseded + 新版本 | 可追溯，状态机清晰 |
| D5 | artifact_type 扩展 | str + 注册表 | 不改代码即可扩展新类型 |
| D6 | 多 worktree | 一任务一 worktree（本期），远期走子任务 | 本期控制复杂度 |
| D7 | 任务详情 UI | 8 Tab + 顶部完成度缩略条 | 既快速浏览也能深入 |
| D8 | 迁移节奏 | Phase 1→2→3→4 渐进 + 双写 2 周 | 安全，不打断现有任务 |

> 以上决策在落地前如需调整，必须更新此表 + 通知所有相关文档。

---

## 17. 多维度可扩展性与维护分析

### 17.1 性能与容量

| 维度 | 数据量估算 | 是否有问题 | 对策 |
|------|-----------|-----------|------|
| 文档工件（tasks/） | 1000 任务 x 8 文件 x 20KB = **160 MB** | 无 | 正常文件系统即可 |
| 截图（screenshots/） | 1000 任务 x 10 张 x 500KB = **5 GB** | 可控 | 超 1 年的归档到冷存储 |
| worktree（worktrees/） | 1000 任务 x 500MB = **500 GB** | 有风险 | 归档策略（见下） |
| DB TaskArtifact 行数 | 1000 x 12 类 x 3 版本 = **36K 行** | 无 | 常规索引 |

**worktree 归档策略**：

- 任务 `final_acceptance_status = approved` 后 **30 天**：worktree 自动 `tar+gzip` 到 `_archive/{yyyy-mm}/TASK-xxx.tar.gz`，原目录删除
- 任务 `status = cancelled` 后 **7 天**：同上
- `tasks/TASK-xxx/docs/` **永久保留**（文本小、检索价值大）
- 归档由后台 cron job 执行：`services/workspace_archiver.py`
- 归档前确认 worktree 已推到 git remote（如未推，先推再归档）

### 17.2 备份策略

| 层 | 备份方式 | 频率 | 恢复时间目标 |
|----|---------|------|-----------|
| `tasks/` 文档目录 | rsync 到远程 / S3 | 每日增量 | < 1h |
| `worktrees/` 代码 | git push 到 remote origin | 每次 commit | 即时（git clone） |
| DB（PostgreSQL） | pg_dump + WAL 归档 | 每日全量 + 持续 WAL | < 30min |
| manifest.json | 不单独备份（可从 DB 重建） | -- | 秒级重建 |

**跨三者一致性**：

- 新增 `services/task_exporter.py`：按 task_id 导出完整包（manifest + docs/ + worktree git bundle + DB rows JSON）
- 用于：客户离线交付 / 跨环境迁移 / 灾备恢复
- 格式：`TASK-xxx-export.tar.gz`

### 17.3 多租户隔离（对接 W4 workspace 模型）

当引入 workspace 时，物理目录和数据库都需要加隔离层：

- 物理目录加一层：`{WORKSPACE_ROOT}/{workspace_id}/tasks/TASK-xxx/...`
- DB `TaskArtifact` 加 `workspace_id` 外键 + index
- 分享 token 只签 `task_id`，访问时校验 `task.workspace_id` 与当前上下文匹配
- **跨 workspace 禁止**：API 层中间件统一校验 `workspace_id`

### 17.4 安全

| 风险点 | 对策 |
|--------|------|
| worktree 暴露 `.env` / `node_modules` | 打包 / 分享时按 `.gitignore` 过滤；public share 只允许访问 `docs/` 和 `screenshots/` |
| public share 页面路径穿越 | `deliverable_store.py` 的路径解析必须 `resolve()` + `relative_to()` 校验 |
| manifest.json 泄露内部路径 | public API 返回时剥离 `storage_path` 等内部字段，只返回 `artifact_type` + `content` |
| 大文件 DoS | 上传限制沿用现有 `pipeline_upload_max_mb`；zip 下载限制单任务 200MB |

### 17.5 监控与告警

| 指标 | 采集方式 | 告警阈值 |
|------|---------|---------|
| `workspace_disk_used_gb` | cron 每小时 `du -s` | > 80% 磁盘容量 |
| `task_artifact_count_total` | DB COUNT | -- (仅观测) |
| `manifest_rebuild_latency_ms` | 代码埋点 | > 5000ms |
| `archive_job_lag_days` | 最早未归档的 approved task age | > 45 天 |
| `worktree_orphan_count` | 没有对应 DB task 的 worktree 目录数 | > 0 |

---

## 18. 与现有系统的详细对接映射

### 18.1 现有组件的新角色

| 现有组件 | 当前角色 | 新角色 |
|---------|---------|--------|
| `delivery_docs.py` | 全局文档读写 | **降级为模板服务** -- 只提供模板内容，不做正式存储 |
| `pipeline_attachments.py` | 文件上传 + 路径校验 | **保留** -- 上传逻辑不变，但 `storage_path` 改为写到 `tasks/{id}/artifacts/` |
| `PipelineArtifact` (model) | 附件索引 | **扩展为 TaskArtifact** -- 增加 `version` / `status` / `artifact_type` registry |
| `PipelineStage.output` | LLM 产出 text | **保留** -- 每阶段完成后，额外物化到 `tasks/{id}/docs/0X-xxx.md` |
| `compile_deliverables()` | 汇总所有 stage output | **改造** -- 写到 `tasks/{id}/docs/00-summary.md`，不再写全局文件 |
| `PipelineTaskDetail.vue` artifacts 区 | 附件列表 | **重构** -- 拆出 `TaskArtifactTabs.vue`，按 8 Tab 展示 |

### 18.2 数据流（新旧对比）

**当前（有 bug）**：
```
stage 完成 -> write_stage_output() -> docs/delivery/0X.md（全局，会覆盖）
           -> PipelineStage.output（DB）
           -> PipelineArtifact（附件）-> data/pipeline_uploads/{task_id}/
```

**目标态**：
```
stage 完成 -> PipelineStage.output（DB，保留）
           -> TaskArtifact（DB 索引，version++）
           -> tasks/{task_id}/docs/0X-xxx.md（物化文件）
           -> manifest.json 异步刷新
           -> SSE event: artifact_updated
```

### 18.3 迁移期双写策略

迁移期间（预计 2 周），新老系统并行：

| 写操作 | 老路径 | 新路径 | 切换开关 |
|--------|--------|--------|---------|
| stage output 物化 | `docs/delivery/0X.md` | `tasks/{id}/docs/0X.md` | `ARTIFACT_STORE_V2=true` |
| compile | `docs/delivery/00-summary.md` | `tasks/{id}/docs/00-summary.md` | 同上 |
| 前端读取 | `/api/delivery-docs/{name}` | `/api/tasks/{id}/artifacts/{type}` | 前端判断 v2 路由是否 200 |

- 新任务默认走 v2
- 老任务（无 `tasks/{id}/` 目录）fallback 到 v1
- 2 周后 v1 标记 deprecated，4 周后移除 v1 写路径

---

## 19. 一句话总结

> **不是"在哪建目录"的问题，是"每一个分叉路口的代价算清楚再选"的问题。**
>
> 先决策、再设计、最后才编码。§15-18 就是这些分叉路口的全部答案。

