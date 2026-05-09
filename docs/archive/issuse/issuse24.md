# Issue 24｜最终 AI-Agent 执行手册：目标、链路、模型、验收

> 目标必须明确，思路必须清晰，执行力必须严谨。  
> 本文承接 `issuse19`、`issuse20`、`issuse21`、`issuse22`、`issuse23`，把前面的诊断收敛成一份可执行手册。

---

## 0. 一句话目标

把 `agent-hub` 从“有很多 Agent 概念的 LLM Wrapper”改造成真正的 AI 交付军团：

```text
OpenClaw / Web / Feishu / QQ
  → Clarifier
  → CEO Agent
  → Product Agent
  → UI/UX Agent
  → Architecture Agent
  → Development Agent + Claude Code
  → QA Agent
  → Acceptance Agent
  → DevOps Agent
  → Share / Deploy / Archive
```

最终用户不关心系统有多少页面、多少模型、多少 Agent。用户只关心：

- 需求有没有被接住。
- 谁正在处理。
- 产物在哪里。
- 能不能验收。
- 能不能上线。

---

## 1. 北极星验收标准

只有同时满足以下条件，才算真正达到最终 AI-Agent：

| # | 必须达成 | 验证方式 |
|---|---|---|
| 1 | OpenClaw 或 Web 创建任务后进入统一主链路 | 任务出现在 Inbox，状态从 intake 推进 |
| 2 | CEO 生成可审批计划 | 90 秒内有 plan / stage / owner / risk |
| 3 | Product 产出真实 PRD | `task_artifacts` 有 `prd`，内容 > 2000 字符 |
| 4 | UI/UX 产出真实设计稿 | 有 `ui_spec`，包含页面、组件、状态、截图或设计引用 |
| 5 | Architecture 产出可落地架构 | 有 API、数据模型、技术选型、风险方案 |
| 6 | Development 写入真实代码文件 | worktree 中有至少 5 个源码文件 |
| 7 | Development 默认调用 Claude Code | trace / job 里能看到 Claude Code 执行记录 |
| 8 | QA 真运行测试 | 有测试命令、输出、通过/失败结果 |
| 9 | Acceptance 真验收 | `reviewing` 输出 > 500 字符，含 APPROVED / REJECTED |
| 10 | DevOps 产出部署资产 | 有 Dockerfile / docker-compose / runbook / 回滚方案 |
| 11 | 8 Tab 都能看到真实产物 | 前端任务详情页人工检查 |
| 12 | 质量分真实回写 | `pipeline_stages.quality_score > 0` |
| 13 | 低质量能自动重跑或打回 | `retry_count > 0` 或 stage 被重置 |
| 14 | 失败能给业务语言 RCA | 失败卡显示“卡在哪、为什么、谁处理、下一步” |

禁止再用“接口 200”“页面能打开”“数据库有占位符”当完成标准。

---

## 2. 当前核心判断

`agent-hub` 不是空壳，后端已经有不少关键骨架：

- `AgentRuntime`：工具调用、记忆、自检、MCP 动态工具。
- `PipelineEngine`：阶段执行、技能注入、peer review、quality gate。
- `TOOL_REGISTRY`：文件、bash、git、测试、浏览器、代码库搜索、agent delegation。
- `TaskScheduler`：统一排队、并发控制、部分 Redis 队列持久化。
- `TaskArtifact`：任务级交付物体系已经有方向。

但最大问题仍然是：

> 能力分散，默认入口没有合成一条真实作战链路。

具体表现：

- `AgentChat.vue` 默认仍走前端轻工具链，不是后端 `AgentRuntime`。
- Pipeline 阶段必须确认是否全部走真实工具执行，而不是只写 markdown。
- Claude Code 已有 executor，但必须进入 development 默认主流程。
- Skills 不能只追加 prompt，必须作为 pre/post stage 执行单元。
- MCP 不能只在独立 Agent run 可用，Pipeline 也必须加载。
- Artifact 不能再有占位符，必须由 stage output / worktree / test result 自动回写。

---

## 3. 执行原则

### 3.1 主线唯一

所有入口都进入同一条任务主线：

```text
intake → plan_pending → approved → running → acceptance_pending → accepted/rejected → deployed/archived
```

Dashboard、AgentChat、Workflow、OpenClaw、Feishu、QQ 不允许各自跑半套流程。

### 3.2 任务第一，Agent 第二

Agent 不是主角，任务推进才是主角。  
Agent 卡片只用于解释“谁负责什么”，不能替代任务流。

### 3.3 每阶段必须有产物

每个阶段完成后必须同时写入：

- `PipelineStage.output`
- `TaskArtifact`
- 任务目录文件
- SSE / Trace
- 必要时 worktree 文件

### 3.4 每步必须可审计

每个阶段都要能回答：

- 用了哪个模型。
- 调了哪些工具。
- 产出了哪些文件。
- 质量分是多少。
- 谁审过。
- 为什么通过或打回。

---

## 4. 阶段职责与产物

| 阶段 | 负责 Agent | 必须产物 | 关键执行要求 |
|---|---|---|---|
| Intake | OpenClaw / Clarifier | `brief` | 识别需求、补齐上下文、判断是否需要 plan mode |
| Planning | CEO Agent | `plan`、`brief` | 拆阶段、定负责人、定风险、定验收口径 |
| Product | Product Agent | `prd` | 用户故事、范围、非目标、验收标准 |
| UI/UX | UI/UX Agent | `ui_spec`、截图/设计引用 | 页面、组件、状态、交互、设计 token |
| Architecture | CTO / Architect Agent | `architecture` | API、数据模型、模块边界、技术风险 |
| Development | Developer Agent + Claude Code | `code_link`、源码文件、commit 摘要 | 必须写入 worktree，不能只生成 markdown |
| Testing | QA Agent | `test_report`、测试日志 | 必须运行真实测试命令 |
| Acceptance | Acceptance Agent | `acceptance` | 读取全部产物，给 APPROVED / REJECTED |
| Deployment | DevOps Agent | `ops_runbook`、Dockerfile、部署日志 | 生成部署与回滚材料 |

---

## 5. 模型策略

### 5.1 当前可落地版本

优先用当前已有和最容易稳定运行的模型：

| 阶段 | 主模型 | 备用 |
|---|---|---|
| Clarifier / OpenClaw | `google/gemma-4-26b-a4b` | `glm-4-flash` |
| CEO / Planning | `qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled@q6_k` | `glm-4-plus` |
| Product | `google/gemma-4-26b-a4b` | DeepSeek / `glm-4-flash` |
| UI/UX | `google/gemma-4-26b-a4b` | Gemini / Qwen VL（后续） |
| Architecture | `qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled@q6_k` | DeepSeek-R1 / `glm-4-plus` |
| Development | Claude Code CLI | DeepSeek Coder / Qwen Coder / Gemma-4 |
| Testing | `google/gemma-4-26b-a4b` + bash/test tools | DeepSeek / `glm-4-flash` |
| Acceptance | `qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled@q6_k` | Claude Opus / Gemini Pro |
| Deployment | `google/gemma-4-26b-a4b` | DeepSeek / `glm-4-flash` |

### 5.2 质量优先版本

如果后续云模型配置齐全，推荐：

| 阶段 | 推荐主模型 | 备用/降级 |
|---|---|---|
| Clarifier | DeepSeek-V3 / Gemini Flash | GLM-4-Flash / Gemma-4 |
| CEO / Orchestrator | Claude Opus / Gemini Pro / Qwen reasoning | DeepSeek-R1 / GLM-4-Plus |
| Product | Claude Sonnet / DeepSeek-V3 / Gemini Pro | Qwen strong / GLM |
| UI/UX | Gemini Pro/Flash + 视觉能力 / Claude Sonnet | Qwen VL / GLM |
| Architecture | Claude Opus/Sonnet / Gemini Pro / Qwen reasoning | DeepSeek-R1 |
| Development | Claude Code + Claude Sonnet/Opus | DeepSeek Coder / Qwen Coder |
| Testing | Claude Sonnet / DeepSeek-V3 / Qwen strong | Gemma-4 / GLM-4-Flash |
| Acceptance | Claude Opus / Gemini Pro / Qwen reasoning | DeepSeek-R1 |
| DevOps | Claude Sonnet / DeepSeek-V3 / Qwen strong | GLM-4-Flash |

### 5.3 关键原则

开发阶段的主力不是普通 chat model，而是 Claude Code。  
普通模型可以写计划、解释代码、生成补丁草案，但真正落地必须进入 worktree。

---

## 6. 执行路线

### Phase 1：主入口统一

目标：所有入口都进入统一任务主线。

改造项：

- Dashboard CTA 调 OpenClaw intake。
- Web 手动任务、OpenClaw、Feishu、QQ 都走同一个 `clarify_or_create_task`。
- 禁止任务在前端 local fallback 中伪执行。
- 任务创建后必须显示在 Inbox。

验收：

```text
发一句“开发一个待办事项 Web App”
→ 任务进入 Inbox
→ 状态为 plan_pending 或 running
→ 有 task_id、source、owner、current_stage
```

### Phase 2：AgentChat 接后端 Runtime

目标：专家聊天不再是前端轻工具演示。

改造项：

- `AgentChat.vue` 使用 `runAgentStream()`。
- 显示 tool call、observation、mcp_tools_loaded、verification。
- 保留前端轻工具作为 demo/offline 模式，但必须显式标记。

验收：

```text
打开任意专家聊天
→ 发送“读取当前项目结构并给建议”
→ 后端产生 agent:tool-call 事件
→ UI 显示工具调用过程
```

### Phase 3：Development 接 Claude Code 主流程

目标：开发阶段写真实代码。

改造项：

- development stage 调用 `CodeGenAgent`。
- `CodeGenAgent` 默认调用 `executor_bridge.execute_claude_code()`。
- Claude Code 工作目录必须是任务 worktree。
- 生成后自动提取 commit/file summary 到 `code_link` artifact。

验收：

```text
development 完成后：
worktree 中有源码文件
TaskCodeTab 能看到文件树
executor job 有 Claude Code 输出
task_artifacts 有 code_link
```

### Phase 4：Testing 真执行

目标：测试阶段不再写“测试建议”，而是真运行测试。

改造项：

- QA Agent 绑定 `test_detect`、`test_execute`、`bash`。
- testing stage 必须执行测试命令。
- 测试失败时不能直接 done，要触发重试或打回 development。

验收：

```text
testing output 包含：
执行命令
通过数 / 失败数
错误摘要
下一步建议
```

### Phase 5：Acceptance / Deployment 补齐

目标：验收和运维不再空壳。

改造项：

- reviewing stage 必须读取所有前序 artifacts。
- Acceptance Agent 输出 `APPROVED` 或 `REJECTED REJECT_TO: <stage_id>`。
- deployment stage 生成 Dockerfile、docker-compose、runbook。
- reject 后自动重置目标阶段及后续阶段。

验收：

```text
reviewing output > 500 字符
deployment output > 1000 字符
worktree 中存在 Dockerfile 或 deploy/ 目录
REJECT_TO 能触发重跑
```

### Phase 6：Artifact 与 8 Tab 完整闭环

目标：用户肉眼可看所有产物。

改造项：

- 每阶段完成后自动写 `TaskArtifact`。
- 任务目录物化 Markdown 文件。
- `TaskArtifactTabs.vue` 默认显示真实内容。
- code tab 显示 worktree 文件、commit、diff、测试状态。

验收 SQL：

```sql
SELECT artifact_type, length(content)
FROM task_artifacts
WHERE task_id = '<task_id>'
ORDER BY artifact_type;
```

要求：核心 artifact 内容不能是占位符，平均长度 > 2000 字符。

### Phase 7：质量与失败闭环

目标：低质量不能混过去，失败能讲人话。

改造项：

- `verify_stage_output()` 的分数必须回写。
- `review_status` 必须回写。
- quality gate 不通过自动 retry。
- 失败时生成业务 RCA 卡。

验收：

```sql
SELECT stage_id, quality_score, verify_status, review_status, retry_count
FROM pipeline_stages
WHERE task_id = '<task_id>';
```

要求：

- 所有完成阶段 `quality_score > 0`。
- reviewing / acceptance 有 review 状态。
- 失败任务必须有 FailureCard。

---

## 7. 每日执行方式

每天只做一条主线，不做横向扩张。

### Day Loop

1. 选一个 Phase。
2. 写清楚当天唯一目标。
3. 改最短链路。
4. 跑一个真实任务。
5. 用 SQL + 文件系统 + 前端三方验证。
6. 失败就修这条链路，不开新战场。
7. 把结果记录到 issue 文档。

### 禁止事项

- 禁止只做 UI 不跑任务。
- 禁止只看 HTTP 200。
- 禁止用 mock artifact 冒充完成。
- 禁止新增页面掩盖主链路问题。
- 禁止 development 阶段只输出 markdown 代码块。
- 禁止 testing 阶段只写测试计划不运行测试。

---

## 8. 最小端到端验证任务

固定使用一个小任务反复验证，不要一开始做大系统：

```text
开发一个 Todo Web App：
- 支持新增、编辑、删除、完成任务
- 数据保存在本地 SQLite 或 JSON 文件
- 有基础前端页面
- 有 3 个自动测试
- 生成 Dockerfile
```

必须看到：

- PRD。
- UI 规范。
- 架构文档。
- 真实源码。
- 测试执行结果。
- 验收结论。
- 运维部署说明。
- 分享页或交付包。

---

## 9. 最终判断

`agent-hub` 下一步不是继续堆 Agent、技能、页面，而是把已有能力合成一条可执行、可验证、可恢复的交付链。

真正的最终态不是：

```text
很多 Agent 页面 + 很多工具入口 + 很多实验室
```

而是：

```text
一句话需求
→ AI 军团接单
→ 每个角色产出真实工件
→ 开发写真实代码
→ 测试真执行
→ 验收可打回
→ 运维可上线
→ 用户能看见完整交付包
```

这才是最终 AI-Agent。