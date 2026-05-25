# 产品体验断层修复计划

> 范围：CLAUDE.md 深度诊断中"产品体验和用户感知断层"五条
> 原则：不重构没坏的东西、精准修改、每步可验证
> 时间：2026-05-22 起

---

## 五个病灶 → 五个修复块

| # | 病灶 | 修复块 | 主要文件 |
|---|------|--------|---------|
| A | Dashboard 提交后无过程叙事 | **进度叙事流** | `Dashboard.vue` / `Inbox.vue` / SSE 事件 |
| B | RCA 只抓硬失败、抓不到软烂活 | **软失败识别** | `quality_gates.py` / `FailureCard.vue` |
| C | 8-Tab 工程师视角、找不到链接 | **交付摘要头** | `PipelineTaskDetail.vue` / `TaskArtifactTabs.vue` |
| D | SharePage 没有验收叙事 | **成功卡 + 试用入口** | `SharePage.vue` / `DeliverableCards.vue` |
| E | i18n 覆盖不全 | **英文兜底** | `i18n/zh.json` + `en.json` + 各组件 |

---

## 执行阶段（依次推进，每阶段独立可验证）

### Phase A —— 进度叙事流（最伤体感，最先做）

**目标**：用户提交一句话后，能看到"AI 现在在做什么"，不是 spinner。

- A1. 在 `SSE` 现有 `agenthub:pipeline:events` channel 上确认事件粒度（stage:started / stage:llm-call / stage:completed）。需要时补一条 `stage:narrative` 事件，payload 含 `role`、`humanized_action`（如"架构师正在画系统图"）。
- A2. `Dashboard.vue` 提交后不要立刻跳走，原地展开一个 **`LiveProgressPanel`** 组件，订阅当前 task 的 SSE，按时间线显示最近 5 条 narrative。
- A3. `Inbox.vue` 的 active 行加 `current_stage` + `current_role` 两个轻量字段（已有 stage 字段，补 role 即可），鼠标悬停显示完整叙事。
- A4. 后端：`pipeline_engine.py` 在 stage 进入 LLM 调用前 emit 一条人话事件，role + 一句话动作。映射表写死在 `STAGE_HUMANIZED_ACTIONS` 常量里。

**验收**：提交一句话后，前端 5 秒内出现第一条叙事，每个 stage 切换都有更新。

---

### Phase B —— 软失败识别（让烂活儿露马脚）

**目标**：启发式过了但内容糟糕的输出，能被显式标红并触发 FailureCard。

- B1. 在 `quality_gates.py` 加一个"一致性检查"维度：用 embedding 相似度比对 design 输出 vs planning 输出、code 输出 vs architecture 输出，低于阈值则 `consistency_score=low`。
- B2. 现有 `can_proceed` 不变，但新增 `soft_warnings` 字段。 stage 完成时把 soft_warnings 写到 `PipelineStage.metadata`。
- B3. `FailureCard.vue` 触发条件从"硬错误"扩展为"硬错误 OR soft_warnings 非空"，UI 上区分红色（硬）/黄色（软）。
- B4. 默认开关 `SOFT_FAILURE_DETECTION_ENABLED=true`，可配置关闭以兼容老测试。

**验收**：构造一个 PRD 跟 code 故意对不上的样本，能看到黄色 FailureCard，文案如"代码与 PRD 一致性偏低，建议人工复核"。

---

### Phase C —— 交付摘要头（让商业用户一眼看到链接）

**目标**：详情页顶部不是 8 个 tab，而是 **Preview URL + 一句话验收摘要 + 主 CTA**。

- C1. `PipelineTaskDetail.vue` 顶部插入 `<DeliveryHeader>` 组件：
  - 大字 Preview URL（点击新窗口打开），带健康状态色点
  - 一句话验收摘要（从 acceptance 阶段 artifact 摘要字段抽，没有则 fallback "AI 已交付 N 份文档"）
  - 主按钮"验收"，次按钮"分享"
- C2. 8-Tab 下移到摘要头之下，作为"详情"区。
- C3. 没有 preview_url artifact 时显示"部署未完成"灰态，但仍展示分享按钮（让用户能拿走文档）。

**验收**：打开任意已交付任务详情页，第一屏看到的就是链接 + 摘要 + 验收按钮，无需滚动。

---

### Phase D —— SharePage 成功卡 + 试用入口

**目标**：外部客户打开分享链接，看到的是 SaaS 风格的验收页，不是 markdown 仓库。

- D1. `SharePage.vue` 顶部增加 `<AcceptanceSummaryCard>` 组件（成功版的 4-field）：
  - **交付了什么**（一句话）
  - **试用入口**（Preview URL，带"在新窗口打开"）
  - **后续负责人**（owner_email，从 task 取）
  - **验收期限 / 已验收时间**
- D2. markdown 文档区折叠到二级，标题改成"交付物详情（点击展开）"。
- D3. 复用 `DeliverableCards.vue` 但加 `compact-mode` prop。

**验收**：用一个 demo share token 打开 SharePage，第一屏是验收卡 + 试用按钮，文档默认折叠。

---

### Phase E —— i18n 英文兜底

**目标**：所有用户可见文案都有 en 翻译，无中文硬编码。

- E1. 扫描 `src/views/**` 和 `src/components/**` 找出 `>.+[一-龥].+<` 模式的硬编码中文。
- E2. 抽到 `i18n/zh.json` + 对应 `en.json`，按页面命名空间：`pipelineDetail.*` / `share.*` / `qa.*` / `deploy.*` / `failure.*`。
- E3. 重点页面：`PipelineTaskDetail.vue`、`SharePage.vue`、`TaskQATab.vue`、`DeployPreviewCard.vue`、`FailureCard.vue`、`TaskArtifactTabs.vue`。
- E4. 错误提示：`api/*.py` 抛出的中文 detail 通过新增 `error_codes.py` 映射成 i18n key，前端按 key 翻译。

**验收**：切到 en，五个重点页面 + 一个失败任务，找不到中文（图片里的字除外）。

---

## 跨阶段约束

- 不动 backend test 套件除非新功能要补测；老测试必须仍绿。
- 每个 Phase 独立提交，commit message 用 `[phase-A]` / `[phase-B]` 前缀。
- 前端改动跑 `pnpm lint && pnpm build`；后端改动跑 `make test-unit`。
- 不引入新依赖。embedding 相似度优先复用 `services/vector/` 已有能力。

---

## 执行顺序

A → C → D → B → E

理由：
1. **A 最伤体感**（spinner 干等 5 分钟），先解锁。
2. **C 紧随其后**：商业用户进详情页第一眼的体验，改一个组件就能见效。
3. **D 承接 C**：外部分享是商业闭环，不能用工程师页。
4. **B 是底层质量**：依赖 embedding 服务，工程量稍大，放中段。
5. **E 收尾**：等前四个 phase 的新文案都稳定后再统一 i18n，避免来回返工。

---

## 实施结果（2026-05-22 第一轮）

| Phase | 状态 | 关键改动 |
|------|------|---------|
| A | ✅ 已落地 | `pipeline_engine.STAGE_HUMANIZED_ACTIONS` + `stage:processing` 事件扩展 `narrative/role`；`PipelineTaskDetail.vue` 顶部加 `live-narrative` 实时叙事条 + 最近 5 条 feed |
| C | ✅ 已落地 | 新增 `DeliveryHeader.vue`：Preview URL + 验收摘要 + 试用/分享/验收按钮，注入到详情页顶部，8-Tab 下移 |
| D | ✅ 已落地 | 新增 `AcceptanceSummaryCard.vue`（成功版 4-field 卡：交付了什么/试用入口/负责人/验收期限）；`SharePage` 文档区折叠为 `<el-collapse>` 默认收起 |
| B | ✅ 已落地 | `quality_gates.py` 加 `_check_cross_stage_consistency`（Jaccard 阈值 0.06，env `SOFT_FAILURE_DETECTION_ENABLED` 可关），新组件 `SoftWarningBanner.vue` 在详情页渲染黄色警告 |
| E | ✅ 第二轮完成 | 补齐 `TaskQATab.vue` / `DeployPreviewCard.vue` / `FailureCard.vue` / `TaskArtifactTabs.vue` / `UiMockupCard.vue` / `TaskArchDiagram.vue` 的英文兜底；`SharePage.vue` 脚本区状态与 fallback 改走 i18n；`backend/app/api/share.py` 增补 `artifacts` 返回，公开分享页可直接渲染 QA / Deploy / Preview 数据 |

### 已完成（Phase E v2）

- `TaskQATab.vue` / `DeployPreviewCard.vue` / `FailureCard.vue` / `TaskArtifactTabs.vue` 的中文硬编码已抽到 `zh.ts` / `en.ts`
- `SharePage.vue` 脚本区 `loadFailed` fallback 与状态 label map 已改走 i18n
- 公开分享接口现在回传 latest `TaskArtifact`，分享页顶部成功卡、QA 卡、部署卡不再依赖私有 task artifact API

### 后续可加（P1+）

- A：Inbox 行级 narrative tooltip（当前仅详情页有）
- B：从 Jaccard 升级到 embedding 相似度（复用 `services/vector/`）
- C：详情页"主 CTA"按 task.status 智能切换（执行中：取消；待验收：验收；已完成：分享）
- E：后端 `api/*.py` 中文 `detail` 统一迁移到 `error_codes.py` + 前端按错误码翻译


  
