# Agent Hub — AI 交付平台

> 把企业需求一句话送进来，AI 团队 90 秒出方案，签字后自动跑到上线。

## 核心路径

```
飞书 / QQ / iOS Shortcut / Web 一句话发需求
    → 📥 收件箱（90 秒看到 Plan/Act 方案）
    → 🤖 团队（14 角色按 Plan 跑，实时看进度）
    → ✅ 验收闸门（客户签字）
    → 🚀 部署上线（Vercel / CF / 小程序）
    → 🔗 客户分享页（/share/:token）
```

## 五个一级入口

| 入口 | 路由 | 说明 |
|------|------|------|
| 控制台 | `/` | Hero CTA + 待办 + 最近任务 |
| 收件箱 | `/inbox` | 待审批 / 进行中 / 已完成 |
| 团队 | `/team` | 14 角色网格 + 实时活跃 |
| 工作流 | `/workflow` | 流水线 + Workflow Builder |
| 资产中心 | `/assets` | 模型 / MCP / 技能 / 评测 / 代码索引 |

## 技术栈

- **前端**：Vue 3 + Vite + Pinia + Element Plus + Vue Flow
- **后端**：FastAPI (Python) + SQLAlchemy (async) + PostgreSQL / SQLite
- **AI**：多厂商 LLM 路由（OpenAI / Anthropic / DeepSeek / Google / 智谱 / 通义）
- **协议**：OpenAI-compatible API、MCP (Model Context Protocol)
- **网关**：飞书、QQ (OneBot)、Slack、iOS Shortcuts

## 快速开始

```bash
# 1. 安装依赖
pnpm install
cd backend && pip install -r requirements.txt

# 2. 配置环境
cp .env.example .env
# 编辑 .env 填入 API Key 和数据库配置

# 3. 启动开发环境
make dev
# 前端: http://localhost:5200
# 后端: http://localhost:8000
# API 文档: http://localhost:8000/docs
```

## Docker 部署

```bash
docker compose up --build -d
# 访问 http://localhost:8787
```

## 项目结构

```
src/               前端 Vue 3 应用
  views/           页面组件（5 入口 + 深链页面）
  components/      通用组件
  services/        API 调用 + 业务逻辑
  stores/          Pinia 状态管理
backend/           FastAPI 后端
  app/api/         路由层
  app/services/    业务服务层
  app/models/      SQLAlchemy 数据模型
data/workspace/    任务工作区（按任务隔离）
```

## 环境变量

参考 `.env.example` 配置。所有 API Key 从环境变量读取，**不要提交到代码仓库**。

## License

MIT
