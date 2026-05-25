# 路线 B — 对结果负责的 AI 交付公司

> 立项日期：2026-05-25
> 状态：已立项，开始落地
> 决策记录：用户在 2026-05-25 13:19 选定 "执行 B"

---

## 一、为什么是 B

市场上 5 类对手都有空缺：

| 赛道 | 代表 | 缺什么 |
|------|------|--------|
| 专家市集 | WorkBuddy / Coze / Dify | 缺"项目完成"概念 |
| 代码协作 | Cursor / Windsurf | 缺"上线 + 后续" |
| 一键生成 | v0 / Bolt / Lovable | 缺"第二次迭代" |
| 自主 SWE | Devin / OpenDevin | 缺"企业可审计" |
| 垂直企业 | Salesforce Agentforce | 缺"通用" |

五个缺口本质是同一件事：**对结果负责的交付方**。我们的 `delivery_contract.py`（真测试 + 真预览 + 真验收三类硬证据）已经是这个方向的 60%，剩下 40% 是商业闭环。

---

## 二、三个产品支柱

### 支柱 1：结果合同（Outcome Contract）

**承诺**：达不到约定指标，30 天内全额退款。

**核心数据结构**：`outcome_contracts` 表 —— 业务目标 + 可测量指标 + 退款条款 + 30/60/90 验证节点。

**为什么是护城河**：所有 LLM 产品都不敢做退款承诺，因为输出不可验证。我们因为有 `delivery_contract` 的硬证据链，敢做。

### 支柱 2：永续维护（Living Product）

**承诺**：上线后 90 天自动监控，bug 4 小时内 PR，新需求接入既有项目。

**核心机制**：任务 3 态（new / iterate / maintain）+ `parent_task_id` 复用上游 artifact + 每日 preview 健康检查。

**为什么是护城河**：v0 / Bolt 抛弃式生成，第二次提需求 = 重新生成。我们有项目记忆 + 工件版本，项目可以活十年。

### 支柱 3：透明问责（Glass-Box Accountability）

**承诺**：每一个交付物点进去，能看到"哪个 agent 做的 / 什么时候 / 用了什么证据 / 否决了哪些备选 / 30 天后的实际效果"。

**核心数据结构**：`decision_graph` 表（决策图 + 后果图）。

**为什么是护城河**：Devin 类自主 agent 最大的痛是黑盒，企业法务不签。我们靠 `TaskArtifact` 的版本/audit 基础设施自然继承。

---

## 三、商业模式（直接定位差异）

| 项 | 同行 | 我们 |
|----|------|------|
| 计费单位 | 月费 / 任务次数 / token | **per Outcome** + 维护订阅 |
| 退款承诺 | 无 | **30 天指标不达成全额退** |
| 后续关系 | 一次性 | **永续团队**，项目终身维护 |
| 主合同 | T&Cs | **outcome_contract.json** 5 条 |
| 对手锚 | "比 Cursor 便宜" | "比外包团队便宜 80% + 永不离职" |

---

## 四、客户画像

- **核心**：想做产品但不想雇 5 个工程师的小老板 / 早期公司 / 企业内部紧缺资源的产品负责人
- **不做**：开发者 / 程序员（卷不过 Cursor）、大企业 IT（销售周期太长，后续接入）

---

## 五、Wave 重排（按"客户立刻能感知差异"优先级）

| Wave | 目标 | 客户能感知的话 | 主要文件 |
|------|------|---------------|---------|
| **W1** | outcome 合同立项 | "签了合同，达不到退钱" | `models/outcome_contract.py` + `api/outcome_contract.py` + Clarify 闸门 UI |
| **W2** | 证据链可视化 | "我能看到每个决策的依据" | `services/decision_graph.py` + `SharePage.vue` provenance tab |
| **W3** | 30/60/90 后果回路 | "60 天后他们还主动来问数据" | `task_scheduler.py` + 指标抓取适配器（Plausible / Stripe / GA） |
| **W4** | 永续维护订阅 | "上次的 bug 他们 4 小时就修好" | `parent_task_id` + maintain mode cron |
| **W5** | 客户共创闸门 | "他们改一句我的需求都来跟我确认" | feedback_slots + 闸门 UI |

> 之前提的"agent 深度 / 自演化 / 信号吸收"全部降权为内部工程改进 —— 重要但不卖钱。

---

## 六、Wave 1 落地（今天就开始）

**今日交付物**：

1. ✅ 本文档（战略锚定）
2. `backend/app/models/outcome_contract.py`  —— 3 张表：`outcome_contracts` / `outcome_metric_readings` / `outcome_checkpoints`
3. `backend/alembic/versions/x0y1z2a3b4c5_add_outcome_contract.py` —— 迁移
4. `backend/app/schemas/outcome_contract.py` —— Pydantic 模型
5. `backend/app/api/outcome_contract.py` —— 5 个端点：draft / sign / record-metric / checkpoint / get
6. `backend/tests/test_outcome_contract.py` —— happy path + reject path
7. 在 `main.py` 注册路由 + `models/__init__.py` 导出

**验收标准**（Karpathy 原则：每改可验证）：

- [ ] 模型可以 import 不报错
- [ ] 迁移可以 `make migrate` 跑通（PG + SQLite 双向兼容）
- [ ] `pytest backend/tests/test_outcome_contract.py -v` 全绿
- [ ] 调用 draft → sign → record-metric → checkpoint 链路通

**下一轮（Wave 1 后半段）**：
- Clarify 闸门 UI：Dashboard 输入一句话后，先弹"我们这样理解你的目标"卡片 → 客户改 / 签 → 才进 planning
- 把现有 `Dashboard.vue` 的"先给方案/直接执行"二选一替换成"草拟合同 → 签 → 启动"三段流程

---

## 七、KPI（B 路线成败标准）

| 指标 | 6 个月目标 | 衡量方法 |
|------|----------|---------|
| 签了 outcome 合同的项目 | ≥ 20 个 | DB 表 count |
| 30 天指标达成率 | ≥ 70% | checkpoint 通过率 |
| 退款率 | ≤ 15% | refund_status='refunded' / 总数 |
| 维护订阅续约率 | ≥ 60% | parent_task 链路活跃 |
| 客户能说出我们差异化的关键词 | ≥ 1（"退款"或"维护"） | 用户访谈 |

---

## 八、风险与缓解

| 风险 | 缓解 |
|------|------|
| 退款承诺被滥用（客户故意不付款） | 验收闸要客户**签电子合同 + 部分预付**（如 30%） |
| 指标抓取依赖客户系统（GA/Stripe）权限 | 提供 **手动录入 + 自动抓取** 双路径，手动需有截图证据 |
| Agent 实际能力撑不起 30 天指标达成 | 立项 Clarify 阶段就**明确放弃不可达成的项目**（不是所有项目都签合同） |
| 永续维护成本失控 | 维护订阅按月计费 + 单月工时上限（如 20h） |

---

## 九、不做什么（明确边界）

- 不做 **agent 市集 UI**（专家中心那种卡片墙）
- 不做 **任务计费**（即开即用、按次收钱的模式）
- 不做 **开发者工具**（Cursor 路线）
- 不做 **企业 IT 中台**（先 B2SMB，企业接入是 Year 2）
