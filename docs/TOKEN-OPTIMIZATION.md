# Agent Hub Token 消耗优化指南

> 针对 agent-hub 项目在开发中使用 Claude Code / AI 辅助编码时的 Token 节省实战指南。
> 最后更新：2026-04-13

---

## 目录

1. [Token 消耗的来源](#token-消耗的来源)
2. [六大省钱技巧](#六大省钱技巧)
3. [Agent Hub 特有优化](#agent-hub-特有优化)
4. [Pipeline LLM 调用优化](#pipeline-llm-调用优化)
5. [开发场景最佳实践](#开发场景最佳实践)
6. [成本参考数据](#成本参考数据)

---

## Token 消耗的来源

使用 Claude Code 或其他 AI 辅助编码工具时，Token 消耗主要来自以下环节：

| 来源 | 占比估算 | 说明 |
|------|----------|------|
| **MCP 服务器工具描述** | 15-25% | 每个 MCP 工具都包含详细文档，即使不使用也持续占用 context |
| **对话历史** | 20-35% | 每次交互的历史记录保留在 context 中，越长越贵 |
| **项目文件** | 15-25% | CLAUDE.md、SKILL.md 等配置文件随每次请求发送 |
| **代码文件内容** | 15-20% | AI 读取的源码文件，文件越大消耗越多 |
| **系统组件** | 10-15% | 系统提示词和内置工具（固定开销，无法优化） |

**直观理解：** agent-hub 项目有 ~36 个前端源文件和 ~20 个后端模块。如果 AI 读取 `PipelineTaskDetail.vue`（1041 行）一次就消耗约 4K tokens；而 `leadAgent.mjs`（400+ 行）约 2K tokens。一次完整的功能开发可能涉及读取 10+ 个文件，仅代码读取就消耗 20K+ tokens。

---

## 六大省钱技巧

### 1. 关闭不必要的 MCP Server

**问题：** 每个 MCP Server 的工具都有大量文本描述。agent-hub 开发场景中可能加载了 chrome-devtools、数据库工具等不相关的 MCP 服务器。

**解决方案：**

```
开发后端 pipeline？→ 关闭 browser/chrome-devtools MCP
纯前端 UI 调整？  → 关闭 database/postgres MCP
写文档/README？   → 关闭大部分 MCP，只保留 filesystem
```

**操作方式（Cursor）：**

1. 打开设置 → MCP Servers
2. 禁用当前不需要的服务器
3. 需要时再重新启用

**预计节省：** 每次请求减少 5-20K tokens（取决于已安装的 MCP 数量）

### 2. 养成 /clear 习惯

**问题：** 对话历史不断累积。在 agent-hub 中完成一个 pipeline 功能后继续讨论前端 UI，之前的后端代码和调试记录仍占用 context。

**解决方案：** 把 `/clear` 当成 `git commit` — 完成一个功能点就清理一次。

**推荐时机：**

| 场景 | 操作 |
|------|------|
| 完成 `leadAgent.mjs` 修改，开始改 `SubtaskCard.vue` | `/clear` |
| 调试完后端 500 错误，开始新功能 | `/clear` |
| Pipeline 全链路测试通过，开始写文档 | `/clear` |
| 对话感觉变慢、回复质量下降 | `/clear` |

**预计节省：** 减少 30-50% 的 Token 消耗

### 3. 主动使用 /compact 压缩历史

**问题：** 修改 `PipelineTaskDetail.vue`（1000+ 行）时需要保持上下文连续，但不想完全清除前面的讨论。

**解决方案：**

```
开始任务
   │
   ├── 研究阶段（读了 10 个文件）
   │
   ├── /compact  ← 压缩研究阶段，保留关键信息
   │
   ├── 实现阶段（修改了 5 个文件）
   │
   ├── /compact  ← 压缩实现细节，保留修改清单
   │
   └── 验证阶段
```

**预计节省：** 长对话中减少 20-40% 的 Token

### 4. 使用 /context 监控消耗

**问题：** 不清楚 Token 花在哪里，无法针对性优化。

**推荐频率：**

| 时机 | 操作 |
|------|------|
| 每个开发阶段开始时 | `/context` 检查基准线 |
| 感觉响应变慢时 | `/context` 找原因 |
| 读取大文件后 | `/context` 确认增量 |

**关注指标：**

- `MCP tools` 占比 → 是否需要关闭不用的 MCP
- `Conversation history` 大小 → 是否需要 `/clear` 或 `/compact`
- `Project files` 占比 → CLAUDE.md / SKILL.md 是否过长

### 5. 精简项目配置文件

**问题：** 项目的 AI 配置文件（CLAUDE.md、SKILL.md 等）随每次请求发送。agent-hub 有 3 个内置 SKILL.md，每个约 50-100 行。

**优化原则：**

```markdown
# 优化前（冗长）
这是一个使用 Vue 3 和 TypeScript 构建的现代化 Web 应用。
我们使用了以下技术：
1. Vue 3.4 - 用于构建用户界面
2. TypeScript 5.4 - 提供类型安全
3. Vite 5.2 - 作为构建工具
...（50行技术栈说明）

# 优化后（精炼）
Vue 3 + TS 5 + Vite 5 + Express + SQLite/PG
前端组件用 <script setup lang="ts">，后端用 .mjs ESM
```

**agent-hub 具体建议：**

| 文件 | 建议 |
|------|------|
| SKILL.md | 内容限制在 30 行以内，只保留核心规则 |
| CLAUDE.md（如创建） | 不超过 50 行，只写项目约定和关键路径 |
| README.md | 已有的保持，不需要进一步精简（不随 AI 请求发送） |

### 6. 保持代码文件精简

**问题：** AI 读取代码的最小单元是文件。agent-hub 中最大的文件 `PipelineTaskDetail.vue` 有 1041 行，一次读取消耗约 4K tokens。

**当前 agent-hub 大文件：**

| 文件 | 行数 | 建议 |
|------|------|------|
| `src/views/PipelineTaskDetail.vue` | 1043 | 考虑拆分为子组件：StagePanel、EventLog、ArtifactViewer |
| `server/index.mjs` | 817 | 考虑拆分：认证中间件、LLM 路由、会话路由 |
| `src/views/PipelineDashboard.vue` | 499 | 可以接受，但接近上限 |
| `server/pipeline/leadAgent.mjs` | 491 | 接近上限，execute 逻辑可拆分 |

**拆分原则：**

- 单个文件超过 500 行 → 考虑拆分
- 单个 Vue 组件超过 300 行 `<script>` → 提取组合函数
- 后端路由文件超过 200 行 → 按功能拆分为子路由

```
# 拆分示例：PipelineTaskDetail.vue → 组合函数
src/
  views/PipelineTaskDetail.vue       # 仅模板 + 组装
  composables/
    usePipelineTask.ts               # 任务加载和状态
    usePipelineSSE.ts                # SSE 事件订阅
    useSubtaskTracking.ts            # 子任务追踪逻辑
```

---

## Agent Hub 特有优化

### Pipeline Smart Run 的 Token 消耗

一次完整的 `smart-run` 涉及多次 LLM 调用：

| 阶段 | LLM 调用 | 预估 Token |
|------|----------|-----------|
| Lead Agent 分析 | 1 次 | 2-4K input + 1-2K output |
| PM 子任务 | 1 次 | 1-2K input + 2-3K output |
| Dev 子任务 | 1 次 | 2-3K input + 3-5K output |
| QA 子任务 | 1 次 | 2-3K input + 2-3K output |
| Review（post-build） | 1 次 | 3-5K input + 1-2K output |
| **合计** | **5 次** | **~25-40K** |

**优化策略：**

1. **选择合适的模型**：简单任务用便宜的模型（如 DeepSeek），复杂任务才用 GPT-4
2. **Skills 按需启用**：不需要 PRD 专家时关闭它，减少 system prompt 长度
3. **合理设置 maxTokens**：在 `llmBridge.mjs` 中为不同阶段设置不同的 `maxTokens`

### Skills 系统的 Token 影响

每个启用的 SKILL.md 内容都会注入 Lead Agent 的 system prompt：

```
3 个 skills 启用 = 系统提示增加 ~300-500 tokens/次
× 5 次 LLM 调用
= 每次 pipeline 额外 1.5K-2.5K tokens
```

**建议：** 只启用当前任务真正需要的 skills。

```bash
# 通过 API 关闭不需要的技能
curl -X PUT http://127.0.0.1:8787/pipeline/skills/prd-expert \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

### 中间件 Token 追踪

`middleware.mjs` 内置的 `token-usage` 中间件已经在追踪每次 LLM 调用的 Token 消耗。通过 SSE 事件 `middleware:token-usage` 和 API `GET /pipeline/middleware/stats` 获取统计数据。

利用这些数据识别 Token 热点：

```bash
# 查看中间件统计
curl -s http://127.0.0.1:8787/pipeline/middleware/stats \
  -H "Authorization: Bearer $KEY" | python3 -m json.tool
```

---

## Pipeline LLM 调用优化

### 针对不同阶段选择模型

不同阶段对模型能力的要求不同：

| 阶段 | 要求 | 推荐模型 | 理由 |
|------|------|----------|------|
| Lead Agent 分析 | 理解力强 | GPT-4 / DeepSeek-V3 | 需要准确分解任务 |
| PM (PRD) | 结构化输出 | DeepSeek-chat | 模板化，便宜模型够用 |
| Dev (架构) | 技术深度 | GPT-4 / DeepSeek-V3 | 需要高质量技术方案 |
| QA (测试) | 全面性 | DeepSeek-chat | 测试方案模板化 |
| Review | 综合判断 | DeepSeek-chat | 打分+结论，格式化够用 |

**实现方式：** 在 `leadAgent.mjs` 中按 role 设置不同的模型（需扩展 `llmBridge.mjs` 支持 per-call 模型覆盖）。

### Prompt 长度优化

**Lead Agent System Prompt：** 当前约 800+ tokens。优化建议：

```javascript
// 优化前：详细描述每个角色
// "product-manager: 负责整理需求、定义 PRD、确定验收标准..."
// "developer: 负责技术方案设计、API 定义、数据库设计..."

// 优化后：简洁角色表
// 角色: PM(PRD/验收) | Dev(架构/API) | QA(测试/回归) | Exec(实现)
```

**子任务 Prompt：** 避免传递所有前置任务的完整输出，只传关键摘要。

### Claude Code Token 消耗

Claude Code 执行 `building` 阶段时的 Token 消耗取决于：

| 因素 | 影响 | 优化方式 |
|------|------|---------|
| PRD 长度 | 输入 tokens | 控制 PRD 在 2000 字以内 |
| 架构方案长度 | 输入 tokens | 只传关键设计点，非完整方案 |
| 执行范围 | Claude Code 内部消耗 | 明确限定修改的文件范围 |
| allowedTools | 可用工具数 | 只开放必要的工具集 |

**优化 `buildExecutionPrompt()`：**

```javascript
// 当前：传递完整 PRD + 完整架构方案
// 优化：只传摘要和关键约束

function buildExecutionPrompt(task) {
  const parts = [`## 任务: ${task.title}\n`]

  const prd = task.stages.find(s => s.id === 'planning')?.output
  if (prd) {
    // 只取前 1000 字符作为关键需求
    parts.push(`### 核心需求\n${prd.slice(0, 1000)}\n`)
  }

  const arch = task.stages.find(s => s.id === 'architecture')?.output
  if (arch) {
    // 只取前 1500 字符作为技术要点
    parts.push(`### 技术要点\n${arch.slice(0, 1500)}\n`)
  }

  return parts.join('\n')
}
```

---

## 开发场景最佳实践

### 场景 1：修改单个组件

```
目标：修改 SubtaskCard.vue 的样式

高效方式：
1. 直接告诉 AI 文件路径和具体修改
2. 不需要 AI 搜索整个项目
3. 改完后 /clear

预计 Token：5-8K（仅读取目标文件 + 修改）
```

### 场景 2：新增 Pipeline 功能

```
目标：给 pipeline 添加新的阶段

高效方式：
1. 先 /context 确认基准线
2. 让 AI 只读取 taskModel.mjs + pipelineRouter.mjs + leadAgent.mjs
3. 不读无关文件（如 gateway/、styles/）
4. 实现完成后 /compact
5. 验证后 /clear

预计 Token：20-30K
低效方式：让 AI 从头理解整个项目 → 50-80K
```

### 场景 3：全链路调试

```
目标：Smart Pipeline 卡在 building 阶段

高效方式：
1. 直接指向相关文件：leadAgent.mjs、executorBridge.mjs
2. 贴上具体错误日志（而不是让 AI 自己找）
3. 聚焦问题段落，不读整个文件
4. 修复后 /clear

预计 Token：10-15K
低效方式：让 AI 从头排查整个 pipeline → 40-60K
```

### 场景 4：写文档 / README

```
目标：更新 README.md

高效方式：
1. 关闭所有不需要的 MCP
2. 只读取 README.md + package.json
3. 提供明确的修改指示

预计 Token：3-5K
```

### 通用原则

| 原则 | 说明 |
|------|------|
| **最小读取** | 只让 AI 读取确实需要的文件，而非「先看看整体结构」 |
| **精确指令** | 「修改 leadAgent.mjs 第 242 行的函数」比「帮我改下 pipeline」节省 80% tokens |
| **分批处理** | 5 个小任务分 5 次对话，每次 /clear，比 1 个长对话便宜 |
| **提供上下文** | 把错误日志、截图贴给 AI，比让 AI 自己执行命令查找要省 |
| **善用 Grep** | 让 AI 用 Grep 精确搜索，而非递归读取目录 |

---

## 成本参考数据

### Claude Code 实测数据

基于 200 小时实测（合理管理 MCP + /clear 习惯）：

| 指标 | 数值 |
|------|------|
| 平均成本 | 1500 配额 ≈ 2 小时高强度开发 |
| 日常开发 | 10 小时/天 ≈ 7500 配额 |
| 单个功能（中等复杂度） | 500-1500 配额 |
| Bug 修复（已知位置） | 100-300 配额 |
| 全链路 Pipeline 开发 | 2000-3000 配额 |

### 不同 LLM 的 Pipeline 成本对比

以一次完整 `smart-run`（5 次 LLM 调用，约 30K tokens）为例：

| 模型 | 输入单价 (/M tokens) | 输出单价 (/M tokens) | 单次 Pipeline 预估 |
|------|---------------------|---------------------|-------------------|
| DeepSeek-V3 | $0.27 | $1.10 | ~$0.02 |
| GPT-4o | $2.50 | $10.00 | ~$0.15 |
| GPT-4o-mini | $0.15 | $0.60 | ~$0.01 |
| Claude Sonnet | $3.00 | $15.00 | ~$0.20 |
| Ollama (本地) | 免费 | 免费 | $0（但慢） |

**推荐策略：** 开发调试阶段用 DeepSeek / Ollama 省钱，正式 Pipeline 用 GPT-4o 保质量。

### 优化前后效果对比

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 单日 Token 消耗 | ~150K | ~60K | **-60%** |
| 同预算可用时间 | 4 小时 | 10 小时 | **+150%** |
| 平均响应速度 | 5-8 秒 | 2-4 秒 | **+50%** |
| 回复质量（主观） | 7/10 | 9/10 | context 更聚焦 |

---

## 速查清单

每次开发前快速过一遍：

- [ ] 关闭不需要的 MCP Server
- [ ] 确认 CLAUDE.md（如有）不超过 50 行
- [ ] 只启用本次任务需要的 Skills
- [ ] `/context` 检查当前 Token 基准线
- [ ] 准备好要修改的文件路径清单（减少 AI 搜索）

每完成一个功能点：

- [ ] `/clear` 清除历史
- [ ] 或 `/compact` 如果还需要上下文连续

长对话中（>30 分钟）：

- [ ] `/context` 检查消耗
- [ ] `/compact` 压缩历史
- [ ] 考虑是否该 `/clear` 重新开始

---

## 总结

Token 管理不是限制创造力，而是帮助更高效地使用 AI 辅助开发。核心习惯三件套：

1. **每完成一个任务就 `/clear`**
2. **定期 `/context` 检查**
3. **关闭不用的 MCP**

这三个习惯就能帮你节省 50% 以上的 Token 消耗，同时保持更清晰的对话上下文和更高质量的 AI 回复。
