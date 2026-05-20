# AI 军团稳定交付闭环问题暴露与分阶段执行计划

日期：2026-05-13

## 目标定义

目标不是再做一个“有很多 Agent 名字和流程节点的 Demo”，而是让用户提交一句话后，系统能稳定交付：

- PRD
- UI 设计图
- 架构图
- 可运行代码
- 测试报告
- 部署链接
- 分享与验收材料

这条链路必须能被真实执行、真实验证、真实恢复。只要其中任一环节只能生成说明文档、依赖人工猜测、失败后静默跳过，就还不能称为稳定的 AI-agent 军团交付平台。

## 当前判断

项目当前处在“AI 交付平台原型”阶段，而不是“商业级 AI 交付操作系统”阶段。

现有系统已经具备不少模块名义能力：Pipeline、Workflow Builder、Agent 角色、LLM Router、Artifact、Share、Upload、Memory、Quality Gate、Scheduler、Observability、CodeGen、UI Visualizer、Deployment 等。但这些模块还没有收敛成一条高成功率的主路径。

最大问题不是缺少模块，而是核心闭环没有被产品化验证。

## 当前项目全量审计结论：优点、鸡肋、硬伤

这次判断不是基于印象，而是按当前项目的核心链路审计：Agent 定义、工具权限、技能市场、AgentRuntime、Agent bus、Pipeline/DAG、Workflow Runner、Artifact、Memory、Learning、Eval、前端 Team/Workflow/Task 视图。

结论是：

> 项目有很多正确的底层零件，但还不是一个真正的 AI-agent 军团。它更像一个把 Agent 平台、Pipeline、Workflow、Skill、Memory、Artifact 都尝试接上的“综合原型”。优点是底子不差；硬伤是组织系统没形成；鸡肋是大量功能有入口、有文案、有表结构，但没有进入主交付闭环。

### 当前真正的优点

#### 1. Agent 画像不是完全空壳

`backend/app/agents/seed.py` 已经定义了较完整的 Agent 体系：

- CEO / 总控
- CTO / 架构师
- Product
- Developer
- QA
- Designer
- DevOps
- Security
- Acceptance
- Data
- Marketing
- Finance
- Legal
- Hermes Overseer

每个 Agent 有：

- `capabilities`
- `seniority`
- `radar`
- `boundary`
- `deliverables`
- `standards`
- `collaboration`
- `role_card`
- `handoff_protocol`
- `preferred_model`
- `quick_prompts`

这说明项目并不是随便写几个角色名，而是认真参考过真实 agent 官网和团队角色设计。

优点：角色设定有商业叙事基础，可以包装成“一个人技术有限公司”的组织图。

问题：这些画像大多还只是 metadata，没有被强制转换成运行时任务协议。

#### 2. 工具权限体系有雏形

项目不是所有 Agent 都能乱调用工具。`backend/app/services/tools/registry.py` 有 `ROLE_TOOL_WHITELIST`：

- CEO 偏只读。
- CTO 可读代码、查 git、做架构搜索。
- Designer 可写设计文件、截图、生成图片。
- Developer 可读写文件、bash、git、build、test。
- QA 可跑测试、浏览器验证，但不能随便改代码。
- DevOps 可部署、push、PR。
- Security 偏只读审计。

这是很好的基础。真正的军团必须有权限边界，否则 Agent 会互相踩踏。

优点：已经有“最小权限”的意识。

问题：权限只是工具调用层的保护，还没有和阶段产物、责任归属、失败恢复绑定。

#### 3. Agent 之间确实有通信机制

当前项目有两套 Agent 互动方式：

- 同步委派：`delegate_to_agent`
- 异步消息：`agent_publish` / `agent_wait_for` / `agent_bus`

`agent_bus` 还支持 Redis pub/sub 和数据库持久化，理论上可以做跨 Agent 协作。

优点：不是完全没有协作基础，已经有消息通道。

问题：Pipeline 主路径没有真正依赖 Agent bus 来完成任务协作。大多数协作还是 prompt 里“建议你委派”，而不是 Orchestrator 强制调度。

#### 4. Pipeline/DAG 模板覆盖面很广

`dag_orchestrator.py` 里有大量模板：

- full
- web_app
- api_service
- data_pipeline
- bug_fix
- microservice
- fullstack_saas
- mobile_app
- enterprise
- growth_product
- fintech
- spec_driven
- e2e_intake

这说明项目有野心：不只是线性流程，而是想让不同业务类型走不同 Agent 阵容。

优点：模板体系适合未来成为“AI 公司部门编排”。

问题：模板太早铺开，导致主路径没有先稳定。现在看起来像很多作战计划，但缺少一支真正打赢过仗的小队。

#### 5. Artifact v2 是正确方向

`TaskArtifact`、Artifact Type Registry、版本、`is_latest`、manifest sync 都是对的。

这对于“交付平台”很重要，因为用户最终买的是交付物，而不是聊天过程。

优点：

- 已经意识到 DB 是 artifact source of truth。
- 支持版本。
- 支持 brief、prd、ui_spec、architecture、implementation、test_report、acceptance、ops_runbook、code_link、screenshot、attachment、deploy_manifest 等类型。

问题：

- Artifact 还主要是存结果，不是阶段通过的强 contract。
- 缺 artifact 时很多流程仍可能继续。
- Evidence，比如真实 build log、screenshot、preview URL，还没有成为硬门禁。

#### 6. Memory / Learning / Eval 不是没有

项目里有：

- Long-term memory
- Working memory
- Learned patterns
- Prompt override
- Learning signal
- Eval dataset/run/result
- Prompt optimizer

这说明“自主提升”的种子已经有了。

优点：未来可以做“越跑越强”的闭环。

问题：当前学习更多是 prompt 补丁层，还没有连接到完整交付成功率。自主提升不能只优化 prompt，还要优化模板、工具、测试、失败恢复策略。

#### 7. 前端已经有平台感

前端有：

- Dashboard / Pipeline board
- Inbox
- Team
- Workflow
- Workflow Builder
- Pipeline Task Detail
- Artifact tabs
- Share page
- Agents Console

优点：已经能展示“平台”而不是普通聊天工具。

问题：平台感强，但“军团正在打仗”的真实感弱。Team 页面展示协作关系，但用户看不到每个 Agent 的真实贡献、证据、争论、返工、接力。

### 当前最鸡肋的部分

这里的“鸡肋”不是说没价值，而是当前阶段投入产出低，容易拖慢主线。

#### 鸡肋 1：过多 Agent 角色

Data、Marketing、Finance、Legal 等角色设定很好，但在“一句话生成可运行产品”的 MVP 中不是刚需。

问题：

- 角色越多，协作复杂度越高。
- 没有强 Orchestrator 时，多角色只会增加 prompt 噪声。
- 用户现在最痛的是主流程跑不通，不是缺 Finance Agent。

处理建议：

- 第一阶段只保留 7 个核心 Agent：Product、Designer、Architect、Developer、QA、DevOps、Acceptance。
- 其他 Agent 作为“专家顾问池”，只有特定模板触发。

#### 鸡肋 2：Workflow Builder 早于稳定主流程

Workflow Builder 看起来高级，但当前 saved workflow runner 还不能真正执行 tool、knowledge、loop。

问题：

- 用户以为可以编排复杂 AI 工作流。
- 实际执行能力不足，会造成信任损失。
- 它和 Pipeline/DAG 主线有割裂。

处理建议：

- 暂时把 Builder 降级为“高级实验功能”。
- 主产品只推固定 Delivery Workflow。
- 等 Orchestrator Kernel 稳定后，再让 Builder 编辑同一套 Kernel 的阶段。

#### 鸡肋 3：Skill Marketplace 当前更像 prompt 模板市场

`skill_marketplace.py` 里的技能大多是 prompt template + input schema + LLM call。

问题：

- 技能不是强执行单元。
- 不能保证产物可验证。
- 和 Agent 阶段 contract 没绑定。

处理建议：

- 保留技能市场，但不要作为主线卖点。
- 先把核心技能变成阶段校验器和工具能力，例如 build、test、screenshot、deploy、schema validate。

#### 鸡肋 4：过早扩展多模板

fullstack_saas、mobile_app、fintech、enterprise 等模板都很好，但现在会稀释工程资源。

问题：

- 每个模板都需要独立 artifact contract、工具链、测试策略、部署策略。
- 没有黄金模板成功率时，多模板只会制造更多失败入口。

处理建议：

- 先只保留 `web_app` 黄金路径。
- 其他模板放入路线图，不作为当前验收目标。

#### 鸡肋 5：前端展示的协作关系是静态推演

Team 页面里协作关系多来自前端 hardcoded reviewMap / escalationMap，而不是实际任务消息或真实交接记录。

问题：

- 看起来有组织关系，但不是实时作战图。
- 用户看不到谁给谁发了任务、谁拒绝了谁、谁修复了谁的问题。

处理建议：

- Team 页面应从 Agent bus、stage events、artifact authorship 生成动态作战图。

### 当前最硬的硬伤

#### 硬伤 1：没有唯一 Orchestrator Kernel

当前存在多条执行入口：

- `pipeline_engine`
- `dag_orchestrator`
- `workflow_runner`
- `lead_agent`
- `agent_runtime`
- `executor_bridge`

每个都能执行一部分，但没有一个唯一总控。

后果：

- 状态散。
- 失败语义散。
- 重试策略散。
- Artifact 写入散。
- 用户不知道到底哪条流程在跑。

真正的军团必须有一个“总司令部”。其他模块只能是 worker 或工具。

#### 硬伤 2：Agent 协作不是强制协议

虽然有 `handoff_protocol`、`collaboration`、`delegate_to_agent`、`agent_bus`，但它们没有成为阶段推进的硬规则。

例如：

- Designer 的输出没有强制被 Developer 以结构化方式消费。
- QA 的失败没有强制生成 Developer 修复任务。
- Acceptance 的 reject 没有形成完整返工链路。
- CTO / Security / Legal 的 review 不一定基于真实 evidence。

真正的协作应该是：

```text
Agent A 产出 artifact -> Kernel 校验 -> Agent B 读取 artifact -> Agent B 产出 evidence -> Reviewer 判定 -> Kernel 决策
```

而不是：

```text
Agent A 写 Markdown -> Agent B 读 prompt 拼接文本 -> LLM 再写 Markdown
```

#### 硬伤 3：30+ 年经验没有转化成能力差异

当前“30 年经验”主要体现在 persona 文案上。

真正应该体现为：

- 不同 Agent 有不同判断框架。
- 不同 Agent 有不同工具链。
- 不同 Agent 有不同验收标准。
- 不同 Agent 有不同失败处理策略。
- 不同 Agent 有不同记忆和案例库。
- 不同 Agent 会坚持自己的专业底线。

例如：

- CTO 不应该只是写架构说明，而应该拒绝模糊 API、要求 file plan。
- Designer 不应该只是写色板，而应该产出图、组件状态、响应式规则。
- QA 不应该只是写测试计划，而应该运行浏览器、抓截图、打回开发。
- DevOps 不应该只是写 runbook，而应该拿到 URL、做 health check。
- Acceptance 不应该只是总结，而应该逐条验收。

#### 硬伤 4：没有证据驱动的作战链

当前系统最缺的是 evidence-first。

军团能打硬仗，靠的不是每个人都“说得专业”，而是每个人都带证据交接：

- Product 交验收标准。
- Designer 交设计图。
- Architect 交架构图和契约。
- Developer 交代码和构建结果。
- QA 交测试日志和截图。
- DevOps 交 URL 和健康检查。
- Acceptance 交逐项验收结果。

当前很多阶段还停留在文本产物，因此看不出“能打硬仗”。

#### 硬伤 5：自主提升没有闭合到生产成功率

Learning loop 和 eval 是优点，但当前自主提升主要围绕 prompt override 和 eval case。

真正的自主提升应该包括：

- 哪类需求失败最多？
- 哪个 Agent 失败率最高？
- 哪个模板构建失败最多？
- 哪个模型在设计阶段最差？
- 哪个 artifact 最常缺失？
- 哪条修复策略最有效？
- 是否应该更新模板、工具、规则，而不只是改 prompt？

如果学习只改 prompt，系统会越来越会说，但不一定越来越会交付。

### 当前项目可以保留和强化的资产

#### 必须保留

- Agent DB 模型。
- Agent seed profile。
- ROLE_TOOL_WHITELIST。
- AgentRuntime。
- Agent bus。
- LLM Router。
- TaskArtifact v2。
- DAG template 概念。
- Memory / Learning / Eval。
- SSE / Observability。
- Pipeline Task Detail / Artifact tabs。

#### 应该收敛

- Pipeline Engine、DAG Orchestrator、Workflow Runner 要收敛到一个 Kernel。
- Skill Marketplace 要从 prompt 技能收敛到执行技能 + 验证技能。
- Workflow Builder 要暂时服从 Delivery Workflow，不要独立成另一套执行语义。
- 多 Agent 要先收敛成 7 个核心岗位。

#### 应该暂缓

- 更多模板。
- 更多市场功能。
- 更多外部平台。
- Finance / Legal / Marketing 的默认介入。
- 任意复杂可视化 workflow。

### 对“一个人技术有限公司”的重新定义

当前项目想打造的不是普通 Agent 平台，而是：

> 一个人提出目标，AI 公司自动完成产品经理、设计、架构、开发、测试、部署、验收的协作。

这个定位是好的，但必须从“角色展示”升级为“组织作战”。

一个人技术有限公司里的每个 Agent 应该像公司岗位：

| 岗位 | 当前表现 | 应有表现 |
|---|---|---|
| CEO | 文案设定强，实际控制弱 | 拥有最终决策权、范围控制、资源调度 |
| Product | 能写 PRD | 输出结构化需求和验收标准 |
| Designer | 能写 UI spec，可生成图片但不稳 | 必须交 UI 图、设计 token、页面状态 |
| Architect | 能写架构文档 | 必须交架构图、API/data/file contract |
| Developer | 有工具和 CodeGen | 必须交真实代码、构建结果 |
| QA | 有测试和浏览器工具 | 必须真实跑测试、截图、打回 |
| DevOps | 有 bash/build/git | 必须交 preview URL 和 health check |
| Acceptance | 能总结验收 | 必须逐项验收，失败退回指定阶段 |
| Security | 有审计能力 | 高风险模板强制介入 |
| Data/Finance/Legal/Marketing | 画像完整但默认价值低 | 作为特定场景专家按需介入 |

### 最终审计结论

当前项目不是没认真做。相反，它做了很多正确零件。

但真正的问题是：

> 它把“AI 公司”的组织图画出来了，却还没有把“AI 公司如何接活、分工、交接、检查、返工、交付、复盘”做成硬系统。

所以用户现在看不到 30+ 年经验，因为经验只在 persona 里，没有变成：

- 决策规则。
- 专业底线。
- 强制产物。
- 验收标准。
- 工具动作。
- 失败处理。
- 复盘学习。

如果继续堆角色、堆页面、堆模型，项目会更像大而全 Demo。  
如果收敛成 Orchestrator Kernel + 7 核心 Agent + Artifact Contract + Evidence Gate + Sandbox Runtime，它才会开始像一个能独立作战的 AI 技术公司。

## 7 个核心 Agent 如何真正体现 30+ 年经验

7 个核心 Agent 不能只是“保留 7 个角色”。每个 Agent 都必须有自己的装备栈：

- 模型：什么时候用强推理，什么时候用低成本，什么时候用代码执行器。
- 工具：它能实际做什么。
- MCP：它连接哪些外部系统。
- Skill：它的方法论和专业套路。
- Rule：它必须遵守的硬规则。
- Hook：它执行前、中、后自动触发什么检查。
- Subagent：它遇到专业分支时召唤谁。
- Artifact Contract：它必须交什么，缺一项不能过。
- Evidence Gate：它用什么证据证明自己完成。

只有这样，“30+ 年经验”才不是 persona 文案，而是可执行能力。

### 三套规则自动串联：OpenSpec + Superpowers + gstack

这三套思想应该成为同一个会话里的默认作业系统。

#### 1. OpenSpec：写代码前把需求锁住

作用：任何实现前必须先把需求、边界、验收标准锁定。

触发阶段：

- Product Agent
- Architect Agent
- Developer Agent 开始前

产物：

- `spec.md`
- `acceptance_criteria.json`
- `non_goals.json`
- `change_plan.md`

硬规则：

- 没有验收标准，不允许进入设计/架构。
- 没有 non-goals，不允许进入开发。
- 需求变更必须生成 spec diff。
- Developer 只能实现 spec 内的内容。

对应 Slash 命令：

```text
/spec       锁定需求、范围、验收标准
/clarify    发现歧义时反问或生成假设
/scope      收缩范围，明确不做什么
```

#### 2. Superpowers：写代码时把质量卡住

作用：开发过程中持续卡质量，不等到最后才发现烂代码。

触发阶段：

- Designer
- Architect
- Developer
- QA

产物：

- `quality_check.json`
- `code_review_findings.md`
- `risk_register.md`

硬规则：

- 每个 Agent 执行前必须加载匹配 skill。
- 每次文件修改后运行轻量校验。
- 代码生成必须遵守模板边界。
- 失败不能用“建议后续优化”掩盖。

对应 Slash 命令：

```text
/skill      查找并加载当前任务需要的技能
/check      执行阶段质量检查
/fix        基于真实错误日志修复
/review     专业角色审查当前产物
```

#### 3. gstack：写完代码后把发布包了

作用：把代码变成可交付包，而不是停留在“写完了”。

触发阶段：

- QA
- DevOps
- Acceptance

产物：

- `build.log`
- `test.log`
- `browser_screenshot.png`
- `deploy_manifest.json`
- `preview_url`
- `release_notes.md`
- `retro.md`

硬规则：

- 没有构建日志，不能说开发完成。
- 没有测试日志，不能说 QA 完成。
- 没有 preview URL，不能说部署完成。
- 没有验收结果，不能说交付完成。

对应 Slash 命令：

```text
/qa         构建、测试、浏览器验证
/ship       打包、预览、部署、健康检查
/accept     按验收标准逐项验收
/retro      复盘失败，沉淀规则和技能
```

### 同一会话如何自动生效

用户不应该手动理解所有 Agent 怎么串。用户只需要输入一个命令或一句话。

例如：

```text
/build 一个 CRM 客户跟进看板，支持新增客户、阶段流转、提醒、统计
```

系统自动展开：

```text
/spec
  -> Product Agent 锁定需求
  -> Acceptance criteria 写入

/design
  -> Designer Agent 产出 UI spec + UI mockup

/arch
  -> Architect Agent 产出架构图 + file plan

/code
  -> Developer Agent 用 Claude Code 写代码
  -> Superpowers 规则持续检查

/qa
  -> QA Agent 构建、测试、浏览器截图

/ship
  -> DevOps Agent 生成 preview URL + health check

/accept
  -> Acceptance Agent 逐项验收

/retro
  -> Learning Loop 记录失败模式，更新规则/技能/模板
```

用户看到的是一个命令；内部是 7 个 Agent 的自动接力。

### 统一 Agent 装备结构

每个 Agent 在 DB 中不应只有 `role_card` 和 `tools`，还应有这些字段或等价配置：

```json
{
  "agent_id": "Agent-developer",
  "primary_model": "claude-code",
  "reasoning_model": "deepseek-v4",
  "fallback_models": ["qwen-plus", "gemini-flash"],
  "mcp_servers": ["github", "filesystem", "browser", "context7"],
  "skills": ["implementation", "debugging", "code-review", "tdd"],
  "rulesets": ["openspec", "superpowers", "repo-standards"],
  "hooks": ["before_write", "after_write", "before_stage_complete"],
  "subagents": ["security-reviewer", "performance-reviewer", "qa-runner"],
  "required_artifacts": ["source_manifest", "build_command", "run_command"],
  "evidence_gates": ["files_exist", "build_passed"]
}
```

这才是“强 Agent”，不是单纯换 system prompt。

## 7 个核心 Agent 能力栈

### 1. Product Agent：需求锁定官

#### 定位

Product Agent 不是“写 PRD 的文案”。它是需求边界和验收标准的守门人。

30+ 年经验体现：

- 能把一句话需求拆成目标、范围、非目标。
- 能拒绝模糊需求直接进入开发。
- 能把“用户想要什么”转成“系统必须满足什么”。
- 能发现范围膨胀和商业价值不清的问题。

#### 推荐模型

- 主模型：Claude Sonnet / GPT-4.1 / DeepSeek V4 reasoning 级别。
- 低成本模型：DeepSeek Chat / Qwen，用于摘要和补全文档。

#### MCP

- `context7`：查框架、产品 API、竞品功能文档。
- `brave-search` / `duckduckgo-search`：竞品调研。
- `filesystem`：读写 spec 文件。
- `github`：读取 issue / PR 背景。

#### Skills

- PRD Writing
- User Story Mapping
- Acceptance Criteria Design
- Competitive Research
- Scope Control

#### Rules

- 必须输出 IN / OUT / FUTURE。
- 每个核心功能必须有验收标准。
- 不允许用“等开发判断”“后续优化”代替决策。
- 没有非目标，不允许进入设计。

#### Hooks

- `before_stage_start`：检查用户输入是否足够形成 spec。
- `before_stage_complete`：校验 PRD JSON schema。
- `on_scope_change`：生成 spec diff。

#### Subagents

- Market Research Subagent：竞品分析。
- Legal Subagent：涉及合规时介入。
- Finance Subagent：涉及定价/成本时介入。

#### 强制产物

- `spec.md`
- `prd.md`
- `acceptance_criteria.json`
- `non_goals.json`
- `risk_assumptions.md`

#### Evidence Gate

- 至少 5 条用户故事。
- 每条用户故事至少 1 条验收标准。
- 明确不做什么。
- 所有关键歧义已澄清或记录假设。

### 2. Designer Agent：体验与视觉交付官

#### 定位

Designer Agent 不是“写色板”。它负责把需求转成用户能看见、开发能实现的界面系统。

30+ 年经验体现：

- 能定义信息架构。
- 能给出页面状态。
- 能给出设计 token。
- 能产出 UI mockup。
- 能考虑响应式、无障碍和空/错/加载态。

#### 推荐模型

- 主模型：Claude Sonnet / GPT-4.1，用于设计推理和文档。
- 视觉模型：OpenAI Images / Gemini Image，用于 UI mockup。
- 多模态模型：Gemini / GPT-4o 级别，用于参考图理解。

#### MCP

- `figma`：读写 Figma / 生成 frame。
- `filesystem`：写 UI spec、HTML prototype。
- `browser` / `puppeteer`：截图和视觉验证。
- `context7`：查询 Element Plus / Tailwind / Vue 组件规范。

#### Skills

- UI Visual Assets
- Design Tokens
- Interaction States
- Accessibility Review
- Responsive Layout

#### Rules

- 不能只给文字说明，必须交可预览视觉 artifact。
- 每个关键页面必须有 loading / empty / error / success / disabled 状态。
- 所有颜色、字号、间距必须 token 化。
- 如果视觉模型或 Figma 不可用，必须阻断并声明缺资源，不能假完成。

#### Hooks

- `before_design`：读取 PRD 和目标用户。
- `after_design`：检查是否有 `ui_mockup.png` 或 `ui_mockup.html`。
- `visual_check`：截图/预览是否可打开。

#### Subagents

- Accessibility Subagent：无障碍检查。
- Brand Subagent：品牌一致性。
- Frontend Feasibility Subagent：确认设计可实现。

#### 强制产物

- `ui_spec.md`
- `design_tokens.json`
- `screen_plan.json`
- `component_states.json`
- `ui_mockup.png`
- `ui_mockup.html`

#### Evidence Gate

- UI 图文件存在且可读取。
- 至少覆盖 2 个核心页面。
- 设计 token 可被前端消费。
- 状态覆盖完整。

### 3. Architect Agent：系统设计与契约官

#### 定位

Architect Agent 不是“写架构文档”。它负责把需求和设计变成可执行技术契约。

30+ 年经验体现：

- 能定义模块边界。
- 能识别性能、安全、扩展风险。
- 能给出 API/data/file contract。
- 能拒绝模糊方案进入开发。

#### 推荐模型

- 主模型：Claude Opus / Sonnet / GPT-4.1 / DeepSeek V4 reasoning。
- 辅助模型：DeepSeek / Qwen，用于生成表格和文档。

#### MCP

- `context7`：框架最佳实践。
- `github`：查目标仓库结构和 issue。
- `filesystem`：读写架构文件。
- `deepwiki`：理解大型开源架构。

#### Skills

- Architecture Design
- API Design
- Data Modeling
- Threat Modeling
- ADR Writing

#### Rules

- 没有 file plan，不能进入开发。
- 没有 API/data contract，不能进入开发。
- 架构图必须可渲染。
- 必须写风险和降级方案。

#### Hooks

- `before_architecture`：检查 PRD 和设计是否完整。
- `contract_validate`：校验 API/data/file plan schema。
- `diagram_render_check`：Mermaid 是否可渲染。

#### Subagents

- Security Architect Subagent。
- Database Reviewer。
- Performance Oracle。

#### 强制产物

- `architecture.md`
- `architecture.mmd`
- `architecture.html`
- `api_contract.json`
- `data_model.json`
- `file_plan.json`
- `adr.md`

#### Evidence Gate

- Mermaid 渲染成功。
- API contract schema 合法。
- file plan 覆盖开发阶段目标文件。
- 风险清单非空。

### 4. Developer Agent：代码实现官

#### 定位

Developer Agent 是真实工程师，不是“代码说明生成器”。它必须用工具写文件、运行命令、修复错误。

30+ 年经验体现：

- 先读 spec，不乱发挥。
- 基于模板开发，不破坏结构。
- 用 Claude Code / coding agent 写真实文件。
- 用 DeepSeek V4 / 强推理模型做错误诊断和重构建议。
- 遇到安全、性能、架构问题会主动召唤专家。

#### 推荐模型

- 代码执行器：Claude Code / Cursor Agent / Codex 类工具，负责真实改文件。
- 推理模型：DeepSeek V4 / Claude Sonnet，用于分析错误、规划修改。
- 快速模型：Qwen / DeepSeek Chat，用于小修和总结。

#### MCP

- `filesystem`：读写文件。
- `github`：分支、PR、issue、代码上下文。
- `context7`：查 Vue/Vite/Element Plus/测试框架文档。
- `puppeteer` / `browser`：本地页面验证。
- `commands`：受控命令执行。

#### Skills

- TDD Workflow
- Code Review
- Debugging
- Refactor Cleaner
- TypeScript / Python Patterns
- Build Error Resolver

#### Rules

- 写代码前必须读取 `spec.md`、`file_plan.json`。
- 不允许实现 spec 外功能。
- 不允许只输出 Markdown 代码说明。
- 所有文件写入必须在任务 worktree。
- 每次生成后必须运行 build。
- 失败日志必须进入下一轮修复 prompt。

#### Hooks

- `before_code`：OpenSpec lock，确认 spec 已冻结。
- `before_write`：检查路径是否在 worktree。
- `after_write`：运行 formatter / typecheck。
- `on_build_fail`：自动生成修复任务。
- `before_complete`：确认 source manifest。

#### Subagents

- TypeScript Reviewer。
- Security Reviewer。
- Performance Reviewer。
- Build Error Resolver。
- QA Runner。

#### 强制产物

- 源码文件。
- `source_manifest.json`
- `implementation.md`
- `build_command`
- `run_command`
- `build.log`

#### Evidence Gate

- 源码文件真实存在。
- package.json 存在。
- build 命令存在。
- build 至少执行一次。
- build 失败时必须有修复记录或阻断。

### 5. QA Agent：真实验证官

#### 定位

QA Agent 不是“写测试计划”。它必须像资深测试负责人一样，真实运行产品、找问题、打回。

30+ 年经验体现：

- 不相信开发自述，只相信证据。
- 会跑 build/test/browser。
- 会区分 P0/P1/P2。
- 会给出复现步骤。
- 会明确退回哪个阶段。

#### 推荐模型

- 主模型：Claude Sonnet / DeepSeek V4，用于分析日志和测试策略。
- 执行优先：本地命令和 Playwright，不靠 LLM 判断页面是否能打开。

#### MCP

- `browser` / `puppeteer`：真实页面测试。
- `filesystem`：读取源码和日志。
- `commands`：运行测试命令。
- `github`：读取 diff。

#### Skills

- Test Strategy
- E2E Testing
- Regression Testing
- Silent Failure Hunter
- Accessibility Smoke

#### Rules

- 没跑过命令，不能说测试通过。
- 没截图，不能说 UI 可用。
- 发现 P0/P1 必须打回 Developer。
- 测试报告必须包含命令、退出码、日志摘要。

#### Hooks

- `before_qa`：确认 Developer artifact 存在。
- `run_build`：构建。
- `run_unit_tests`：单测。
- `run_browser_smoke`：打开页面截图。
- `on_failure`：生成 bug report 并路由给 Developer。

#### Subagents

- E2E Runner。
- Accessibility Architect。
- Security Smoke Reviewer。

#### 强制产物

- `test_report.md`
- `build.log`
- `test.log`
- `browser_screenshot.png`
- `console_errors.json`
- `qa_result.json`

#### Evidence Gate

- build exit code 记录。
- test exit code 记录。
- 页面截图存在。
- console error 记录。
- P0/P1 为 0 才能进入部署。

### 6. DevOps Agent：发布与运行官

#### 定位

DevOps Agent 不是“写部署说明”。它必须把产物变成可访问 URL。

30+ 年经验体现：

- 会区分本地 preview、静态发布、云部署。
- 会做 health check。
- 会准备回滚。
- 会记录部署清单。
- 会暴露配置缺失，而不是假装部署。

#### 推荐模型

- 主模型：Claude Sonnet / DeepSeek V4，用于部署诊断。
- 快速模型：DeepSeek Chat / Qwen，用于 runbook。

#### MCP

- `vercel`：部署和 preview。
- `github`：PR / CI 状态。
- `filesystem`：读取 dist 和配置。
- `commands`：运行 build/preview。
- `sentry`：后续生产监控。

#### Skills

- Deploy Checklist
- CI/CD
- Release Engineering
- Rollback Planning
- Cost/Resource Check

#### Rules

- 没有 preview URL，不能标记部署完成。
- 没有 health check，不能进入验收。
- 缺 token 必须进入“等待配置”，不能生成假 URL。
- 部署产物必须和 QA 通过的 commit/worktree 一致。

#### Hooks

- `before_deploy`：确认 QA pass。
- `build_dist`：构建静态产物。
- `start_preview`：启动预览。
- `health_check`：访问 URL。
- `after_deploy`：写 deploy manifest。

#### Subagents

- Deployment Expert。
- Security Reviewer。
- Cost Reviewer。

#### 强制产物

- `preview_url`
- `deploy_manifest.json`
- `health_check.json`
- `ops_runbook.md`
- `rollback_plan.md`

#### Evidence Gate

- URL 可访问。
- HTTP status 正常。
- 页面截图存在。
- 回滚方案存在。

### 7. Acceptance Agent：最终验收官

#### 定位

Acceptance Agent 是客户验收代表，不是“总结报告生成器”。

30+ 年经验体现：

- 逐条对照 PRD 验收标准。
- 只认 artifact 和 evidence。
- 不合格明确退回阶段。
- 不被漂亮文案欺骗。

#### 推荐模型

- 主模型：Claude Opus / Sonnet / GPT-4.1 / DeepSeek V4 reasoning。
- 辅助模型：DeepSeek Chat，用于整理报告。

#### MCP

- `filesystem`：读取全部 artifact。
- `browser`：打开 preview。
- `github`：确认代码状态。
- `sentry`：后续读取错误。

#### Skills

- Acceptance Testing
- Product QA
- Risk Review
- Client Delivery Review

#### Rules

- 每条验收标准必须 PASS / FAIL / PARTIAL。
- FAIL 必须指明退回阶段。
- 缺 evidence 不能通过。
- 验收报告必须面向客户可读。

#### Hooks

- `before_acceptance`：检查 artifact 完整度。
- `verify_preview`：打开 preview URL。
- `criteria_check`：逐条验收。
- `on_reject`：生成 `REJECT_TO: stage_id`。
- `on_approve`：生成分享页和交付包。

#### Subagents

- Product Reviewer。
- QA Reviewer。
- Security Reviewer。
- Customer Success Reviewer。

#### 强制产物

- `acceptance.md`
- `acceptance_result.json`
- `delivery_summary.md`
- `share_ready.json`

#### Evidence Gate

- 所有 required artifact 存在。
- preview URL 可访问。
- 验收标准逐项有结果。
- 没有 P0/P1 风险。

## Slash 命令如何映射到 7 个 Agent

用户最终不应该手动点很多页面，而是可以用命令驱动整家公司。

### `/spec`

负责人：Product Agent  
参与：Architect、Designer 可按需审查  
结果：锁需求、范围、验收标准。

### `/design`

负责人：Designer Agent  
参与：Product、Frontend Feasibility Subagent  
结果：UI spec、设计 token、UI mockup。

### `/arch`

负责人：Architect Agent  
参与：Security、Database、Performance Subagents  
结果：架构图、API/data/file contract。

### `/code`

负责人：Developer Agent  
参与：Build Resolver、Security Reviewer、TypeScript Reviewer  
结果：真实代码、build log。

### `/qa`

负责人：QA Agent  
参与：E2E Runner、Accessibility Reviewer  
结果：测试日志、浏览器截图、打回意见。

### `/ship`

负责人：DevOps Agent  
参与：Deployment Expert、Security Reviewer  
结果：preview URL、health check、runbook。

### `/accept`

负责人：Acceptance Agent  
参与：Product、QA、Security  
结果：验收结论、分享链接。

### `/retro`

负责人：Orchestrator Kernel  
参与：所有失败相关 Agent  
结果：学习信号、规则更新、技能更新、模板修正。

## 每个 Agent 如何自主提升

自主提升不是“下次 prompt 写好点”。必须分四层。

### 1. Prompt 层

从失败反馈中提炼 prompt addendum。

适合：

- 输出格式不稳定。
- 老是漏章节。
- 容易忘记某些检查项。

### 2. Rule 层

把反复失败变成硬规则。

例如：

- Designer 连续 3 次没生成图，则增加规则：缺 `ui_mockup` 必须阻断。
- QA 连续发现 build 漏跑，则增加规则：没有 build log 不能完成。

### 3. Skill 层

把可复用流程变成 Skill。

例如：

- Vue/Vite 生成套路。
- Element Plus 表单页套路。
- Playwright smoke 测试套路。
- Vercel preview 部署套路。

### 4. Template 层

如果同类任务反复成功，把它固化为模板。

例如：

- Todo App 模板。
- CRM Dashboard 模板。
- Admin CRUD 模板。
- Landing Page 模板。

这才是“军团自主提升”。

## 落地改造优先级

### P0：先实现 Agent 装备表

给每个 Agent 增加可配置能力：

- `model_policy`
- `mcp_bindings`
- `skill_bindings`
- `rulesets`
- `hooks`
- `subagents`
- `artifact_contract`
- `evidence_gates`

### P1：实现 Rule Pack 自动加载

每个会话自动加载：

- OpenSpec rules：写代码前。
- Superpowers rules：写代码中。
- gstack ship rules：写代码后。
- Repo rules：项目本身规范。

### P2：实现 Slash Command 到 Delivery Workflow

新增命令路由：

- `/build`
- `/spec`
- `/design`
- `/arch`
- `/code`
- `/qa`
- `/ship`
- `/accept`
- `/retro`

这些命令不是聊天快捷语，而是 Orchestrator Kernel 的入口。

### P3：实现每个 Agent 的 Evidence Gate

先从 Developer / QA / DevOps 做起：

- Developer：真实代码 + build log。
- QA：test log + screenshot。
- DevOps：preview URL + health check。

### P4：实现 Agent 作战图

Team 页面不再展示静态关系，而是展示：

- 谁接了任务。
- 谁产出了 artifact。
- 谁审查了谁。
- 谁打回了谁。
- 谁修复了问题。
- 哪个 Agent 成功率最高。

## 一句话结论

7 个 Agent 能不能强，不取决于 persona 写得多豪华，而取决于它们是否拥有：

- 专属模型策略。
- 专属工具和 MCP。
- 专属技能。
- 专属规则。
- 专属 hook。
- 专属 subagent。
- 专属产物合同。
- 专属证据门禁。
- 专属学习闭环。

目前项目已经有一部分零件，但没有把这些零件装到每个 Agent 身上。下一步要做的不是继续写“30 年经验”的人设，而是把 30 年经验变成每个 Agent 的默认工作系统。

## 核心弊端：不是功能缺口，而是系统设计方向偏了

当前项目最深层的问题，不是“还没有 UI 设计图”“还没有部署链接”“工作流偶尔断”，而是系统仍然按“把多个 LLM 调用串起来”的思路建设，却想达到“AI 团队稳定交付产品”的效果。

这两者不是同一个架构层级。

真正的 AI-agent 军团不是多个角色 prompt 的集合，而是一个交付操作系统。它需要有组织结构、任务协议、状态机、工具执行、证据产物、质量门禁、失败恢复、资源调度、模型治理和最终部署闭环。当前项目有很多这些名词，但它们还没有形成一个强约束系统。

### 核心弊端一：把 Agent 当角色，而不是当可执行工人

当前 Agent 的核心仍然是：

- 给不同角色一段 system prompt。
- 给它们绑定一些工具名。
- 让它们输出 Markdown。
- 再让另一个 Agent 审阅 Markdown。

这会产生“像团队”的表象，但没有“团队执行”的确定性。

真正的 Agent 应该是可执行工人：

- 接收结构化任务。
- 读取指定上下文。
- 使用被授权工具。
- 写入指定 artifact。
- 输出机器可校验的结果。
- 失败时返回标准错误。
- 被上级 agent 或 orchestrator 重新调度。

当前最致命的问题是：Agent 产物不是强 contract，而是自然语言。自然语言适合展示，不适合作为下游执行的唯一依据。

### 核心弊端二：没有“军团总司令”的硬控制面

现在 Lead Agent / Pipeline Engine / DAG Orchestrator / Workflow Runner 都承担了一部分总控职责，但没有一个统一的控制面。

缺失的控制面包括：

- 谁决定任务拆解？
- 谁决定进入哪个阶段？
- 谁判断 artifact 是否合格？
- 谁决定重试、返工、升级、暂停？
- 谁拥有全局上下文预算？
- 谁负责成本、模型、工具权限？
- 谁最终签发交付？

如果这些职责散落在多个模块里，系统就会出现“每个模块都觉得自己完成了，但用户流程没有完成”的问题。

真正的军团需要一个 Orchestrator Kernel，而不是多个互相绕开的执行入口。

### 核心弊端三：缺少统一任务协议

当前任务从一句话进入系统后，后续阶段大多通过 prompt 拼接传递上下文。这样会导致：

- 上游输出格式不稳定。
- 下游理解依赖模型发挥。
- 失败无法精准定位字段。
- Artifact 无法机器校验。
- 不同执行入口语义不一致。

真正系统需要统一任务协议，例如：

```json
{
  "task_id": "uuid",
  "goal": "用户一句话目标",
  "scope": ["必须完成的功能"],
  "non_goals": ["明确不做的功能"],
  "acceptance_criteria": ["可验收条件"],
  "required_artifacts": ["prd", "ui_mockup", "architecture_diagram", "source_code", "test_report", "preview_url"],
  "constraints": {
    "template": "vue-vite-spa",
    "deadline_minutes": 30,
    "max_cost_usd": 2.0
  }
}
```

所有 Agent 都围绕这个协议工作，而不是自由发挥。

### 核心弊端四：没有证据优先的工程文化

AI 产品最容易失败的地方是“看起来完成”。当前系统也有这个倾向：

- PRD 看起来长，但不一定可验收。
- 设计说明看起来完整，但没有图。
- 架构说明看起来专业，但没有和代码绑定。
- 代码说明看起来像实现，但不一定有文件。
- 测试报告看起来像测试，但不一定跑过。
- 部署说明看起来能上线，但没有 URL。

真正的交付平台必须反过来：先要证据，再写总结。

每个阶段都要问：

- 文件在哪里？
- 图在哪里？
- 日志在哪里？
- URL 在哪里？
- 截图在哪里？
- 测试退出码是什么？
- 谁验证过？

没有证据，就不能进入下一阶段。

### 核心弊端五：系统没有围绕“成功率”优化

现在系统更像围绕“能力覆盖”优化：模型、技能、workflow、artifact、share、upload、memory 都有。

但商业产品应该围绕“成功率”优化：

- 一句话任务完整成功率。
- 首次构建成功率。
- 自动修复成功率。
- UI 图生成成功率。
- 预览 URL 可访问率。
- 用户验收通过率。

没有成功率指标，系统就会不断增加功能，却不知道是否真的变好。

### 核心弊端六：资源层没有产品化

AI 军团需要大量外部资源：

- LLM 模型。
- 视觉模型。
- 浏览器。
- 文件系统。
- 沙箱。
- 包管理器。
- Git。
- 部署平台。
- Figma / 设计工具。
- 数据库。
- 缓存。
- 向量检索。
- 密钥。

当前项目很多资源是“可选配置”，但没有被设计成产品级资源池。

结果是：缺 key、缺 CLI、缺环境、缺部署 token 时，系统不是清晰进入“等待资源配置”，而是跳过、fallback 或生成文字说明。

真正的系统必须先做资源体检，再执行任务。

### 核心弊端七：没有把我这样的 Coding Agent 放在正确位置

如果目标是让我来实现真正 AI-agent 军团，不能把我当成“单次写代码工具”，而应该把我放进工程闭环：

- 我负责设计架构和拆分阶段。
- 我负责逐步修改代码。
- 我负责写 Hero Path 测试。
- 我负责运行验证。
- 我负责根据失败日志修复。
- 我负责更新文档和验收报告。

也就是说，我应该作为“平台建设工程师 + 自测执行者”进入循环，而不是每次只回答一个局部问题。

## 暴露出来的问题

### 1. 流程测试证明的是 API 存活，不是用户旅程成功

当前流程测试覆盖了任务创建、artifact 写入、工作记忆、工作流保存、模型列表、凭证、分享、deliverables zip 等能力，但大量测试绕开真实 LLM、真实 workflow run、真实工具调用、真实构建和真实部署。

典型风险：

- 测试通过后，仍然不能证明“一句话到完整交付”能跑通。
- `smart-run` / `auto-run` 测试通过，是因为 monkeypatch 了真实执行函数。
- 工作流保存和读取被测了，但工作流真实执行没有形成强验收。
- 没有一条 CI 级别的 Hero Path E2E 测试。

结果是系统看起来很完整，但失败会集中暴露在真实用户执行时。

### 2. Workflow Runner 仍是 Demo 级执行器

当前 saved workflow runner 真正执行的是 `llm` 和 `http` 节点。`tool`、`knowledge_retrieve`、`loop` 等节点仍是 stub。

这意味着用户看到的是“工作流编辑器”，但底层不是完整的 agentic workflow engine。

风险：

- 工具节点无法真正调用工具。
- 知识检索节点无法真正检索上下文。
- 循环节点无法做迭代修复。
- 条件节点只能做简单字符串判断。
- UI 上的“运行工作流”和 Pipeline DAG 执行模型不完全统一。

这会造成产品体验断裂：用户以为在编排 AI 军团，实际只是运行一串浅层节点。

### 3. Scheduler 不是 durable workflow

当前调度器能限制并发、持久化队列，但运行中的任务不持久化。如果进程重启、热重载、worker 崩溃，in-flight pipeline 会丢失，需要人工重新触发。

风险：

- 长流程容易断。
- 用户不知道断在哪里。
- 任务可能停留在 `active`、`paused`、`running` 等不可靠状态。
- 恢复逻辑依赖后补清理，而不是原生可恢复状态机。

商业级交付平台需要的是 durable workflow：每个阶段状态、输入、输出、重试、失败、恢复、审计都可持久化。

### 4. `force_continue=True` 容易制造假完成

`auto-run` 默认强制继续，阶段失败时可能跳过继续跑。这样可以减少卡死，但也容易让系统生成不完整交付。

风险：

- 失败没有阻断最终交付。
- 用户看到流程结束，但 artifact 质量不完整。
- 质量门禁、peer review、verification 的权威性被削弱。
- 系统从“修复失败”变成“绕过失败”。

稳定交付平台应该把失败显性化，并提供可恢复路径，而不是默认跳过。

### 5. Agent 军团更多是角色提示词，不是执行组织

当前有 CEO、架构师、设计师、开发、QA、DevOps、验收等角色，但很多协作仍依赖 prompt 和 Markdown 传递。

真正的 AI 军团应该具备：

- 每个 Agent 有明确职责边界。
- 每个 Agent 有可调用工具和权限。
- 每个 Agent 产出结构化 artifact。
- 下游 Agent 能机器读取上游 artifact。
- 主管 Agent 能判断失败、退回、重试、升级。
- 所有关键判断都有证据。

当前问题：

- Agent 之间缺少强任务协议。
- 产物多是自然语言，不是结构化合同。
- Delegate 更像辅助调用，不是任务队列。
- Review 更多是 LLM 再评一次文本，不是基于证据的验收。

所以系统有“军团感”，但没有“军团执行力”。

### 6. PRD、设计图、架构图、代码、测试、部署没有统一交付合同

目标产物虽然都有入口，但缺少统一、强制、可验收的 artifact contract。

当前风险：

- PRD 可能只是长文档，没有结构化用户故事和验收标准。
- UI 设计可能只是规格说明，没有真实图片或可点击原型。
- 架构图可能只是 Mermaid HTML，没有和代码、API、部署对应。
- 代码可能只是实现说明，或 CodeGen 失败后的 fallback 文本。
- 测试报告可能只是模型写的报告，不一定来自真实测试。
- 部署阶段可能只是 runbook，不一定有可访问 URL。

交付平台不能只交“说明”，必须交“证据”。

### 7. 图片上传和多模态上下文没有产品级治理

系统已经支持上传图片和文本，并能把图片转成多模态输入。但这还不是完整的上下文系统。

风险：

- 图片数量和大小受限，超限后只是文本提示。
- 不同模型对多模态支持不同，fallback 后可能丢失视觉信息。
- 上传文件没有被转成可追踪需求引用。
- 设计图、截图、参考图、附件在 artifact 和 prompt 中的身份不统一。

用户上传的图片应该成为任务上下文的一等公民，而不是“附加 prompt”。

### 8. UI 设计图生成链路不稳定

设计阶段提示词要求调用 `generate_image_asset`，但图片生成依赖 OpenAI Images key。另一个 UI Visualizer 依赖本地脚本或 Gemini key。缺失时可能只产生 HTML 或空图片。

风险：

- 用户期待 UI 设计图，但拿到的是 Markdown。
- 生成失败没有清晰的产品提示和补救路径。
- 设计图 artifact 路径、预览、下载、版本管理不够统一。
- Figma / Design MCP 还没有成为稳定交付路径。

设计阶段必须从“建议生成视觉稿”升级为“必须生成可预览设计证据；失败则明确阻断或请求配置”。

### 9. 架构图是文本解析产物，不是强语义模型

当前架构图主要通过解析架构阶段输出生成 Mermaid HTML。它有价值，但还不够强。

风险：

- 架构图可能和实际代码不一致。
- API、数据模型、部署拓扑之间没有一致性校验。
- Mermaid 渲染成功不代表架构正确。
- 架构图没有成为后续开发和部署的强输入。

架构图应该和 API 契约、数据模型、文件清单、部署拓扑绑定。

### 10. 代码生成没有固定黄金模板和强验证

开发阶段可能调用 CodeGenAgent / Claude CLI 写文件，也可能失败后 fallback 到普通 LLM 文本。

风险：

- 生成代码不一定可运行。
- 没有固定项目模板导致成功率波动。
- 安装、构建、测试、预览不是每次强制执行。
- 失败后 auto-fix 不一定能闭环。
- 测试报告可能没有真实构建证据。

商业级 MVP 应先支持极少数黄金模板，而不是追求通用。

### 11. 部署链接还不是强制产物

目标要求部署链接，但当前部署阶段更像生成部署说明或配置文件。

风险：

- 没有真实 preview URL。
- 没有部署状态机。
- 没有部署失败恢复。
- 没有截图或健康检查证明链接可用。

如果没有可访问 URL，就不能宣称“完成交付”。

### 12. UI 展示没有把失败变成可操作体验

用户现在感知到的是“流程断了”。这说明失败被记录了，但没有被产品化解释和引导。

需要暴露：

- 断在哪个阶段。
- 为什么断。
- 谁负责。
- 缺什么配置。
- 下一步自动做什么。
- 用户可以点什么。

失败不是异常情况，而是 agent 产品的核心交互。

## 根因总结

### 根因一：概念铺得太宽，闭环打得不够深

项目同时追求 Agent 军团、Workflow、Skill、MCP、Artifact、Share、Upload、Observability、Cost、Deployment、Memory、Gateway 等能力，但没有先把一条商业主路径做到高成功率。

结果是模块很多，用户价值却不稳定。

### 根因二：过度依赖 LLM 自觉，缺少机器验收

提示词里写了很多“必须完整”“禁止省略”“必须生成设计图”，但 LLM 不可靠。真正可靠的是：

- Schema 校验
- 文件存在校验
- 构建校验
- 测试校验
- 浏览器截图校验
- 部署健康检查
- artifact 完整度校验

没有这些，prompt 再强也会断。

### 根因三：状态机不够硬

长任务必须被设计成可恢复状态机，而不是后台协程。

当前系统有 scheduler、cleanup、trace、SSE，但缺少真正的 durable execution。

### 根因四：产物没有从“文档”升级为“证据”

AI 交付平台的核心不是生成文字，而是生成可验收证据：

- PRD 有验收标准。
- UI 有图。
- 架构有图。
- 代码能跑。
- 测试有日志。
- 部署有 URL。
- 页面有截图。
- 分享页能验收。

### 根因五：没有黄金路径成功率指标

当前缺少一个明确指标：

> 100 次“一句话生成 Vue/Vite 小应用”，至少 80 次完整交付到可访问预览链接。

没有这个指标，开发会继续被模块数量牵引，而不是被成功率牵引。

## 如果由我来实现真正的 AI-agent 军团

我不会继续从“加更多 Agent、加更多模型、加更多页面”开始。我会把系统重构成一个交付操作系统，核心是：

> Orchestrator Kernel + Agent Workers + Durable Workflow + Artifact Contract + Tool Sandbox + Evidence Gates + Deployment Runtime

也就是先建立一条稳定、可恢复、可验收的生产线，再逐步扩展 agent 数量、模型数量和任务类型。

### 1. 产品边界：先只做一个可成功的军团

第一版只服务一个任务类型：

> 用户一句话生成一个可运行 Web App，并获得 PRD、UI 图、架构图、代码、测试报告、预览 URL、分享页。

我会先砍掉泛化能力：

- 不做任意复杂工作流。
- 不做所有技术栈。
- 不做多端发布。
- 不做大型企业项目改造。
- 不做任意 MCP 市场。

先支持一个黄金模板：

- Frontend：Vue 3 + Vite + TypeScript。
- UI：Element Plus 或轻量自研组件。
- Build：npm / pnpm 固定命令。
- Test：Vitest + Playwright smoke。
- Preview：本地 preview server，后续接 Vercel / Cloudflare Pages。

目标不是“看起来强”，而是 100 次里 80 次能完整交付。

### 2. 总体架构

我会把系统拆成 7 层。

```text
User Request
    |
    v
Intake & Clarifier
    |
    v
Orchestrator Kernel
    |
    +--> Product Agent
    +--> Designer Agent
    +--> Architect Agent
    +--> Developer Agent
    +--> QA Agent
    +--> DevOps Agent
    +--> Acceptance Agent
    |
    v
Artifact Store + Evidence Store
    |
    v
Sandbox Runtime
    |
    v
Preview / Deploy Runtime
    |
    v
Share & Acceptance
```

每层职责：

- Intake & Clarifier：把一句话变成结构化任务。
- Orchestrator Kernel：唯一总控，负责状态、调度、模型、失败恢复。
- Agent Workers：只做自己阶段的工作，不拥有全局流程。
- Artifact Store：保存结构化产物。
- Evidence Store：保存截图、日志、URL、测试结果。
- Sandbox Runtime：安装、构建、测试、运行。
- Deploy Runtime：生成可访问链接。

### 3. Orchestrator Kernel：真正的军团大脑

我会新建或重构一个 `OrchestratorKernel`，不要让 `pipeline_engine`、`dag_orchestrator`、`workflow_runner` 各自为政。

Kernel 的职责：

- 创建任务计划。
- 确定阶段顺序。
- 选择 Agent。
- 选择模型。
- 注入上下文。
- 调用 Agent。
- 验证 artifact。
- 决定重试、返工、暂停、升级。
- 写入事件和 trace。
- 最终签发交付。

核心数据结构：

```python
class DeliveryRun:
    id: str
    task_id: str
    goal: str
    template: str
    status: RunStatus
    current_stage: str
    stages: list[DeliveryStage]
    budget: Budget
    created_at: datetime
    updated_at: datetime

class DeliveryStage:
    id: str
    role: str
    agent_id: str
    status: StageStatus
    input_snapshot_id: str
    output_artifact_ids: list[str]
    evidence_ids: list[str]
    retry_count: int
    failure_reason: str | None
```

重要原则：

- 所有状态进数据库。
- 所有阶段输入输出可重放。
- 所有失败可恢复。
- 不再依赖后台协程记忆当前状态。

### 4. Agent 组织方式

我不会先做 14 个同等复杂度 Agent。第一版只需要 7 个核心 Agent。

#### Product Agent

职责：

- 需求澄清。
- PRD。
- 用户故事。
- 验收标准。
- 非目标。

强制输出：

- `prd.json`
- `prd.md`
- `acceptance_criteria.json`

#### Designer Agent

职责：

- 设计 token。
- 页面结构。
- 组件规范。
- UI mockup。

强制输出：

- `ui_spec.md`
- `design_tokens.json`
- `screen_plan.json`
- `ui_mockup.png`
- `ui_mockup.html`

#### Architect Agent

职责：

- 技术选型。
- API/data/file plan。
- 架构图。

强制输出：

- `architecture.md`
- `architecture.mmd`
- `architecture.html`
- `file_plan.json`
- `api_contract.json`

#### Developer Agent

职责：

- 基于模板写代码。
- 不自由创建任意工程结构。
- 修复 build/test 错误。

强制输出：

- 真实源码文件。
- `source_manifest.json`
- `build_command`
- `run_command`

#### QA Agent

职责：

- 执行真实测试。
- 运行浏览器 smoke。
- 记录日志和截图。

强制输出：

- `test_report.md`
- `build.log`
- `test.log`
- `browser_screenshot.png`
- `qa_result.json`

#### DevOps Agent

职责：

- 启动 preview。
- 部署或生成预览链接。
- 健康检查。

强制输出：

- `preview_url`
- `deploy_manifest.json`
- `health_check.json`
- `ops_runbook.md`

#### Acceptance Agent

职责：

- 按 PRD 验收。
- 检查证据是否齐全。
- 决定通过或退回。

强制输出：

- `acceptance.md`
- `acceptance_result.json`
- `reject_to_stage` 或 `approved`

### 5. 模型策略

我会按任务类型选择模型，而不是所有阶段用一个模型。

#### 高推理模型

用于：

- 需求拆解。
- 架构设计。
- 失败诊断。
- 验收判断。

候选：

- Claude Sonnet / Opus 级别。
- GPT-4.1 / GPT-5 级别。
- Gemini Pro 级别。

要求：

- 长上下文。
- 稳定结构化输出。
- 强代码理解。

#### 快速执行模型

用于：

- 文档补全。
- 小修改。
- 低风险转换。
- 简单总结。

候选：

- DeepSeek Chat。
- Qwen。
- GLM Flash。
- Gemini Flash。

要求：

- 成本低。
- 延迟低。
- 支持 fallback。

#### 代码模型 / Coding Agent

用于：

- 写代码。
- 修复构建错误。
- 修改模板。

候选：

- Claude Code / Cursor Agent / Codex 类执行器。
- 不能只使用普通 chat completion。

要求：

- 能读写文件。
- 能运行命令。
- 能根据错误日志迭代。

#### 视觉模型

用于：

- UI mockup。
- 图片理解。
- 参考图分析。

候选：

- OpenAI Images。
- Gemini 图像生成。
- Figma MCP / Design MCP。

要求：

- 没有视觉模型时，设计阶段不能假装完成。
- 必须进入“缺少设计资源”状态。

#### 模型路由规则

每次模型调用前，Kernel 应决定：

- 阶段是什么？
- 当前失败次数多少？
- 是否需要长上下文？
- 是否需要视觉输入？
- 是否需要工具调用？
- 当前预算剩多少？
- 哪些 provider 可用？

模型选择不应散在每个服务里，而应该由统一 Model Policy 决策。

### 6. 上下文系统

我会把上下文分成 5 类，而不是简单拼 prompt。

#### Task Context

当前任务的目标、约束、验收标准。

#### Artifact Context

上游阶段产物，包括 PRD、设计、架构、代码 manifest。

#### Evidence Context

真实日志、截图、构建结果、测试结果、部署结果。

#### Memory Context

历史任务中可复用的经验，但必须低优先级，不能污染当前任务。

#### Uploaded Context

用户上传的图片、文件、参考材料。

上下文注入规则：

- 不能把所有历史都塞进 prompt。
- 每阶段只拿所需 artifact。
- 图片必须有引用 ID。
- 文本文件必须有摘要和原文路径。
- 超长内容必须先摘要，再允许按需展开。

我会实现一个 `ContextAssembler`：

```python
class ContextAssembler:
    async def build_for_stage(
        self,
        task_id: str,
        stage_id: str,
        role: str,
        max_tokens: int,
    ) -> StageContext:
        ...
```

它负责：

- 选择上下文。
- 控制 token。
- 保留引用。
- 给模型明确输入边界。

### 7. Artifact Contract

我会把 artifact 从“展示数据”升级为“阶段通过条件”。

每个阶段定义：

- 必需 artifact。
- 可选 artifact。
- schema。
- 校验器。
- 下游依赖。

例如设计阶段：

```json
{
  "stage": "design",
  "required": [
    "ui_spec",
    "design_tokens",
    "screen_plan",
    "ui_mockup"
  ],
  "validators": [
    "markdown_not_empty",
    "json_schema_valid",
    "file_exists",
    "image_readable"
  ]
}
```

如果 `ui_mockup.png` 不存在，设计阶段就是失败，不允许写一句“由于缺少 API key，建议后续生成”然后继续。

### 8. 工具和资源

真正 AI 军团需要资源池。

#### 必备资源

- LLM API keys。
- 图像生成 API key。
- Browser / Playwright。
- Node.js / pnpm / npm。
- Python。
- Git。
- 沙箱目录。
- 预览服务端口池。
- Redis。
- PostgreSQL。

#### 可选资源

- Figma MCP。
- Vercel token。
- Cloudflare token。
- GitHub token。
- 向量数据库。
- Sentry。

#### Resource Manager

我会做一个 `ResourceManager`，任务执行前先体检：

```json
{
  "llm": "ok",
  "vision": "missing_key",
  "node": "ok",
  "browser": "ok",
  "deploy": "not_configured"
}
```

体检结果决定执行策略：

- 必需资源缺失：阻断。
- 可选资源缺失：降级。
- 降级后不能满足目标：请求用户配置。

这比现在执行到一半再失败更可靠。

### 9. Sandbox Runtime

代码生成必须在沙箱里完成。

Sandbox 要负责：

- 创建任务工作目录。
- 初始化模板。
- 限制文件写入范围。
- 安装依赖。
- 构建。
- 测试。
- 启动 preview。
- 收集日志。
- 截图。

所有命令都要有：

- timeout。
- stdout/stderr 保存。
- exit code。
- resource limit。
- artifact 写入。

第一版可以先本地沙箱，后续升级 Docker。

### 10. Evidence Gate

每个阶段结束时，不是问“模型说 OK 吗”，而是问证据是否存在。

#### PRD Gate

- 有用户故事。
- 有验收标准。
- 有非目标。
- JSON schema 通过。

#### Design Gate

- 有设计 token。
- 有 screen plan。
- 有 UI 图。
- 图片文件存在且可读取。

#### Architecture Gate

- 有 Mermaid。
- Mermaid 能渲染。
- 有 file plan。
- 有 API/data contract。

#### Development Gate

- 源码文件存在。
- package.json 存在。
- build command 存在。

#### QA Gate

- build exit code = 0。
- test exit code = 0 或有明确可接受失败。
- browser screenshot 存在。

#### Deploy Gate

- preview URL 存在。
- health check 通过。
- 页面截图存在。

#### Acceptance Gate

- 所有必需 artifact 存在。
- 所有 evidence 存在。
- 按验收标准逐项 PASS / FAIL。

### 11. 工作流实现方式

我会把当前 workflow 分成两类：

#### Delivery Workflow

这是产品主线，必须稳定。

- 固定阶段。
- 强状态机。
- 强 artifact contract。
- 强 evidence gate。

#### Custom Workflow

这是高级能力，等主线稳定后再做。

- 可视化 Builder。
- 自定义节点。
- 自定义工具。
- 自定义 loop。

当前项目的问题是太早把 Custom Workflow 放到产品中心。应该先让 Delivery Workflow 成功，再把 Builder 作为可视化编辑器接入同一套 Kernel。

### 12. 部署策略

我会分三步做部署。

#### Step 1：本地 Preview URL

先不接云平台。

- 启动 `npm run dev -- --host 0.0.0.0 --port <allocated>`。
- 健康检查。
- Playwright 截图。
- 写入 preview URL。

#### Step 2：静态构建产物

- `npm run build`。
- 保存 `dist/`。
- 提供本地静态服务。

#### Step 3：云部署

接入：

- Vercel。
- Cloudflare Pages。
- Netlify。

部署不是第一天重点。第一天重点是用户能打开预览。

### 13. 我会如何实际推进代码实现

我会按下面顺序动手，而不是一次性重写。

#### 第一刀：写 Hero Path 测试

先写测试暴露失败。

- 创建任务。
- 执行 delivery run。
- 等待完成。
- 检查 artifact。
- 检查源码。
- 检查构建日志。
- 检查 screenshot。
- 检查 preview URL。

没有这个测试，所有改动都没有方向。

#### 第二刀：新增 DeliveryRun / DeliveryStage 表

不要马上推翻现有 PipelineTask。先新增运行层。

- `delivery_runs`
- `delivery_stages`
- `delivery_evidence`

旧的 PipelineTask 继续作为任务入口。

#### 第三刀：实现 OrchestratorKernel MVP

只支持黄金模板。

阶段固定：

1. intake
2. product
3. design
4. architecture
5. development
6. qa
7. preview
8. acceptance

#### 第四刀：实现 Artifact Contract 校验

先做简单校验：

- 非空。
- JSON schema。
- 文件存在。
- 命令退出码。
- URL 健康检查。

#### 第五刀：实现 Sandbox Runtime

先支持 Vue/Vite：

- 初始化模板。
- 写文件。
- npm install。
- npm run build。
- npm run dev。
- Playwright screenshot。

#### 第六刀：把 UI 接到新运行层

任务详情页显示：

- 当前 run。
- 当前 stage。
- 失败卡片。
- artifact 完整度。
- evidence。
- 一键重试。

#### 第七刀：再接回现有 Agent 和 Workflow

把现有 AgentRuntime、LLM Router、Artifact Writer、SSE、Trace 逐步接到 Kernel，而不是让它们继续平行发展。

### 14. 技术资源清单

#### 后端

- FastAPI：保留。
- SQLAlchemy：保留。
- PostgreSQL：作为生产主库。
- Redis：队列、事件、缓存，但不能作为唯一状态源。
- Playwright：浏览器验证。
- Docker：后续沙箱隔离。

#### 前端

- Vue 3：保留。
- Vite：保留。
- Element Plus：保留。
- Vue Flow：后续只作为 workflow 可视化，不作为主线必要能力。

#### 模型

- 一个强推理模型：负责规划、架构、验收、失败诊断。
- 一个强代码执行器：负责真实文件改写和修复。
- 一个低成本执行模型：负责普通文档和总结。
- 一个视觉模型：负责 UI 图和参考图理解。

#### 外部服务

- Figma MCP：可选增强，不作为 MVP 必需。
- Vercel / Cloudflare：Phase 2 部署。
- GitHub：后续生成 PR。
- Sentry：后续生产问题观测。

### 15. 成本和速度考虑

不能每个阶段都用最贵模型。

策略：

- Intake：低成本模型。
- PRD：中高模型。
- Design：中高模型 + 视觉模型。
- Architecture：高推理模型。
- Development：coding agent。
- QA：本地命令优先，LLM 只分析日志。
- Acceptance：高推理模型，但输入是结构化证据。

成本治理原则：

- 能用机器验证，不用 LLM 判断。
- 能用 schema 校验，不用 LLM 审阅。
- 能用小模型做的，不用大模型。
- 大模型只处理高价值决策和失败诊断。

### 16. 最小可实施版本

第一版真正要实现的不是完整军团，而是一个最小军团：

```text
Product Agent -> Designer Agent -> Architect Agent -> Developer Agent -> QA Agent -> Preview Agent -> Acceptance Agent
```

每个 Agent 只完成一个清晰阶段。

每个阶段只允许通过 artifact contract 交付。

每个阶段都必须有 evidence gate。

每个失败都必须能重试或阻断。

这就是从“AI demo”走向“AI 交付系统”的关键。

## 分阶段执行计划

### Phase 0：冻结范围，定义唯一 Hero Path

目标：停止继续扩散功能，先定义唯一必须跑通的主路径。

主路径：

1. 用户输入一句话。
2. 系统生成结构化 PRD。
3. 系统生成 UI 设计规格和至少 1 张设计图。
4. 系统生成架构说明和至少 1 张架构图。
5. 系统生成 Vue/Vite 小应用代码。
6. 系统执行安装、构建、测试。
7. 系统启动预览并截图。
8. 系统生成分享链接和验收页。

暂时不做：

- 任意复杂 workflow。
- 多语言多框架通用代码生成。
- 复杂 MCP 市场化。
- 多平台部署。
- 大型企业 RBAC 深化。
- 泛化 App Store / Google Play 发布。

验收标准：

- 文档中明确唯一黄金模板：Vue 3 + Vite + Element Plus 或纯 Vue/Vite。
- 所有阶段都围绕这条路径服务。
- 新功能如果不能提高这条路径成功率，暂缓。

### Phase 1：建立 Hero Path E2E 测试

目标：先让失败可见，而不是先修所有问题。

任务：

- 新增一个真实端到端测试脚本或 pytest 标记测试。
- 输入固定一句话，例如：“做一个待办事项看板，支持新增、完成、删除任务。”
- 使用可控模型或 mock LLM fixture，但必须真实执行 pipeline 状态流转。
- 验证每个关键 artifact 存在。
- 验证代码目录存在。
- 验证构建命令被执行。
- 验证测试报告包含真实命令输出。
- 验证分享页可访问。

验收标准：

- 测试失败时能明确指出断在哪个阶段。
- 测试不能只检查接口 200。
- 测试必须验证最终交付包完整度。

产出：

- `backend/tests/test_hero_delivery_path.py`
- `docs/selftest-report.md` 更新为真实 Hero Path 结果。

### Phase 2：把 Pipeline 改成强状态机

目标：让流程断了也能知道、能恢复、能重试。

任务：

- 为每个阶段定义状态：`pending`、`running`、`succeeded`、`failed`、`blocked`、`retrying`、`awaiting_user`。
- 每个阶段启动前持久化输入快照。
- 每个阶段完成后持久化输出 artifact id。
- 运行中任务必须可恢复，不能只在内存协程里。
- 去掉默认假完成策略，`force_continue` 只允许调试模式使用。
- 增加统一失败卡片：阶段、原因、责任方、下一步。

验收标准：

- 进程重启后，任务能显示“上次断在 X 阶段”。
- 用户可以点击继续、重试、跳过、取消。
- 后端有明确的 resume API。
- UI 不再只显示“断了”，而是显示可执行恢复动作。

### Phase 3：定义 Artifact Contract

目标：每个阶段必须交结构化产物，不合格不能过。

建议合同：

PRD：

- `brief`
- `user_stories`
- `acceptance_criteria`
- `scope`
- `non_goals`

设计：

- `ui_spec`
- `design_tokens`
- `screen_list`
- `ui_mockup_png`
- `ui_mockup_html`

架构：

- `architecture`
- `architecture_diagram`
- `api_contract`
- `data_model`
- `file_plan`

开发：

- `source_files`
- `code_link`
- `build_command`
- `run_command`

测试：

- `test_report`
- `build_log`
- `test_log`
- `screenshot`

部署：

- `deploy_manifest`
- `preview_url`
- `health_check`
- `rollback_plan`

验收标准：

- Artifact 缺失则阶段失败。
- Artifact 不能只是自然语言。
- UI 能显示每个 artifact 的状态。
- 分享页展示的是完整交付证据。

### Phase 4：固定代码生成黄金模板

目标：先让一种项目稳定成功。

建议先只支持：

- Vue 3 + Vite 单页应用。
- 本地预览。
- 静态部署或 preview server。
- 后端先不做，除非任务明确需要 API。

任务：

- 准备干净模板。
- 开发阶段只允许在模板范围内改文件。
- 生成后强制运行 install/build/test。
- 失败后自动把错误交给开发 Agent 修复，最多 2 次。
- 修复仍失败则阻断，并展示真实日志。

验收标准：

- 10 个固定简单应用需求，至少 8 个能完整构建成功。
- 每个交付都有截图。
- 没有构建通过就不能进入部署阶段。

### Phase 5：把设计图和架构图变成强制证据

目标：从“写设计说明”升级为“产出可看图形”。

任务：

- 设计阶段必须产出至少一个可预览视觉 artifact。
- 如果 OpenAI/Gemini/Figma 配置缺失，阶段应明确阻断或进入“需要配置”状态，而不是静默跳过。
- 架构阶段必须产出 Mermaid 原文和 HTML 预览。
- 架构图必须和 API/data/file plan 一致性检查。

验收标准：

- 任务详情页能直接看到 UI 图和架构图。
- 分享页能看到图。
- 图缺失时，交付不能标记完成。

### Phase 6：真实测试与浏览器验证

目标：测试报告必须来自真实命令和浏览器证据。

任务：

- 自动运行 `npm install`、`npm run build`、`npm test` 或模板定义命令。
- 启动预览服务器。
- 用 Playwright 打开页面。
- 截图。
- 抽取页面文本和 console error。
- 如果页面打不开，退回开发阶段。

验收标准：

- 测试报告包含命令、退出码、日志摘要。
- 截图 artifact 存在。
- console error 不为 0 时标记风险。

### Phase 7：部署链接闭环

目标：没有 URL 不算完成。

MVP 可先做本地预览链接或静态 preview，然后再接 Vercel/Cloudflare。

任务：

- 定义 `preview_url` artifact。
- 部署阶段执行真实部署或真实预览。
- 健康检查 URL。
- 截图部署页面。
- 失败时给出修复动作。

验收标准：

- 交付包里有可访问 URL。
- URL 健康检查通过。
- 分享页引用该 URL。

### Phase 8：统一工作流产品体验

目标：Workflow Builder 不再是平行 demo，而是同一条交付引擎的可视化入口。

任务：

- 合并 saved workflow runner 和 DAG pipeline 的执行语义。
- `tool` 节点真正调用工具。
- `knowledge_retrieve` 节点接入任务上下文检索。
- `loop` 节点支持有限迭代和退出条件。
- 每个节点都有 artifact 输出和失败恢复。

验收标准：

- 用户从 Builder 创建的流程，和普通一句话任务使用同一套状态机、artifact、SSE、失败卡片。
- 不再出现 UI 上有节点、后端只是 stub 的情况。

## 每阶段成功指标

### 技术指标

- Hero Path 完整成功率。
- 平均完成时间。
- 阶段失败率。
- 自动修复成功率。
- artifact 完整率。
- 构建通过率。
- 预览 URL 可访问率。

### 产品指标

- 用户能否在 10 秒内看懂当前进度。
- 用户能否知道失败原因。
- 用户能否一键重试。
- 用户能否拿到可分享交付链接。
- 用户是否需要读后台日志才能判断状态。

### 质量指标

- PRD 是否有验收标准。
- UI 是否有可视设计图。
- 架构图是否可预览。
- 代码是否可运行。
- 测试是否来自真实执行。
- 部署链接是否可访问。

## 执行顺序建议

优先级从高到低：

1. Hero Path E2E 测试。
2. Pipeline 强状态机与失败恢复。
3. Artifact Contract。
4. Vue/Vite 黄金模板代码生成。
5. 构建、测试、截图验证。
6. UI 设计图和架构图强制证据。
7. 预览/部署链接。
8. Workflow Builder 语义统一。
9. 更多模板、更多模型、更多 MCP。

## 明确不做的事

在 Hero Path 成功率达到 80% 前，不建议继续投入：

- 新增更多 Agent 角色。
- 新增更多模型面板。
- 新增复杂市场功能。
- 新增更多部署平台。
- 扩展到移动端、小程序、App Store。
- 做复杂企业权限和计费。
- 做泛化任意代码库改造。

这些会增加复杂度，但不会直接修复“流程跑不通”的核心问题。

## 近期 7 天执行计划

### Day 1：写死黄金路径验收

- 明确唯一模板。
- 明确 artifact contract。
- 写 Hero Path 测试草案。
- 整理当前失败点。

### Day 2：让失败可见

- 增加阶段失败卡片字段。
- 暴露 scheduler / pipeline 真实状态。
- UI 展示当前阶段、失败原因、下一步。

### Day 3：收紧 artifact

- 每阶段缺 artifact 直接失败。
- 任务详情页显示完整度。
- 分享页显示缺失项。

### Day 4：代码生成模板化

- 固定 Vue/Vite 模板。
- 强制写入模板目录。
- 强制 build。

### Day 5：自动测试和截图

- 接入 Playwright 页面打开。
- 保存截图 artifact。
- 测试报告写入真实日志。

### Day 6：预览链接

- 启动本地 preview 或静态服务。
- 写入 `preview_url`。
- 做健康检查。

### Day 7：端到端跑 10 次

- 用 10 个简单需求跑完整链路。
- 记录失败原因。
- 只修最高频失败。

## 最终验收门槛

当下面条件满足时，才可以说系统进入可演示的商业 MVP：

- 10 个简单 Web App 需求，至少 8 个完整交付。
- 每个任务都有 PRD、UI 图、架构图、代码、测试报告、预览 URL。
- 每次失败都能在 UI 上看到明确原因和下一步。
- 不需要开发者看后台日志才能恢复任务。
- 分享页能展示完整交付证据。

当下面条件满足时，才可以说接近可售卖：

- 100 次黄金路径任务，成功率超过 80%。
- 平均失败恢复次数低于 1 次。
- 构建通过率超过 85%。
- 预览 URL 可访问率超过 90%。
- 用户验收通过率超过 70%。

## 核心原则

不要再证明“我们有很多模块”。  
接下来只证明一件事：

> 用户一句话进来，系统稳定给出一个能打开、能测试、能分享的小产品。

这件事没有稳定之前，AI 军团只是概念；这件事稳定之后，Agent、Workflow、Skill、MCP、Marketplace 才有商业价值。
