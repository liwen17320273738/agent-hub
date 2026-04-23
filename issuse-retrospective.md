# agent-hub 全量 Issue 回顾与反思

> 截止 2026-04-23，共 45 个文件（21 个主 issue + 24 个 phase）+ 8 个 ADR。
>
> 这份文档不是"清单"，是**反思**：我们到底做了什么、漏了什么、重复了什么、学到了什么。

---

## 一、时间线全景

```
issuse01-02   项目审计 + 安全诊断
    ↓
issuse03      架构重构路线图 → phase1-5（统一 Agent 模型、AgentRuntime、Skills）
    ↓
issuse04      自动化能力深度分析 → phase1-4（项目接入、高危修复、DAG/MCP、差距评估）
    ↓
issuse05      角色矩阵 + 军团协作 → phase1（验收 + Cost Governor + 模板）
    ↓
issuse06      迁移/模板/军团状态 → phase + phase02（观测看板 + 学习回路 + 并行 DAG）
    ↓
issuse07      短板与风险 → phase01-03（pytest、Redis 双 worker、Jira/GitHub webhook）
    ↓
issuse08      Gateway 片段（未展开）
    ↓
issuse09      Resolvr 产品分支 → phaseA-B（WorkflowBuilder + SWE-Bench）
    ↓
issuse10      限流/429 事故 → phase（修复 + fallback + 测试）
    ↓
issuse11      验收体系 → phase（质量门 + FinalAcceptance + SLA）
    ↓
issuse12      IM↔验收断点 → phase（Wave 5：pause + notify + keyword routing）
    ↓
issuse13      "75 分"诊断 + 30 天抢修 → phase（T1-T7 可执行清单）
    ↓
issuse14      Plan/Act 双模态 → phase（Wave 6：plan_session + approve/reject）
    ↓
issuse15      与 issuse14 重复 → phase（OpenAI 兼容桥接层）
    ↓
issuse16      九大平台竞品分析
    ↓
issuse17      公网多通道接入操作记录
    ↓
issuse18      产品路线图（吸收九大平台优势）
    ↓
issuse19      重诊断："为什么让人头疼"
    ↓
issuse20      30 天执行手册（路径 A：AI 交付平台）
    ↓
issuse21      任务工件体系设计 → phase（Phase 0-4 落地分期）
```

---

## 二、5 个阶段划分

| 阶段 | Issue 范围 | 做的事 | 一句话概括 |
|------|-----------|--------|-----------|
| **S1 审计期** | 01-02 | 全面扫描代码、安全、架构 | "知道自己有多烂" |
| **S2 工程期** | 03-07 | Agent 统一、pipeline 加固、DAG、pytest、webhooks | "把地基补上" |
| **S3 产品期** | 08-14 | WorkflowBuilder、限流修复、验收闭环、Plan/Act | "开始像个产品了" |
| **S4 战略期** | 15-18 | 竞品分析、多通道接入、路线图 | "抬头看路" |
| **S5 收敛期** | 19-21 | 诊断痛点、30 天执行、工件体系 | "砍掉噪音，聚焦交付" |

---

## 三、实际完成 vs 只是写了

### 已完成（有对应 .phase.md 标记 "已落地/已交付"）

| Issue | 交付物 |
|-------|--------|
| 03 phase1-5 | Agent 统一模型、AgentRuntime、Profile UI、Quality Gate、Skills |
| 04 phase1-3 | 项目接入、高危安全修复、DAG/MCP/browser/delegate |
| 05 phase1 | Cost Governor、验收 URL/截图、企业模板 |
| 06 phase+02 | 观测看板、学习回路、DAG 并行修复 |
| 07 phase01-03 | 156→199+ pytest、Redis pubsub、external_links、Jira/GitHub webhook |
| 09 phaseA-B | WorkflowBuilder 画布、SWE-Bench 骨架 |
| 10 phase | 限流修复、fallback、DagCanvas、Vitest |
| 11 phase | FinalAcceptanceModal、质量门 UI、SLA |
| 12 phase | Wave 5（pause_for_acceptance、IM notify、keyword routing）|
| 14 phase | Wave 6（Plan/Act、plan_session、Inbox）|
| 15 phase | OpenAI 兼容桥接层 |

### 只是写了（没有 phase 标记交付，或明确是战略/诊断文档）

| Issue | 性质 | 还有用吗 |
|-------|------|---------|
| 01 | 初始审计 | 有 — 安全/架构 backlog 未清零 |
| 02 | 安全深挖 | 有 — SSRF/API key 部分项未关闭 |
| 04 phase4 | 差距评估 | 有 — "距离军团还差几波"仍成立 |
| 08 | 片段 | 无 — 已被 15.phase 取代 |
| 09 | Resolvr 产品方向 | 待定 — 是否还追这条线？ |
| 13 | "75 分"诊断 | 有 — 诊断仍准确 |
| 13 phase | T1-T7 清单 | 部分重叠 — 与 issuse20 执行手册重叠 |
| 16 | 竞品分析 | 有 — 战略参考 |
| 17 | 公网接入记录 | 有 — 运维参考，tunnel 可能过期 |
| 18 | 路线图 | 有 — 与 issuse20/21 互补 |
| 19 | 重诊断 | 已标记被 issuse20 取代，保留价值观 |
| 20 | 30 天手册 | **当前执行文档** |
| 21 + phase | 工件体系 | **当前设计 + 分期文档** |

---

## 四、反复出现的 5 个病根

从 issuse01 到 issuse21，有些问题**每隔 3-5 个 issue 就重新出现一次**，说明之前没有真正解决：

### 病根 1：「产物不可见」

| 出现位置 | 怎么说的 |
|----------|---------|
| issuse01 | "产出没有统一归档" |
| issuse06 | "军团跑完了，交付物散在各处" |
| issuse11 | "验收看不到全貌" |
| issuse13 | "75 分，但客户看不到结果" |
| issuse19 | "跑了半天，不知道产出了什么" |
| issuse21 | **专项解决** — 但还没实施 |

**教训**：这个问题从第 1 天就存在，到第 21 个 issue 才正式建架构。之前每次都是"加个面板""加个 tab"的表层修补。

### 病根 2：「导航混乱 / 页面太多」

| 出现位置 | 怎么说的 |
|----------|---------|
| issuse01 | "前端路由过多" |
| issuse09 | "要不要砍页面做垂直产品" |
| issuse13 | "30 个入口看着头疼" |
| issuse19 | "sidebar 30+ 入口，看不出重点" |
| issuse20 | 30→5 入口（尚未执行）|

**教训**：每次加新功能就加新页面，从不合并旧页面。issuse20 的"合并不删"原则是对的，但更根本的问题是**没有产品经理角色在每次迭代时把关**。

### 病根 3：「文档写了很多，代码没跟上」

统计：21 个主 issue + 24 个 phase = **45 个 markdown 文件**。但：

- issuse03 写了路线图 → 花了 5 个 phase 才做完基础
- issuse13 写了 30 天计划 → 部分与 14/15 重叠
- issuse18 写了路线图 → 与 issuse20 重叠
- issuse20 写了 30 天计划 → issuse21 发现底座没设计
- issuse21 写了架构 → 还要 Phase 0 再确认一轮才能动手

**教训**：文档产出速度 >> 代码交付速度。不是文档写多了（文档是对的），而是**每份新文档都在发现"之前的文档漏了什么"，导致永远在补设计、不在写代码**。

### 病根 4：「全局资源没有按任务隔离」

| 出现位置 | 具体问题 |
|----------|---------|
| issuse01 | "`create_all` 替代 Alembic，多租户无隔离" |
| issuse06 | "12 个模板共享同一个交付目录" |
| issuse10 | "限流是全局的，不是按任务的" |
| issuse21 | "`docs/delivery/*.md` 全任务共享会互相覆盖" |

**教训**：从 DB 到文件系统到限流，"全局共享"是默认模式。每次发现一个新的共享冲突，修一个点。直到 issuse21 才系统性地提出"按任务隔离"原则。

### 病根 5：「功能加了但没闭环验证」

| 出现位置 | 具体问题 |
|----------|---------|
| issuse04 | "E2E 链路存在但依赖外部 CLI，没端到端测过" |
| issuse07 | "没有 pytest，全靠手动 smoke" |
| issuse09 phaseB | "WorkflowBuilder 画布有了，后端不执行" |
| issuse10 | "resume API 语义不对，前端状态是假的" |
| issuse12 | "部署先于验收跑了，没人发现" |

**教训**：每个功能写完就写下一个，没有"闭环验证 → 发现问题 → 修到真正能用"的习惯。issuse20 的"每周验收"机制就是为了打破这个循环。

---

## 五、当前文档体系的关系图

```
                    ┌─ issuse01-02 ─── 审计基线（仍有未关闭安全项）
                    │
                    ├─ issuse03-07 ─── 工程地基（已交付，phase 文件记录）
                    │
                    ├─ issuse08 ─────── 废弃（片段，被 15.phase 取代）
                    │
                    ├─ issuse09 ─────── 独立产品分支（Resolvr，待决定是否继续）
                    │
                    ├─ issuse10-14 ──── 产品闭环（已交付，Wave 5-6）
                    │
                    ├─ issuse15 ─────── 重复（=14 正文 + phase 是 OpenAI 桥）
                    │
                    ├─ issuse16 ─────── 竞品分析（战略参考）
                    │
                    ├─ issuse17 ─────── 公网接入运维记录
                    │
                    ├─ issuse18 ─────── 路线图（与 20 互补）
                    │
  当前活跃 ────→   ├─ issuse19 ─────── 产品诊断（被 20 取代，保留价值观）
                    │
  当前执行 ────→   ├─ issuse20 ─────── 30 天执行手册 ←─── 所有改造的调度中心
                    │                        ↑ 引用
  当前设计 ────→   └─ issuse21 + phase ── 工件体系架构 + 落地分期
```

---

## 六、6 条教训（给自己的）

### 1. 先验证再扩展，不要先扩展再回头补

issuse03 统一了 Agent 模型 → 然后加了 14 个 agent → 然后发现 pipeline 跑不通 → 然后补 DAG → 然后发现验收没闭环 → 然后补 FinalAcceptance → 然后发现文档没归档 → 然后写 issuse21。

**正确的顺序**：1 个 agent + 1 条完整链路跑通 → 再加第 2 个 agent。

### 2. 每个 issue 必须有明确的"关闭条件"

很多 issue 写完诊断就算了，没有"什么算做完"。issuse01/02 的安全项到今天可能还没全部关闭。

**规则**：每个 issue 顶部必须有 `## 关闭条件`，全部 checkbox 勾完才能关。

### 3. 不要用新 issue 替代修旧 issue

issuse13 重新诊断了 issuse01 的问题，issuse19 重新诊断了 issuse13 的问题，issuse21 重新设计了 issuse06 就该解决的交付归档。

**规则**：如果新 issue 和旧 issue 有 >30% 重叠，应该更新旧 issue，不要新开。

### 4. 文档数量不等于进展

45 个文件不代表做了 45 件事。真正交付的工程变更集中在 issuse03-07 的 phase 和 issuse10-14 的 phase。其余是诊断、规划、战略 —— 有价值，但不能替代代码。

**规则**：每写一份规划文档，必须同时开始动手做其中最小的一件事。

### 5. "合并不删"是对的，但更重要的是"不再新建"

issuse20 说"旧路由保留，sidebar 只暴露 5 个"。但同时又新建了 Inbox/Team/Workflow/Assets/SharePage 5 个新页面。

**风险**：30 天后可能变成 30+5=35 个页面。必须在新页面上线的同一天，把被替代的旧页面从 router 里 redirect，而不是"留着以后再说"。

### 6. 架构决策要前置，不能边写边定

issuse21.phase 加了 Phase 0 是对的。但本该在 issuse03 就建立"决策记录"机制（ADR）。如果从第 1 天就有 ADR 文件夹，后面每个 issue 就不需要重新讨论"DB vs 文件谁权威""版本怎么存"这些基础选型。

**规则**：新建 `docs/adr/` 目录，每个架构决策一个文件（`0001-workspace-root.md` / `0002-db-as-source-of-truth.md`），格式：背景 → 选项 → 决策 → 后果。

---

## 七、当前状态一句话

> **45 个 issue 文件，真正改变了代码的只有 ~15 个 phase 文件。**
> **当前活跃的只有 issuse20（执行手册）和 issuse21（工件体系）。**
> **最大的风险不是"不知道做什么"，是"写了太多'做什么'，没有足够的'在做'。"**

---

## 八、建议的下一步

1. **关闭 issuse01-18 的所有 issue** — 逐个检查未关闭项，要么标 "done"，要么迁移到 issuse20 的 backlog
2. **issuse15.md 删除** — 与 issuse14 重复
3. **issuse08.md 标记废弃** — 片段，已被 15.phase 取代
4. **issuse09 做决策** — Resolvr 是否继续？是就开独立 repo，否就标废弃
5. **建 `docs/adr/` 目录** — 把 issuse21 §16 的 8 个决策迁移过去
6. **不再新开 issue 编号** — 直到 issuse20 的 30 天 checkbox 至少完成 50%
7. **开始写代码** — Phase 0 确认完就动手，不再写新的诊断文档

---

## 九、文件状态速查表

| 文件 | 状态 | 说明 |
|------|------|------|
| issuse01.md | 审计基线 | 仍有未关闭安全项 |
| issuse02.md | 审计基线 | 仍有未关闭安全项 |
| issuse03.md + phase1-5 | **已交付** | 架构重构全部完成 |
| issuse04.md + phase1-3 | **已交付** | 项目接入 + 高危修复完成 |
| issuse04-phase4.md | 差距评估 | 仍可参考 |
| issuse05.md + phase1 | **已交付** | Cost Governor + 模板 |
| issuse06.md + phase/02 | **已交付** | 观测 + 学习 + DAG 并行 |
| issuse07.md + phase01-03 | **已交付** | pytest + webhook + external_links |
| issuse08.md | **废弃** | 片段，被 15.phase 取代 |
| issuse09.md + phaseA-B | **已交付（画布）** | Resolvr 产品方向待决 |
| issuse10.md + phase | **已交付** | 限流修复 |
| issuse11.md + phase | **已交付** | 验收体系 |
| issuse12.md + phase | **已交付** | Wave 5 IM 闭环 |
| issuse13.md + phase | 诊断 + 清单 | 部分与 20 重叠 |
| issuse14.md + phase | **已交付** | Wave 6 Plan/Act |
| issuse15.md | **重复** | 与 issuse14 内容相同，应删除 |
| issuse15.phase.md | **已交付** | OpenAI 兼容桥 |
| issuse16.md | 战略参考 | 竞品分析 |
| issuse17.md | 运维记录 | 公网接入 |
| issuse18.md | 战略参考 | 路线图 |
| issuse19.md | **被 20 取代** | 保留价值观参考 |
| issuse20.md | **W1-W4 已交付** | 30 天手册 — AI 交付平台 |
| issuse21.md + phase | **Phase 0-4 已交付** | 工件体系全链路落地 |
| issuse-retrospective.md | 本文件 | 全量回顾 |

---

## 六、issuse20 四周执行成果总结（2026-04-22 → 2026-04-23）

### W1：品牌统一 + Sidebar 收口
- 全局替换 "Wayne Stack" → "Agent Hub"
- Sidebar 30 入口收口到 5 个：控制台 / 收件箱 / 团队 / 工作流 / 资产

### W2：核心工作流闭环
- 工作流编译器 `workflow_compiler.py` + 运行器 `workflow_runner.py`
- 任务详情页重构为 3-tab（概览 / 交付物 / 角色泳道）
- `DeliverableCards.vue` 8 张交付文档明信片

### W3：Hero 路径 + 分享
- Dashboard CTA：一句话输入 → 先给方案 / 直接执行
- HMAC-SHA256 分享令牌：7/30/365 天 TTL
- `SharePage.vue` 公开页：无需登录查看交付物 + 验收闸门
- 后端 `share.py` 5 个端点：generate / get / doc / accept / reject

### W4：企业要素 + 可见性
- **Workspace RBAC**：`Workspace` + `WorkspaceMember`（admin/manager/member）三角色
- **Credentials Vault**：Fernet 加密存储，API 不暴露明文
- **Cost Governor**：任务级预算，60% 自动降级 DeepSeek，100% 硬上限阻断
- **失败 RCA 业务卡片**：4 字段（卡在哪 / 为什么 / 谁处理 / 下一步）+ 操作按钮
- **交付包 ZIP 下载**：8 docs + screenshots + manifest.json
- **i18n**：vue-i18n 中英双语，sidebar 全量覆盖
- **测试**：27 个新测试全部通过

---

## 七、issuse21 工件体系落地成果（Phase 0-4）

### Phase 0：架构决策确认
- 8 个决策全部写入 config：`workspace_root`、`artifact_store_v2=True`
- DB 权威、manifest 缓存策略确认

### Phase 1：任务级目录（W1-W2 同步完成）
- `task_workspace.py` 创建任务目录 + manifest.json
- 双写模式：旧 `docs/delivery/*.md` + 新 `tasks/TASK-xxx/docs/`

### Phase 2：DB 工件索引 + 版本化
- **`TaskArtifact`** 模型：版本追踪 + `is_latest` + `status(active/superseded)`
- **`ArtifactTypeRegistry`**：12 个预置类型（需求/PRD/UI/架构/代码/测试/验收/运维/截图/附件/部署清单/实现说明）
- **工件 CRUD API**：`GET/POST /tasks/{id}/artifacts/{type}` + `POST .../supersede`
- **`artifact_writer.py`**：pipeline engine stage 完成自动写入 v2 artifact
- **`manifest_sync.py`**：异步重建 manifest.json 缓存

### Phase 3：8 Tab 交付视图
- **`TaskArtifactTabs.vue`**：8 个固定 Tab + 顶部完成度缩略条
- **`TaskDocTab.vue`**：Markdown 渲染 + 版本历史下拉 + superseded 标记
- **`TaskCodeTab.vue`**：代码工件展示（路径/分支/commit/变更文件/测试状态）
- 任务详情页默认打开"交付物"Tab，不再默认概览大杂烩

### Phase 4：迁移 + 归档
- **`workspace_archiver.py`**：已验收 30 天 / 已取消 7 天自动 tar.gz 归档
- **`artifact_store_v2=True`**：新任务只写 v2 路径，旧任务 fallback 兼容
- `pipeline_engine.py` 集成 `artifact_writer.write_artifact_v2()`
- 14 个新单测全部通过

### 关键指标（W1-W4 + Phase 0-4 合计）
| 指标 | 值 |
|------|-----|
| Sidebar 入口数 | 5（从 30+） |
| 新 API 端点 | 20+ |
| 新 Vue 组件 | 13+ |
| 新后端模型 | 5（Workspace / WorkspaceMember / Credential / TaskArtifact / ArtifactTypeRegistry） |
| 测试通过率 | 322/322 (100%)（修复 4 个 Redis 弹性降级 + 27 W4 + 14 Phase 2-4） |
| Pydantic 警告 | 0（@validator → @field_validator + .dict() → .model_dump()） |
| ADR 文件 | 8（docs/adr/0001-0008） |
| 废弃 Issue | issuse08（废弃）+ issuse15（重复） |
| Frontend Build | 0 errors |
| Backend 健康 | healthy (PostgreSQL + Redis) |
| Hero Path E2E | 全链路通过（12类型 + 工件写入 + 版本升级 + is_latest翻转） |

---

## 项目自测（Self-Test）— 12 Projects × 17 Tests

> 执行日期: 2026-04-23

### 覆盖范围

12 个多样化项目（Web/API/数据/移动/DevOps/安全/文档/SaaS/IoT/AI/可观测/教育），每项目 17 项测试（创建→7阶段推进→4工件写入→版本升级→工件列表→工件详情→Pipeline工件→分享链接→分享访问→ZIP下载→预算→RCA→质量→Supersede→更新）。

### 自测发现并修复的问题

| # | 问题 | 严重性 | 修复 |
|---|------|--------|------|
| 1 | 空标题可创建任务（无校验） | 中 | `field_validator("title")` |
| 2 | 已完成任务仍可推进（状态未防护） | 中 | advance 增加 `status==done` 前置检查 |
| 3 | 分享令牌 ~6% 随机失败（HMAC字节含 `\|`） | 高 | 签名改用 hex 编码 |

### 最终结果

| 指标 | 值 |
|------|-----|
| 测试项目 | 12 |
| 总测试用例 | 312 |
| 通过率 | **100.0%** |
| 边界条件测试 | 7/7 PASS |
| DAG模板验证 | 15 templates OK |
| 问题发现并修复 | 3/3 |
| 单测回归 | 322/322 PASS |
