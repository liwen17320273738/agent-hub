# Agent Hub 开发指南

> 适用于所有参与 agent-hub 开发的工程师（含 AI 辅助编码场景）。
> 最后更新：2026-04-13

---

## 目录

1. [项目概览](#项目概览)
2. [技术栈](#技术栈)
3. [环境搭建](#环境搭建)
4. [目录结构](#目录结构)
5. [运行模式](#运行模式)
6. [核心架构](#核心架构)
7. [开发工作流程](#开发工作流程)
8. [编码标准](#编码标准)
9. [质量红线](#质量红线)
10. [场景化工作流程](#场景化工作流程)
11. [复杂任务处理](#复杂任务处理)
12. [部署方式](#部署方式)
13. [常见问题](#常见问题)

---

## 项目概览

Agent Hub 是一个浏览器端的「AI 团队」协作平台。用户选择角色（市场、销售、技术支持等），像与顾问交谈一样与 AI 对话，并在本地保留对话历史。

企业模式下，它进一步演化为 **AI 军团流水线**（AI Legion Pipeline）：

- **Lead Agent** 智能分析需求、动态分解子任务
- **Subagent** 并行执行（产品经理 → 开发 → QA → 评审）
- **Claude Code** 在终端中执行实际开发任务
- **Skills 系统** 为 Agent 注入领域专业知识
- **中间件管道** 提供护栏、Token 追踪、循环检测

---

## 技术栈

### 前端

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue 3 | ^3.4 | UI 框架 |
| Vue Router | ^4.3 | Hash 路由 (`/#/...`) |
| Pinia | ^2.1 | 状态管理 |
| Element Plus | ^2.9 | UI 组件库 |
| Vite | ^5.2 | 构建工具 / 开发服务器 |
| TypeScript | ^5.4 | 类型系统 (`strict: true`) |
| markdown-it | ^14.1 | Markdown 渲染 |
| highlight.js | ^11.10 | 代码高亮 |

### 后端

| 技术 | 版本 | 用途 |
|------|------|------|
| Node.js | ≥18 (推荐 22.5+) | 运行时 |
| Express | ^4.21 | HTTP 框架 |
| SQLite (`node:sqlite`) | Node 内置 | 默认数据库 (需 Node 22.5+) |
| PostgreSQL (`pg`) | ^8.13 | 生产数据库 |
| bcryptjs | ^3.0 | 密码加密 |
| cookie-session | ^2.1 | 会话管理 |
| dotenv | ^16.4 | 环境变量 |

### 工具链

| 工具 | 用途 |
|------|------|
| pnpm 10.12 | 包管理器 |
| concurrently | 并行启动前后端 |
| Docker / docker-compose | 容器化部署 |
| Claude Code CLI | AI 开发执行器 |
| Ollama (可选) | 本地 LLM 推理 |

---

## 环境搭建

### 前置条件

```bash
# Node.js ≥ 18（使用 SQLite 需 ≥ 22.5）
node --version

# pnpm
corepack enable
corepack prepare pnpm@10.12.1 --activate

# Claude Code（用于 building 阶段）
npm install -g @anthropic-ai/claude-code
claude --version
```

### 安装依赖

```bash
git clone <repo-url> agent-hub
cd agent-hub
pnpm install
```

### 配置环境变量

```bash
# 前端配置
cp .env.example .env

# 后端配置（企业模式必需）
cp server/.env.example .env
```

**关键变量说明：**

| 变量 | 必填 | 说明 |
|------|------|------|
| `LLM_API_URL` | 是 | LLM Chat Completions 端点（如 `https://api.deepseek.com/v1/chat/completions`） |
| `LLM_API_KEY` | 是 | LLM API 密钥 |
| `LLM_MODEL` | 是 | 模型名（如 `deepseek-chat`、`gemma4:26b`） |
| `SESSION_SECRET` | 是 | 会话密钥（≥32 字符随机串） |
| `ADMIN_EMAIL` | 是 | 初始管理员邮箱 |
| `ADMIN_PASSWORD` | 是 | 初始管理员密码（生产环境必须修改） |
| `DATABASE_PATH` | 否 | SQLite 路径（默认 `./data/agent-hub.sqlite`） |
| `DATABASE_URL` | 否 | PostgreSQL 连接串（设置后优先于 SQLite） |
| `PIPELINE_API_KEY` | 否 | Pipeline API 密钥（便于脚本/自动化调用） |
| `CLAUDE_PATH` | 否 | Claude Code 二进制路径（默认 `claude`） |
| `VITE_ENTERPRISE` | 否 | 设为 `true` 启用企业模式 |

**本地使用 Ollama：**

```bash
# .env
LLM_API_URL=http://127.0.0.1:11434/v1/chat/completions
LLM_API_KEY=ollama
LLM_MODEL=gemma4:26b
```

---

## 目录结构

```
agent-hub/
├── src/                          # 前端源码 (Vue 3 + TypeScript)
│   ├── views/                    # 页面组件
│   │   ├── Dashboard.vue         # 首页仪表盘
│   │   ├── AgentChat.vue         # Agent 对话
│   │   ├── PipelineDashboard.vue # 流水线管控台
│   │   ├── PipelineTaskDetail.vue# 任务详情（含子任务追踪）
│   │   ├── SkillsView.vue        # 技能管理
│   │   ├── Settings.vue          # 设置
│   │   └── ModelLab.vue          # 模型实验室
│   ├── components/               # 通用组件
│   │   ├── SubtaskCard.vue       # 子任务卡片（实时状态）
│   │   ├── SkillsPanel.vue       # 技能面板
│   │   └── ChatMessage.vue       # 消息气泡
│   ├── services/                 # API 和业务逻辑
│   │   ├── pipelineApi.ts        # 流水线 API 客户端
│   │   ├── llm.ts                # LLM 调用封装
│   │   └── enterpriseApi.ts      # 企业模式 API
│   ├── stores/                   # Pinia 状态管理
│   │   ├── pipeline.ts           # 流水线状态
│   │   ├── settings.ts           # 设置状态
│   │   └── auth.ts               # 认证状态
│   ├── agents/                   # Agent 注册和类型定义
│   ├── router/                   # 路由配置 (Hash History)
│   └── styles/                   # 全局样式
│
├── server/                       # 后端源码 (Express + ESM)
│   ├── index.mjs                 # 入口：Express app、认证、路由挂载
│   ├── db.mjs                    # SQLite Schema 定义
│   ├── store.mjs                 # 数据访问层 (SQLite/PostgreSQL)
│   ├── events.mjs                # SSE 事件总线
│   ├── pipeline/                 # AI 军团流水线
│   │   ├── pipelineRouter.mjs    # REST API 路由
│   │   ├── taskModel.mjs         # 任务模型和阶段定义
│   │   ├── taskStore.mjs         # 任务持久化
│   │   ├── orchestrator.mjs      # 经典固定阶段编排器
│   │   ├── leadAgent.mjs         # Lead Agent 智能编排器
│   │   ├── llmBridge.mjs         # 统一 LLM 调用层
│   │   ├── middleware.mjs        # 中间件管道
│   │   └── skills.mjs            # 技能加载器
│   ├── executor/                 # Claude Code 执行器
│   │   ├── executorBridge.mjs    # CLI 进程管理
│   │   └── executorRouter.mjs    # 执行器 API
│   └── gateway/                  # 外部接入网关
│       ├── openclawRouter.mjs    # OpenClaw 意图解析
│       ├── feishuWebhook.mjs     # 飞书机器人
│       └── qqWebhook.mjs         # QQ 机器人
│
├── skills/                       # 技能包
│   ├── public/                   # 内置技能
│   │   ├── prd-expert/SKILL.md   # PRD 专家
│   │   ├── code-review/SKILL.md  # 代码审查
│   │   └── test-strategy/SKILL.md# 测试策略
│   └── custom/                   # 自定义技能
│
├── docs/                         # 文档
│   ├── DEVELOPMENT.md            # 本文件
│   ├── TOKEN-OPTIMIZATION.md     # Token 优化指南
│   └── architecture/             # 架构文档
│
├── scripts/                      # 辅助脚本
├── public/                       # 静态资源
├── package.json
├── vite.config.ts
├── tsconfig.json
├── Dockerfile
└── docker-compose.yml
```

---

## 运行模式

### 静态模式（纯前端）

API 密钥存储在浏览器 localStorage，适合个人使用。

```bash
pnpm dev          # 启动 Vite 开发服务器，端口 5200
pnpm build        # 构建静态文件到 dist/
pnpm preview      # 预览构建结果
```

### 企业模式（前端 + 后端）

API 密钥存在服务端，支持多用户、数据库持久化、AI 军团流水线。

```bash
pnpm dev:enterprise   # 并行启动 Vite (5200) + Express (8787)
```

**API 代理关系：** Vite 将 `/api/hub/*` 代理到 `http://127.0.0.1:8787/*`（前缀剥离）。

### 生产部署

```bash
pnpm build
pnpm start        # Express 同时服务 dist/ 和 API，端口 8787
```

---

## 核心架构

### AI 军团流水线（Smart Pipeline）

```
用户需求
    │
    ▼
┌──────────────┐     ┌──────────────┐
│  Gateway     │────▶│  Lead Agent  │  动态分析、分解任务
│  (飞书/QQ/   │     │  (智能编排)   │
│   OpenClaw)  │     └──────┬───────┘
└──────────────┘            │
                            ▼
              ┌─────────────────────────┐
              │  Subtask Execution      │
              │  ┌─────┐ ┌─────┐ ┌───┐ │  并行执行
              │  │ PM  │ │ Dev │ │ QA│ │
              │  └──┬──┘ └──┬──┘ └─┬─┘ │
              └─────┼───────┼──────┼───┘
                    │       │      │
                    ▼       ▼      ▼
              ┌─────────────────────────┐
              │  Building Stage         │
              │  (Claude Code CLI)      │  终端执行开发
              └─────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │  Review & Delivery      │
              │  (测试验证 + 验收评审)     │
              └─────────────────────────┘
```

### 流水线阶段

| 阶段 | ID | 角色 | 说明 |
|------|----|------|------|
| 需求接入 | `intake` | OpenClaw | 解析意图，结构化需求 |
| PRD 定义 | `planning` | Product Manager | 整理需求、定义范围和验收标准 |
| 技术方案 | `architecture` | Developer | 输出技术方案和实现路径 |
| 开发实现 | `building` | Executor (Claude Code) | 在终端执行开发任务 |
| 质量验证 | `testing` | QA Lead | 功能验证、回归测试 |
| 验收评审 | `reviewing` | Orchestrator | 审查所有产出，给出结论 |
| 完成 | `done` | — | 任务完成 |

### 两种运行模式

| 模式 | 入口 | 特点 |
|------|------|------|
| **经典模式** `auto-run` | `orchestrator.mjs` → `runFullPipeline()` | 固定顺序、逐阶段执行 |
| **智能模式** `smart-run` | `leadAgent.mjs` → `runSmartPipeline()` | Lead Agent 动态分解、并行子任务、Claude Code 集成 |

### 中间件管道

所有 LLM 调用通过 `runMiddlewarePipeline()` 执行，支持以下中间件：

| 中间件 | 功能 |
|--------|------|
| `token-usage` | 追踪 Token 消耗，发送 SSE 事件 |
| `guardrail` | 策略拦截（如 executor 角色需 `ALLOW_EXECUTOR=1`） |
| `loop-detection` | 检测重复调用，防止死循环 |
| `error-formatting` | 格式化 LLM 错误（连接拒绝、认证失败、限流） |

### 技能系统（Skills）

技能通过 `SKILL.md` 文件定义，结构：

```yaml
---
name: code-review
description: 代码审查专家
enabled: true
license: MIT
---

# 代码审查框架

审查维度：
1. 功能正确性
2. 安全性
3. 性能
...
```

- 放入 `skills/public/` 或 `skills/custom/` 目录
- 通过 API `GET /pipeline/skills` 查看、`PUT /pipeline/skills/:name` 切换启用
- Lead Agent 自动将已启用技能注入系统提示

### SSE 实时事件

前端通过 `GET /pipeline/events` (SSE) 订阅以下事件：

| 事件 | 说明 |
|------|------|
| `pipeline:smart-start` | 智能流水线启动 |
| `lead-agent:analyzing` | Lead Agent 分析中 |
| `lead-agent:plan-ready` | 任务分解完成 |
| `subtask:start` | 子任务启动 |
| `subtask:completed` | 子任务完成 |
| `subtask:failed` | 子任务失败 |
| `executor:started` | Claude Code 启动 |
| `executor:log` | Claude Code 实时日志 |
| `executor:completed` | Claude Code 完成 |
| `task:stage-advanced` | 阶段推进 |
| `pipeline:smart-completed` | 智能流水线完成 |

---

## 开发工作流程

> **重要：每个任务必须遵循此流程，不可跳过任何阶段。**

### 1. 研究阶段（RESEARCH）

在开始任何任务前，必须先执行：

- [ ] 检查现有代码库中的类似实现
- [ ] 使用 Glob/Grep 搜索相关代码
- [ ] 理解项目架构和依赖关系
- [ ] 阅读相关文件的注释和文档

**不确定时联网搜索：**

- 新技术/框架的最佳实践
- 特定库的最新 API 文档
- 错误消息的解决方案

### 2. 计划阶段（PLAN）

研究完成后，必须输出：

- **文件清单**：要修改/创建的文件列表
- **实现方案**：关键步骤和技术选型
- **风险识别**：潜在问题和边缘情况
- **待确认问题**：需要用户澄清的问题

> **重要：获得用户确认后再开始编码。**

### 3. 实现阶段（IMPLEMENT）

获得确认后，按照计划执行：

- [ ] 遵循项目现有代码风格
- [ ] 完整的错误处理（绝不跳过）
- [ ] 编写时同步添加测试
- [ ] 运行 linter/formatter/type-checker

**完成标准：**

- [ ] Linter 零警告零错误
- [ ] 所有测试通过
- [ ] 类型检查通过
- [ ] 代码已格式化

---

## 编码标准

### TypeScript（前端 `src/`）

**命名规范：**

| 类型 | 规则 | 示例 |
|------|------|------|
| 文件 | kebab-case / PascalCase(.vue) | `pipeline-api.ts`, `SubtaskCard.vue` |
| 变量/函数 | camelCase | `fetchSkills()`, `taskId` |
| 类/接口/类型 | PascalCase | `PipelineTask`, `SubtaskInfo` |
| 常量 | SCREAMING_SNAKE_CASE | `MAX_RETRY_COUNT` |
| 布尔值 | is/has/can/should 前缀 | `isLoading`, `hasError` |

**函数规范：**

- 单个函数不超过 30 行
- 参数不超过 4 个，超过使用对象参数
- 必须声明返回类型
- 一个函数只做一件事

**错误处理：**

```typescript
// 正确
try {
  const data = await fetchData()
} catch (error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  console.error('[fetchData]', message)
  throw error
}

// 错误：空 catch、any 类型
try { await fetchData() } catch (e: any) {}
```

**导入顺序：**

```typescript
// 1. 外部库
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'

// 2. 内部模块（@/ 别名）
import { fetchSkills } from '@/services/pipelineApi'
import type { Skill } from '@/services/pipelineApi'

// 3. 相对路径
import SubtaskCard from '../components/SubtaskCard.vue'
```

### JavaScript/ESM（后端 `server/`）

后端使用 `.mjs` (ES Modules)，风格与 TypeScript 保持一致：

- 使用 `const`/`let`，禁用 `var`
- 函数优先使用箭头函数或 `function` 声明
- 错误处理必须捕获具体异常
- 异步操作必须使用 `async/await`

```javascript
// 正确：具体异常处理 + 日志
export async function getTask(taskId) {
  try {
    return await store.getTask(taskId)
  } catch (error) {
    console.error(`[getTask] failed for ${taskId}:`, error.message)
    return null
  }
}

// 错误：静默吞异常
export async function getTask(taskId) {
  try { return await store.getTask(taskId) } catch {}
}
```

### Vue 组件

```vue
<script setup lang="ts">
// 1. 外部导入
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'

// 2. 类型导入
import type { PipelineTask } from '@/agents/types'

// 3. Props / Emits
const props = defineProps<{
  taskId: string
  status: 'pending' | 'running' | 'done' | 'failed'
}>()

const emit = defineEmits<{
  (e: 'update', task: PipelineTask): void
}>()

// 4. 响应式状态
const loading = ref(false)
const data = ref<PipelineTask | null>(null)

// 5. 计算属性
const isComplete = computed(() => data.value?.status === 'done')

// 6. 方法
async function loadData(): Promise<void> {
  loading.value = true
  try {
    data.value = await fetchTask(props.taskId)
  } catch (error: unknown) {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

// 7. 生命周期
onMounted(loadData)
</script>
```

---

## 质量红线

> **以下规则是绝对底线，没有任何例外情况。**

### 提交前强制检查

| 检查项 | 命令 | 标准 |
|--------|------|------|
| 类型检查 | `npx vue-tsc --noEmit` | 零错误 |
| 构建验证 | `pnpm build` | 构建成功 |
| 测试 | `pnpm test:pipeline` | 所有通过 |

### 绝对禁止清单

**代码质量：**

- 绝不提交未通过测试的代码
- 绝不使用 TODO/FIXME 作为最终代码
- 绝不跳过错误处理
- 绝不吞掉异常（空 catch 块）
- 绝不使用魔法数字（提取为命名常量）

**类型安全：**

- 绝不使用 `any` 类型（用 `unknown` 替代）
- 绝不使用 `@ts-ignore`
- 绝不禁用 ESLint 规则

**安全相关：**

- 绝不硬编码密钥/凭证（使用环境变量）
- 绝不在日志中输出敏感信息
- 绝不跳过输入验证

### 违反红线的处理

1. 必须立即修复
2. 不能使用任何方式绕过
3. 不能以「临时方案」为由例外

---

## 场景化工作流程

### Bug 修复

```
1. RESEARCH ─→ 复现问题 → 定位根因 → 检查相关代码
2. PLAN    ─→ 说明根因 → 修复方案 → 影响范围
3. IMPLEMENT → 最小化改动 → 添加回归测试 → 验证修复
```

### 新功能

```
1. RESEARCH ─→ 理解需求 → 搜索复用点 → 确认技术栈
2. PLAN    ─→ 模块设计 → 接口定义 → 测试策略
3. IMPLEMENT → 渐进开发 → 同步测试 → 更新文档
```

### 重构

```
1. RESEARCH ─→ 分析现状 → 识别问题 → 评估影响
2. PLAN    ─→ 重构方案 → 分步计划 → 回滚预案
3. IMPLEMENT → 小步迭代 → 保持测试通过 → 及时提交
```

---

## 复杂任务处理

对于以下类型的任务，在计划阶段需要进行深度思考：

- 涉及多个模块的架构变更
- 新技术/框架的引入
- 性能优化方案
- 数据库 Schema 设计

**深度思考要求：**

1. 列出至少 2-3 种可行方案
2. 分析每种方案的优缺点
3. 说明推荐方案的理由
4. 识别潜在的技术债务

---

## 部署方式

### GitHub Pages（静态模式）

推送到 `main` 分支，GitHub Actions 自动构建并部署。

```bash
# .github/workflows/deploy-github-pages.yml 已配置
# 用户站点仓库需在 Actions Variables 设 VITE_BASE_PATH=/
```

### Docker（企业模式 + PostgreSQL）

```bash
# 修改环境变量
export SESSION_SECRET="your-random-secret-32-chars-min"
export ADMIN_EMAIL="admin@yourdomain.com"
export ADMIN_PASSWORD="strong-password"
export LLM_API_URL="https://api.deepseek.com/v1/chat/completions"
export LLM_API_KEY="sk-xxx"

# 启动
docker compose up --build -d

# 访问 http://localhost:8787
```

**注意事项：**

- Dockerfile 使用多阶段构建（builder → runtime）
- 生产镜像不包含 `skills/` 目录，需手动挂载或在 Dockerfile 中添加 `COPY skills ./skills`
- Node 22 slim 镜像已内置 SQLite 支持，但 docker-compose 默认使用 PostgreSQL

### 手动部署

```bash
pnpm build
# 配置 .env 中的所有必需变量
NODE_ENV=production pnpm start
```

---

## 常见问题

### Q: 为什么 `node:sqlite` 报错？

需要 Node.js ≥ 22.5。升级 Node 或改用 PostgreSQL（设置 `DATABASE_URL`）。

### Q: Vite 代理 `/api/hub` 返回 HTML？

确认后端 Express 在 8787 端口运行。直接测试后端：`curl http://127.0.0.1:8787/pipeline/health`。

### Q: Claude Code 执行超时？

默认超时 15 分钟。检查：

1. Claude Code CLI 是否安装：`claude --version`
2. 网络是否通畅（Claude Code 需要连接 Anthropic API）
3. 任务是否过于复杂（考虑拆分）

### Q: Smart Pipeline 子任务执行缓慢？

本地 Ollama 模型较慢，Lead Agent 分解 + 多个子任务 LLM 调用串行执行。建议：

1. 使用更快的远程 API（DeepSeek / OpenAI）
2. 或使用更小的本地模型
3. 检查 Ollama 状态：`curl http://127.0.0.1:11434/api/ps`

### Q: Pipeline API 返回 401 "未登录"？

Pipeline 路由需要认证。选择一种方式：

```bash
# 方式 1: 在 .env 设置 API Key
PIPELINE_API_KEY=your-key

# 请求时携带
curl -H "Authorization: Bearer your-key" http://127.0.0.1:8787/pipeline/tasks

# 方式 2: 先登录获取 session cookie
curl -c cookies.txt -X POST http://127.0.0.1:8787/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"changeme"}'
```

### Q: 如何添加自定义技能？

在 `skills/custom/` 下创建目录和 `SKILL.md`：

```bash
mkdir -p skills/custom/my-skill
cat > skills/custom/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: 自定义技能描述
enabled: true
---

# 技能内容

在这里编写专业知识...
EOF
```

重启服务或调用 `GET /pipeline/skills` 刷新。
