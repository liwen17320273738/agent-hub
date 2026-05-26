# Agent Hub 全面诊断报告

> 关联 Linear: [WAY-12](https://linear.app/wayneli/issue/WAY-12/agent-hub-全面诊断从产品到agent团队的差距分析与修复计划)
> 日期：2026-05-25

---

## 一、诊断方法论

通过全链路代码审查（backend + frontend 共计 50+ 核心文件），从四个维度交叉验证产品能力：

1. **产品交付闭环** — 需求 → 执行 → 验收 → 部署 → 分享
2. **Agent 团队能力** — 13 个 Agent 的专业深度、协作机制、学习能力
3. **质量门禁体系** — 自检 → 质量门 → 同行评审 → 护栏 → 验收全链路
4. **验收与交付可信度** — 证据链完整性、交付合同硬度

---

## 二、问题清单（按严重度分级）

### P0 — 必须立即修复（影响交付可信度）

#### P0-1: Agent 专业深度实质上是 "LLM 常识水平"，不是 "30 年专家"
**文件**: `backend/app/services/pipeline_engine.py` lines 383-715 (`STAGE_ROLE_PROMPTS`)
**位置**: 所有 13 个 Agent 的 system prompt

每个 Agent 的 prompt 是静态模板文本。例如：
- 架构师 Agent 的 prompt 只说"你设计过银行核心系统"，但没有注入**真实架构决策模式库**
- 安全 Agent 的 prompt 只说"检查 SQL 注入/XSS"，但没有注入**OWASP Top 10 最新变种的检测模式表**
- 验收官 Agent 的 prompt 只说"逐条核对验收标准"，但没有注入**专业验收检查清单**

**本质问题**：Agent 的"专业能力" = 底层 LLM 的常识水平。换一个弱模型（如 DeepSeek），输出质量直接下降。真正的专家知识（模式库、决策树、检查清单）为零。

**影响范围**：全系统。所有阶段的输出质量都不稳定。

---

#### P0-2: 同行评审是 "一个 LLM 评另一个 LLM"，缺乏真实的领域对标
**文件**: `backend/app/services/pipeline_engine.py` lines 141-293 (`STAGE_REVIEW_CONFIG`)
**位置**: 每条 peer review 的 reviewer_prompt

评审链：
- 架构师评审规划（计划）→ 开发评审架构 → 测试评审开发 → 验收评审测试 → CEO 评审验收

**核心问题**：评审是"同级别 Agent 用 LLM 判断"。架构师评审 PRD 时，没有**技术可行性模板**、没有**行业对标库**（"同类产品通常..."）。验收评审测试报告时，没有**专业的验收检查清单**。

**结果**：评审 ≈ "觉得 OK"，不是真审查。

---

#### P0-3: 质量门禁的 LLM 深度评估用的是同一个模型的二次调用
**文件**: `backend/app/services/quality_gates.py` lines 502-557 (`_llm_quality_evaluation`)
**位置**: LLM evaluation call

Quality Gate 的 LLM deep evaluation 用的是 `app_settings.llm_model`，默认与管线 Agent 是**同一个模型**。这意味着"一个模型写的东西让同一个模型来评质量"。

**本质问题**：没有任何外部/独立质量视角。如果模型有系统性盲点（比如一直遗忘记测试覆盖率），这个门禁永远发现不了。

---

#### P0-4: 多个关键服务模块零单元测试覆盖
**文件**: 全局扫描结果

**零测试覆盖的关键模块**：
- `agent_runtime.py` — Agent 执行引擎核心（0 个专用测试文件）
- `agent_delegate.py` — 跨 Agent 委托机制（0）
- `agent_bus.py` — 异步 Agent 通信（0）
- `learning_loop.py` — 学习回路（0，除了 `test_learning_targeting.py` 覆盖了一个边缘功能）
- `guardrails.py` — 安全护栏（0）
- `quality_gates.py` — 质量门禁核心评估逻辑（0）
- `pipeline_engine.py` — 管线引擎核心（0，只有集成测试覆盖）

**影响**：这些是系统的"心脏"。没有测试意味着每次改动都可能引入回归，重构几乎不可能。

---

#### P0-5: 驳回自我修复机制缺乏"真正学会"的能力
**文件**: `backend/app/services/dag_orchestrator.py` lines 441-500 (`_reset_to_stage`)
**文件**: `backend/app/services/learning_loop.py` lines 97-147 (`capture_signal`)

驳回修复机制目前：
1. 接收驳回 → 记录 LearningSignal → 重置目标 stage 到 PENDING
2. 注射驳回文本到 agent 的 reject_feedback 字段
3. 如果信号达到阈值（3 条），蒸馏成 PromptOverride 并注入

**问题**：
- 蒸馏只做"文本规则注入"，不修正 agent 的**知识结构**
- 同一问题在不同任务中可能反复犯（因为每个任务独立）
- 没有跨项目知识沉淀（"A 项目犯过的错，B 项目自动免错"）

---

### P1 — 重要但不阻塞交付

#### P1-1: Agent 协作本质上是"单向管道"，不是"真正的团队"
**文件**: `backend/app/services/collaboration.py`
**文件**: `backend/app/services/agent_delegate.py`
**文件**: `backend/app/services/agent_bus.py`

现有协作机制：
- **串行传递**（collaboration.py）— A 做完传给 B，单向管道
- **delegate_to_agent**（agent_delegate.py）— 当前 agent 可以呼叫另一个，请求/响应模式
- **agent_bus** — Redis 发布/订阅，管线尚未真正使用

**缺失的团队协作模式**：
- 架构师做方案时，安全 Agent 没有主动提醒"你的 JWT 配置有风险"
- 开发编码时，测试 Agent 没有提前准备测试环境
- 没有"通晒评审"（所有 agent 同时看一份产出，各自提专业意见）
- 没有冲突仲裁（架构师说微服务，开发说单体，谁拍板？）

---

#### P1-2: Outcome Contract 存在但未接入管线
**文件**: `backend/app/services/outcome_contract_service.py`
**文件**: `backend/app/models/outcome_contract.py`

`outcome_contract` 的表和评估逻辑已实现，但：
- 管线没有在任何阶段自动创建 outcome contract
- Dashboard 没有"草拟合同→签字→启动"的三段流程
- Clarify 闸门（"我们这样理解你的目标"）尚未实现

目前是"半成品"状态——代码在仓库里但没人用。

---

#### P1-3: 自检（self_verify）仅做启发式检查，不实际验证内容质量
**文件**: `backend/app/services/self_verify.py`

```python
# Line 15-16
# NOTE: LLM-based quality evaluation is planned but not yet implemented.
# Current checks are purely heuristic (pattern matching, length, keyword).
```

当前检查项：
- 格式：Markdown 标题存在 → 不是格式正确
- 长度：>= 最小字符数 → 不是内容充实
- 必要章节：包含关键章节名 → 不是章节有实质性内容
- 占位符：检测 TODO/TBD → 检测范围有限

**问题**：自检是"看起来有检查"但**不防住任何实质性问题**。写着 500 字废话可以通过所有检查。

---

#### P1-4: 13 个 Agent 中有 6 个角色（安全/法务/数据/市场/财务/设计）不适合纯文本输出
**文件**: `backend/app/services/pipeline_engine.py` lines 606-715

安全 Agent 让写"安全审计报告"，法务 Agent 让写"合规审查报告"。

**问题**：这些角色的真正价值在于**交互**（安全扫描代码、法务审查合同），而不是写出"一个看起来像报告的东西"。目前它们只能"假装输出报告"，无法真正调用安全扫描工具或法律数据库。

---

#### P1-5: Hermes 质量监督 Agent 的存在意义不明确
**文件**: `backend/app/agents/seed.py` lines 1056-1119

Hermes 的职责是"统一质量监督"，但它的审查链（自检→质量门→同行评审→护栏→可观测→验收）与现有的 `execute_stage` 中的 6 层成熟化完全重叠。

**问题**：Hermes 是一个"重复的检查器"，不是增量价值。它没有独立的数据源或不同的模型视角。

---

### P2 — 改进提升

#### P2-1: 前端设计系统缺失
- **现状**：Element Plus 组件库 + 深色主题 + 标准样式
- **缺少**：设计 Token 没有在前端代码中落地，没有主题系统，没有组件变体规范
- **Pencil 状态**：MCP 已注册但未连接，项目无 `.pen` 文件

#### P2-2: Learning Loop 的自动激活策略可能造成质量下降
**文件**: `backend/app/services/learning_loop.py` lines 56-76

```python
AUTO_PROMOTE_MIN_APPROVE_RATE = 0.70
```

当 `auto_apply=True` 时，蒸馏出的 PromptOverride 自动激活。如果蒸馏质量不高（比如 LLM 归纳错了根本原因），可能会把错误规则注入到后续任务的 system prompt 中。

**问题**：自动激活缺少"验证集"——应该让新规则在 shadow 模式下跑 N 个任务验证后再自动激活。

#### P2-3: 没有"Agent 能力画像"反馈给用户
- 团队页面（Team.vue）显示 Agent 的雷达图（"分析": 95, "设计": 98），但这些是**硬编码的数字**，不是真实运行数据
- 用户看不到"这个 Agent 过去做的项目通过率是多少"

#### P2-4: 测试集中在集成测试层面，单元测试严重不足
56 个测试文件中，大部分是集成/端到端测试。关键业务逻辑的纯函数测试缺失。

---

## 三、问题分类汇总

| 类别 | P0 | P1 | P2 | 总计 |
|------|-----|-----|-----|------|
| Agent 专业能力 | 2 | 2 | 1 | 5 |
| 质量门禁 | 2 | 1 | 0 | 3 |
| 测试覆盖 | 1 | 0 | 1 | 2 |
| 协作机制 | 0 | 1 | 0 | 1 |
| 学习能力 | 1 | 0 | 1 | 2 |
| 产品完整性 | 0 | 1 | 1 | 2 |

---

## 四、分阶段修复计划

### Phase A — 立即止血（本周，P0 修复）

**A1: 给每个 Agent 注入领域知识库**
- 修改 `STAGE_ROLE_PROMPTS`，为每个 stage 注入结构化的知识表
- 架构师：注入架构决策模式库（微服务 vs 单体决策树、CAP 取舍场景）
- 安全：注入 OWASP Top 10 + CVE 模式库表
- 验收：注入专业的验收检查清单（SaaS/电商/金融等场景化）
- 目标：不增加 LLM 调用次数，只在 system prompt 里加几百行结构化的领域知识

**A2: 为同行评审注入独立评审模板**
- 修改 `STAGE_REVIEW_CONFIG`，每个 reviewer_prompt 改成：
  - "请对照以下检查清单逐项评估（不满足任一 → REJECT）"
  - 清单包含具体的技术可行性、一致性、完整性检查项

**A3: 给 Quality Gate 的 LLM 评估换成独立的强模型**
- 修改 `_llm_quality_evaluation`，使用配置中的 `quality_gate_model`（与 `llm_model` 隔离）
- 默认：quality_gate_model = gpt-4o 或 claude-sonnet（与执行模型错开）

**A4: 给零测试覆盖的关键模块补单元测试**
- 优先级：`agent_runtime.py` > `agent_delegate.py` > `learning_loop.py` > `guardrails.py` > `quality_gates.py`
- 每个模块至少覆盖：happy path + error path + edge case

---

### Phase B — 强化基础（2 周，P1 修复）

**B1: 实现真正的并行协作**
- 在 `agent_bus.py` 的基础上，让设计/架构/安全 Agent 在方案阶段同步协作
- 架构师产出架构草稿 → 自动广播给安全 Agent 做安全预审 → 安全 Agent 返回"我发现 3 个问题"
- 实现 Agent 间的"通晒评审"模式

**B2: 解决 Agent 委托的"假输出"问题**
- 安全 Agent：绑定真正的 `dependency_check` / `codebase_search` 工具调用，而不是只写报告
- 法务 Agent：注入真实的法律条款比对表
- 目标：让"做安全审查" = 真正扫描代码，不是"写一段像安全审查的文字"

**B3: Outcome Contract 接入管线**
- 实现 Clarify 闸门 UI：Dashboard 输入需求后，先弹"我们这样理解你的目标"
- Dashboard 的三段流程：草拟合同 → 签字 → 启动
- 管线在 planning 阶段自动创建 outcome_contract

**B4: 升级 self_verify 到实质检查**
- 添加 LLM-based content quality check（用弱模型做快速过滤，不是深度评估）
- 加强占位符检测：检测"将在下个版本实现""待确认"等语义占位符

---

### Phase C — 团队进化（4 周，P2 + 深度改进）

**C1: 学习回路的"影子模式验证"**
- 蒸馏出的 PromptOverride 先走 shadow 模式 3-5 个任务
- 比较 shadow 版与 active 版的批准率
- 只有 shadow 版显著优于 active 版时才自动激活

**C2: 构建跨项目知识沉淀机制**
- 按功能领域（用户认证/支付/数据导出）做跨项目的模式提取
- 新任务匹配到"类似领域"时自动注入过往经验

**C3: 引入独立质检模型**
- Quality Gate 的 LLM 评估换成独立的、更高成本的模型（如 claude-opus）
- 或引入多模型投票（2 个不同模型同时评估，不一致时标记人工审查）

**C4: 前端设计系统接入 Pencil**
- Agent-designer 产出设计 Token → Pencil `.pen` 文件
- 前端代码从 `.pen` 同步设计变量
- 让客户在 SharePage 看到"这是设计稿"、"这是实现"的可视化对比

**C5: 构建 Agent 能力画像**
- 每个 Agent 的真实通过率、驳回率、平均重试次数 = 动态指标
- 在 Team 页面用真实数据替换硬编码雷达图

---

### 修复时间线

```
本周（Phase A）:
  ┌─ A1: 注入领域知识库          ████████░░░░  / 8
  ├─ A2: 独立评审模板            ████░░░░░░░░░  / 4
  ├─ A3: 独立质检模型            ██████░░░░░░░  / 6
  └─ A4: 补测试                 ████████░░░░░  / 8

第 2-3 周（Phase B）:
  ├─ B1: 并行协作               ████████░░░░░  / 8
  ├─ B2: Agent 委托真输出        ██████░░░░░░░  / 6
  ├─ B3: Outcome Contract       ██████████░░░  / 10
  └─ B4: 升级 self_verify       ████░░░░░░░░░  / 4

第 4-7 周（Phase C）:
  ├─ C1: 影子模式验证            ██████░░░░░░░  / 6
  ├─ C2: 跨项目知识沉淀          ██████████░░░  / 10
  ├─ C3: 独立质检模型            ████░░░░░░░░░  / 4
  ├─ C4: Pencil 设计系统         ██████░░░░░░░  / 6
  └─ C5: Agent 能力画像          ████░░░░░░░░░  / 4
```

---

## 五、核心洞察

当前系统的**骨架是世界一流的**：
- `delivery_contract.py` 的三重硬闸门（真测试 + 真预览 + 真证据）
- Phase 6（QA 真实执行）和 Phase 7（部署上线）
- DAG 编排 + 驳回自愈的循环机制
- 学习回路的信号蒸馏机制

**但骨架里面的"肌肉"（Agent 专业知识）是虚的**。

13 个 Agent 的"30 年经验"目前是**标签**，要变成真正的专业级输出，核心路径是：

1. **Domain Knowledge Injection** — 不依赖 LLM 的常识，给固定的结构化的领域知识
2. **Independent Validation Chain** — 质量门禁和评审使用独立/更强的模型或规则引擎
3. **Cross-Modal Strength** — 让安全/法务/设计等 Agent 真正调用工具做事，不只写报告
4. **Organizational Learning** — 跨项目的知识沉淀，让团队越用越强
