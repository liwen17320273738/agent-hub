---
# Agent Hub 核心问题诊断与架构重构路线图

## 🧠 核心诊断：Agent Hub 的本质问题
**一句话总结：**
当前的系统本质上是一个**“带有角色提示词的 LLM 聊天壳”**。Agent 缺乏独立的身份标识、可见的能力边界、工具执行能力以及真正的协作机制。用户无法区分不同 Agent 的专业差异，更无法感受到其“资深专家”的专业水平。

---

## ⚠️ 核心问题深度分析

### 1. 三套互不相通的“Agent”定义（架构脑裂）
系统中存在三套完全独立的 Agent 概念，彼此之间没有任何关联：

| 维度 | 来源 | 实际用途 | 致命问题 |
| :--- | :--- | :--- | :--- |
| **前端 (UI)** | `src/agents/registry.ts` (静态数组) | Dashboard 展示 + 基础聊天 | 硬编码在前端，不读取后端 API 数据。 |
| **后端 (DB)** | `AgentDefinition` 表 + `seed.py` | 数据库持久化存储 | 仅存在于数据库，前端和 Pipeline 均未真正调用。 |
| **Pipeline** | `STAGE_ROLE_PROMPTS` (硬编码) | 流水线阶段执行 | 逻辑完全脱离 DB Agent，也不读取前端 Agent。 |

**后果：** 你在前端看到的 `Agent-product-manager` 与 Pipeline 中执行的 `product-manager` 角色是两个完全无关的实体。

### 2. Agent 缺乏真正的“能力” (Capability Gap)
目前的 Agent 仅仅是一段 `systemPrompt` 文本，缺乏以下核心要素：
* **工具使用 (Tool Use) 缺失：** `AgentRuntime`（带工具循环的运行时）虽然已实现，但从未被任何地方调用。Pipeline 阶段只是单次的 LLM 调用，不具备工具执行能力。
* **技能绑定 (Skill Binding) 缺失：** `AgentSkill` 关联表存在，但缺乏关联数据，Pipeline 执行时无法按需加载技能。
* **能力展示 (Visibility) 缺失：** `capabilities` JSON 字段存在于 DB 中，但前端完全不渲染。
* **独立记忆 (Memory) 缺失：** 每个 Agent 缺乏私有的知识库，全局 `Memory` 系统仅能实现简单的关键字搜索。

### 🛡️ 3. Pipeline 是“Prompt 接力”，而非“多 Agent 协作”
当前的 Pipeline 执行本质上是同一个 LLM 在不同阶段更换 `system_prompt` 的“自说自话”过程，缺乏协作灵魂：
* **缺乏审阅/反馈：** 没有 Agent 间的相互审计、质疑或反馈机制。
* **缺乏工具调用：** Agent 不能真正地写代码、跑测试、做设计。
* **缺乏质量门禁：** `Self-verify` 仅做字符串规则检查，而非逻辑验证。
* **缺乏条件分支：** `skip_condition` 虽然定义了，但从未被执行。

### 🧩 4. 技能系统（Skill System）链路断裂
* **同步失败：** `SKILL.md` 的变更不会自动同步到数据库。
* **ID 冲突：** 存在 `prd-writing` 与 `prd-expert` 这种 ID 不一致的情况。
* **分类错位：** `seed.py` 中的 `category`（如 `operations`）与 `STAGE_SKILL_MAP` 期望的类别（如 `deployment`）完全对不上。
* **后果：** Pipeline 在执行阶段时，由于类别无法匹配，实际上注入了 0 个技能。

### 🎨 5. 前端 Agent 身份感丧失
`AgentCard.vue` 仅显示头像和名称，缺乏以下专家属性：
* **专业领域标签、能力雷达图、可用工具列表、历史产出、协作关系图。**
* **用户感受：** 所有的 Agent 看起来都只是“一个聊天框 + 一个不同的名字”。

---

## 🛠️ 解决方案：让 Agent 成为真正的“资深专家”

### 🏗️ 架构重设计：统一 Agent 模型
我们需要构建一个统一的 `AgentDefinition` 模型，使其具备以下维度：
* **Identity (身份)**: Name, Title, Persona, Avatar.
* **Expertise (专业)**: Domain, Seniority, Boundary, Standards.
* **Tools (工具)**: `git_*`, `test_*`, `file_*`, `bash`, `search`.
* **Skills (技能)**: `prd`, `code_rev`, `arch`, `test`, `deploy`.
* **Collaboration (协作)**: `can_delegate_to`, `can_review`, `escalation_path`.

### 🚀 实施路线图 (Roadmap)

#### 📍 Phase 1: 基础重构 (建立根基)
* **统一身份源**：前端删除静态列表，改为从 `/api/agents` 动态加载。
* **接入运行时**：在 Chat 和 Pipeline 路径中启用 `AgentRuntime`，让 Agent 真正能使用 `tools`。
* **修复技能链**：实现 `discover_skills()` 自动同步，并修复 `category` 匹配逻辑。

#### 📍 Phase_2: 可视化增强 (展示身份)
* **Agent Profile 页面**：展示能力雷达图、技能列表、工具列表、协作关系图。
* **产出标准展示**：展示该 Agent 的 `deliverables` 和 `quality_gate`。

#### 📍 Phase_3: 协作机制实现 (真正协作)
* **引入审阅逻辑**：实现 `REJECT` 后的回退机制，支持下游 Agent 对上游输出的审计。
* **引入人类审批**：在关键阶段（如 Deployment）强制引入 `human_in_the_loop`。

#### 📍 Phase_4: 产业化交付 (端到端 SDLC)
* **标准化模板**：提供基于特定角色的 SDLC 完整模板（从 PRD $\rightarrow$ Arch $\rightarrow$ Code $\rightarrow$ Test $\rightarrow$ Deploy）。

---

**结论：**
Agent Hub 的核心矛盾在于**“强大的后端能力”与“简陋的 Agent 身份定义”之间的脱节**。
**建议从 Phase 1 开始实施**：优先统一 Agent 身份源并为 Pipeline 注入工具执行能力，这是让 Agent 从“聊天机器人”蜕变为“自动化工程师”的唯一路径。 🌫️


核心诊断：Agent Hub 的根本问题
一句话总结
当前系统不是一个 AI Agent 平台，而是一个"带角色提示词的 LLM 聊天壳"。 Agent 没有独立身份、没有可见能力、没有工具使用、没有协作机制——用户无法区分一个 Agent 和另一个 Agent 的区别，更看不出任何"30年资深专家"的水平。

问题一：三套互不相通的"Agent"定义（脑裂）
系统中存在 三套 完全独立的 Agent 概念，互不关联：

层级	Agent 来源	实际用途	问题
前端
src/agents/registry.ts 静态数组 (14 个)
Dashboard 展示 + 聊天
硬编码在前端，不读后端 API
后端 DB
AgentDefinition 表 + seed.py 种子数据
仅存在于数据库，没有任何地方真正使用
/agents API 存在但前端不调用
Pipeline
STAGE_ROLE_PROMPTS + AGENT_PROFILES 硬编码
Pipeline 阶段执行
不读 DB Agent，不读前端 Agent
后果： 你在前端看到的 Agent-product-manager 和 Pipeline 里执行的 product-manager 角色是两个完全无关的东西。前端聊天用前端 systemPrompt，Pipeline 用另一套硬编码 prompt，数据库里的 Agent 定义谁都不用。

问题二：Agent 没有真正的"能力"
当前 Agent 的全部"能力"就是一段 systemPrompt 文字。没有：

工具使用：AgentRuntime（带工具循环的运行时）写好了但 从未被任何地方调用。Pipeline 阶段只是单次 LLM 调用，不使用任何工具
技能绑定：AgentSkill 关联表存在但 从未创建关联数据，Pipeline 执行时也不读 Agent 绑定的技能
能力展示：capabilities JSON 字段存在于 DB 模型但 前端从不渲染
独立记忆：每个 Agent 没有自己的知识库/经验库，Memory 系统是全局的且仅做关键字搜索
问题三：Pipeline 是"串行 prompt 接力"，不是多 Agent 协作
Pipeline 的真实执行流程：

stage_1: 发一条消息给 LLM（用 CEO 角色 prompt）→ 拿到文本输出
stage_2: 把 stage_1 的输出塞进 context，再发给 LLM（用 Architect 角色 prompt）→ 拿到文本输出
stage_3: ... 同上
这不是多 Agent 协作，而是 同一个 LLM 换了不同 system prompt 在自说自话。没有：

Agent 间的审阅/反馈/质疑
工具调用（不能真正写代码、跑测试、做设计）
质量门禁（Self-verify 只检查字符串长度）
条件分支（skip_condition 定义了但从未执行）
问题四：技能系统断裂
技能来源	数量	与 Pipeline 的关系
skills/public/ SKILL.md
6 个
不自动同步到数据库，Pipeline 查不到
MARKETPLACE_REGISTRY
6 个
ID 和文件系统的不一致（prd-writing vs prd-expert）
seed.py DEFAULT_SKILLS
6 个
写入 DB，但 category 与 STAGE_SKILL_MAP 对不上
Pipeline 按 category 从 DB 查技能，但种子数据的 category（如 operations）和 STAGE_SKILL_MAP 期望的 category（如 deployment, devops）根本匹配不上。结果：大多数阶段实际上注入了 0 个技能。

问题五：前端看不出 Agent 的独立专家身份
AgentCard.vue 只显示：图标 + 名称 + title 标签 + 2 行描述 + 对话数量。没有：

专业领域标签
能力雷达图 / 技能列表
可使用的工具列表
历史产出 / 成功案例
与其他 Agent 的协作关系
工作边界（擅长什么 / 不擅长什么）
用户感受： 所有 Agent 看起来都是 "一个聊天框 + 不同名字"。

解决方案：让每个 Agent 成为可见的资深专家
架构重设计：统一 Agent 模型
┌─────────────────────────────────────────────────────────┐
│                    AgentDefinition (DB)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Identity  │ │Expertise │ │  Tools   │ │  Skills  │   │
│  │─────────  │ │─────────-│ │─────────-│ │──────────│   │
│  │ name      │ │ domain   │ │ git_*    │ │ prd      │   │
│  │ title     │ │ seniority│ │ test_*   │ │ code_rev │   │
│  │ persona   │ │ boundary │ │ file_*   │ │ arch     │   │
│  │ avatar    │ │ standards│ │ bash     │ │ test     │   │
│  └──────────┘ │ cases    │ │ search   │ │ deploy   │   │
│               └──────────┘ └──────────┘ └──────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────────┐ │
│  │  Memory  │ │ Metrics  │ │ Collaboration Protocol   │ │
│  │──────────│ │──────────│ │──────────────────────────│ │
│  │ personal │ │ tasks_ok │ │ can_delegate_to: [...]   │ │
│  │ patterns │ │ avg_qual │ │ can_review: [...]        │ │
│  │ knowledge│ │ response │ │ escalation_path: [...]   │ │
│  └──────────┘ └──────────┘ └──────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
     Chat Runtime   Pipeline     Frontend
     (AgentRuntime   Stage        Agent Profile
      + tools)       Execution    + Capability UI
需要实现的 7 个关键改造
1. 统一 Agent 身份源 — 消除三套系统

前端删除 registry.ts 静态列表，改为从 /api/agents 动态加载
Pipeline execute_stage 改为按 pipeline_role 查询 AgentDefinition，使用其 system_prompt + 关联技能 + 关联工具
一个 Agent 定义，三处统一消费
2. 接入 AgentRuntime — 让 Agent 能用工具

当前 AgentRuntime（ReAct 工具循环）已实现但从未被调用。需要：

Chat 路径：聊天时根据 Agent 配置的 tools 列表启用工具循环
Pipeline 路径：每个阶段启用该角色 Agent 绑定的工具（如 developer 可用 git/file/bash/test，QA 可用 test_execute/test_detect）
这样 Agent 就不再只是"输出文本"，而是能做事
3. 专家级 Agent Profile 设计

每个 Agent 需要一个完整的专家档案：

# 示例：产品需求专家
id: product-expert
name: 产品需求专家
title: 首席产品架构师
seniority: "30年产品设计经验"
domain:
  primary: ["产品需求分析", "用户研究", "商业模式"]
  secondary: ["竞品分析", "数据驱动决策"]
boundary:
  handles: ["PRD 编写", "用户故事", "验收标准", "需求优先级", "MVP 定义"]
  delegates_to:
    architecture: "架构设计交给架构专家"
    ui_design: "UI 设计交给设计专家"
standards:
  - "每个需求必须有明确的验收标准"
  - "需求文档遵循 IEEE 830 标准"
  - "用户故事使用 INVEST 原则"
deliverables:
  - type: "PRD"
    format: "结构化文档"
    quality_gate: "需包含: 背景、目标、范围、用户故事、NFR、里程碑"
tools: ["web_search", "file_read", "file_write"]
skills: ["prd-expert", "deep-research", "data-analysis"]
collaboration:
  reviews_output_of: []
  output_reviewed_by: ["architect-expert", "ceo-expert"]
  can_escalate_to: ["ceo-expert"]
4. 技能系统修复 — 打通断裂的链条

启动时 discover_skills() 自动同步 SKILL.md 到数据库（而不仅仅是加载到内存）
统一 ID（prd-expert = prd-writing，不要两套）
修复 STAGE_SKILL_MAP 与种子数据的 category 对齐
启用 AgentSkill 关联：每个 Agent 绑定具体技能，Pipeline 执行时读取
5. 前端 Agent Profile 页 — 展示专家身份

新增 Agent 详情页 /agent/:id/profile，展示：

专家头像 + 名称 + 资历描述
能力雷达图（分析、设计、编码、测试、运维 等维度）
绑定的技能列表（带描述和使用统计）
可使用的工具列表（带图标）
协作关系图（与哪些 Agent 有上下游关系）
产出标准（该 Agent 的交付物是什么、质量门禁是什么）
历史绩效（完成任务数、平均质量评分）
6. 真正的多 Agent 协作 — 不是接力而是协作

改造 Pipeline 为真正的协作模式：

每个阶段输出后，下游 Agent 先审阅再开始工作
审阅不通过可以回退到上一阶段要求修改
Agent 间可以提问和澄清
关键节点需要人类审批才能继续
7. SDLC 全流程 Agent 团队

角色	专家名称	核心交付物	关键工具
CEO/PM
产品需求专家
PRD、需求规格、优先级矩阵
web_search, file_write
Architect
架构设计专家
架构方案、技术选型、数据模型
web_search, file_write
UI Designer
UI 设计专家
设计规范、页面原型、组件定义
web_search, file_write, image_gen
Developer
开发实现专家
可运行代码、Git PR
git_, file_, bash, test_*
QA
测试质量专家
测试策略、用例、测试报告
test_execute, test_detect, bash
DevOps
运维部署专家
部署方案、CI/CD 配置、监控
bash, file_, deploy_
Reviewer
验收评审专家
评审报告、验收确认
file_read, web_search
实施优先级
阶段	内容	预期效果
Phase 1 (基础)
统一 Agent 数据源；接入 AgentRuntime；修复技能链
Agent 从"聊天壳"变成"能用工具的专家"
Phase 2 (可见性)
Agent Profile 页面；能力展示；技能绑定 UI
用户能看到每个 Agent 的独立身份和能力
Phase 3 (协作)
Pipeline 审阅机制；条件分支；人类审批
从"接力"变成真正的团队协作
Phase 4 (产品化)
SDLC 全流程模板；质量门禁；产出标准化
能端到端交付一个完整项目
你想从哪个阶段开始实施？我建议从 Phase 1（统一 Agent 身份 + 接入工具运行时） 开始，因为这是让 Agent 从"假专家"变成"真专家"的根基。

分析已经完成。总结一下核心发现：

三套 Agent 定义互不相通 — 前端静态列表、数据库定义、Pipeline 硬编码各自为政
AgentRuntime（工具循环）写好了但从未调用 — Agent 只能输出文本，不能真正执行任何操作
技能系统链条断裂 — SKILL.md 不同步到数据库，category 对不上，Pipeline 阶段实际注入 0 个技能
Pipeline 是 prompt 接力赛 — 不是多 Agent 协作，只是同一个 LLM 换不同 system prompt
前端完全看不出 Agent 能力 — 所有 Agent 都是"一个聊天框 + 不同名字"
要让每个 AI Agent 展现出 30 年资深专家水平，需要按 4 个阶段推进：

Phase 1：统一 Agent 数据源 + 接入工具运行时（让 Agent 能做事）
Phase 2：Agent Profile 页面 + 能力展示（让用户看到专家身份）
Phase 3：Pipeline 审阅/回退/人类审批（真正的团队协作）
Phase 4：SDLC 全流程模板 + 质量门禁（端到端交付完整项目）
你想从哪个阶段开始？还是需要我对某个具体问题做更深入的分析？






Phase 2：Agent Profile 页面 + 能力展示（让用户看到专家身份）
Phase 3：Pipeline 审阅/回退/人类审批（真正的团队协作）
Phase 4：SDLC 全流程模板 + 质量门禁（端到端交付完整项目）