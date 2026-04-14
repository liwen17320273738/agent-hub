# AI 军团全链路架构设计

## 一、整体愿景

从"前台 Agent 对话"升级为 **AI 军团自动化流水线**：

```
飞书/QQ 消息 → OpenClaw 网关 → 任务创建 → 流水线编排 → Claude Code 执行 → 前台评审/验收
```

## 二、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     外部消息接入层                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ 飞书 Bot │  │  QQ Bot  │  │ Web Chat │  │ REST API    │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘ │
│       │              │             │               │        │
│       └──────────────┴─────────────┴───────────────┘        │
│                          │                                   │
│                    ┌─────▼──────┐                            │
│                    │  OpenClaw  │  统一消息网关               │
│                    │  Gateway   │  解析意图 → 创建任务        │
│                    └─────┬──────┘                            │
└──────────────────────────┼──────────────────────────────────┘

┌──────────────────────────┼──────────────────────────────────┐
│                    任务流水线引擎                             │
│                    ┌─────▼──────┐                            │
│                    │   Task     │  任务状态机                 │
│                    │   Engine   │  阶段推进 / 审批 / 回退     │
│                    └─────┬──────┘                            │
│                          │                                   │
│     ┌────────────────────┼────────────────────┐              │
│     ▼          ▼         ▼         ▼          ▼              │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐          │
│  │需求   │ │PRD   │ │开发   │ │测试   │ │验收/运维 │          │
│  │评审   │ │定义   │ │实现   │ │验证   │ │发布     │          │
│  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───────┘          │
│     │        │        │        │        │                    │
│     ▼        ▼        ▼        ▼        ▼                    │
│  Wayne    Wayne    Claude    Wayne    Wayne                   │
│  Orch.    PM       Code     QA       Orch.                   │
└──────────────────────────┬──────────────────────────────────┘

┌──────────────────────────┼──────────────────────────────────┐
│                    执行层                                     │
│  ┌───────────────────────▼────────────────────────┐          │
│  │              Executor Bridge                    │          │
│  │  ┌──────────────┐  ┌──────────────┐            │          │
│  │  │ Claude Code  │  │  LLM Agents  │            │          │
│  │  │ (终端执行)    │  │  (对话/分析)  │            │          │
│  │  └──────────────┘  └──────────────┘            │          │
│  └────────────────────────────────────────────────┘          │
└──────────────────────────┬──────────────────────────────────┘

┌──────────────────────────┼──────────────────────────────────┐
│                    前台展示层                                 │
│  ┌───────────────────────▼────────────────────────┐          │
│  │           Pipeline Dashboard                    │          │
│  │  任务看板 │ 阶段可视化 │ 审批 │ 日志 │ 验收     │          │
│  └────────────────────────────────────────────────┘          │
│  ┌────────────────────────────────────────────────┐          │
│  │           WebSocket 实时推送                     │          │
│  └────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

## 三、核心模块设计

### 3.1 任务模型 (Task)

```typescript
interface PipelineTask {
  id: string
  title: string
  description: string
  source: 'feishu' | 'qq' | 'web' | 'api'
  sourceMessageId?: string
  sourceUserId?: string
  status: 'intake' | 'planning' | 'building' | 'testing' | 'reviewing' | 'done' | 'cancelled'
  currentStageId: PipelineStageId
  stages: PipelineStageState[]
  artifacts: TaskArtifact[]
  executionLogs: ExecutionLog[]
  createdAt: number
  updatedAt: number
  createdBy: string
}
```

### 3.2 流水线阶段 (Pipeline Stages)

| 阶段 | 负责角色 | 执行方式 | 产物 |
|------|---------|---------|------|
| intake | OpenClaw | 自动 | 结构化需求 |
| planning | Wayne PM | LLM 对话 | PRD + 验收标准 |
| architecture | Wayne Dev | LLM 对话 | 技术方案 |
| building | Claude Code | 终端执行 | 代码 + PR |
| testing | Wayne QA | LLM + 执行 | 测试报告 |
| reviewing | Wayne 总控 | 人工+AI | 验收结论 |
| shipping | 运维自动化 | 脚本执行 | 部署结果 |

### 3.3 OpenClaw 网关

OpenClaw 是统一的消息入口：
- 接收飞书/QQ/API 消息
- 解析意图：是需求？是查询？是审批？
- 创建或更新任务
- 通知相关 agent 开始工作
- 回复消息源（飞书/QQ）进度

### 3.4 执行桥 (Executor Bridge)

对接 Claude Code CLI：
- 创建隔离的工作目录
- 构建 prompt（包含 PRD、代码上下文）
- 通过 claude cli 执行
- 捕获输出和结果
- 生成 diff/PR

### 3.5 WebSocket 事件系统

实时推送：
- 任务状态变化
- 阶段推进
- 执行日志流
- 审批请求

## 四、API 设计

### 网关 (Gateway)

```
POST /api/gateway/feishu/webhook     飞书事件回调
POST /api/gateway/qq/webhook         QQ 机器人回调
POST /api/gateway/intake             Web/API 手动提需求
```

### 流水线 (Pipeline)

```
GET    /api/pipeline/tasks            任务列表
POST   /api/pipeline/tasks            创建任务
GET    /api/pipeline/tasks/:id        任务详情
PATCH  /api/pipeline/tasks/:id        更新任务
POST   /api/pipeline/tasks/:id/advance  推进到下一阶段
POST   /api/pipeline/tasks/:id/approve  审批通过
POST   /api/pipeline/tasks/:id/reject   审批打回
```

### 执行 (Execution)

```
POST   /api/executor/run              执行 Claude Code 任务
GET    /api/executor/tasks/:id/logs   获取执行日志
WS     /api/executor/tasks/:id/stream 实时执行流
```

## 五、实施路线

### Phase 1: 基础设施（当前）
- [x] Task 数据模型和状态机
- [x] Pipeline API (CRUD + 阶段推进)
- [x] OpenClaw 网关骨架
- [x] 飞书 Webhook 接入
- [x] WebSocket 事件系统
- [x] Pipeline Dashboard 前端

### Phase 2: 执行层
- [ ] Claude Code CLI 集成
- [ ] 执行结果解析和存储
- [ ] Git 操作自动化 (branch, commit, PR)

### Phase 3: 智能编排
- [ ] LLM 驱动的意图识别
- [ ] 自动阶段推进（带人工审批门）
- [ ] 多任务并行调度

### Phase 4: 扩展集成
- [ ] QQ Bot 接入 (OneBot 协议)
- [ ] 钉钉/企业微信
- [ ] CI/CD 集成 (GitHub Actions)
- [ ] 监控告警
