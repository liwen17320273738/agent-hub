# Agent Hub — 全栈重构 Master Plan

> 后端 Python (FastAPI) + 前端 TypeScript (Vue 3) + PostgreSQL + Redis + Docker

## 问题总览（16 项）

| # | 问题 | 归属阶段 |
|---|------|---------|
| 1 | 模型写死，无法实时获取最新模型 | Phase 2 |
| 2 | 后端数据未入库 | Phase 1 |
| 3 | 缓存机制不成熟 | Phase 1 |
| 4 | 安全、运维不够 | Phase 1 / 7 |
| 5 | AI 军团各角色职责未执行到底 | Phase 3 |
| 6 | 需求未落地交付 | Phase 5 |
| 7 | 技能/skills/rules/hooks/subagent/plugin/MCP 未在技能中心体现 | Phase 4 |
| 8 | 未接入手机端，模块技能未体现 | Phase 6 |
| 9 | 角色（CEO/PE/产品/开发/测试/UI/运维/验收）不明显，能力未体现 | Phase 3 |
| 10 | 未接入服务器，需全栈上线（DB/缓存/安全） | Phase 1 / 7 |
| 11 | 缺乏扩展、迭代能力 | Phase 4 / 5 |
| 12 | AI-Agent 之间协作缺乏 | Phase 5 |
| 13 | 核心/辅助智能体需重新定义 | Phase 3 |
| 14 | Token/Key 费用节约未落地 | Phase 2 |
| 15 | 智能体缺乏自主学习、创新、外部资源收集 | Phase 5 |
| 16 | 后端全局采用 Python，前端 TypeScript | Phase 1 |

---

## Phase 1: Python 后端基础架构

### 技术栈
- **FastAPI** + **Uvicorn** (ASGI)
- **SQLAlchemy 2.0** + **Alembic** (ORM + 迁移)
- **PostgreSQL 16** (主数据库)
- **Redis 7** (缓存 + 会话 + 消息队列)
- **Pydantic v2** (数据校验)
- **python-jose** + **passlib** (JWT + 密码哈希)

### 目录结构
```
backend/
├── alembic/                    # 数据库迁移
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 环境变量 & 配置
│   ├── database.py             # SQLAlchemy 引擎 & 会话
│   ├── redis_client.py         # Redis 连接
│   ├── security.py             # JWT / RBAC / 限流
│   ├── models/                 # SQLAlchemy 模型
│   │   ├── user.py
│   │   ├── org.py
│   │   ├── conversation.py
│   │   ├── pipeline_task.py
│   │   ├── agent_definition.py
│   │   ├── skill.py
│   │   ├── model_provider.py
│   │   └── token_usage.py
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── api/                    # 路由
│   │   ├── auth.py
│   │   ├── agents.py
│   │   ├── conversations.py
│   │   ├── models.py           # 实时模型注册
│   │   ├── pipeline.py
│   │   ├── skills.py
│   │   ├── llm_proxy.py
│   │   ├── gateway.py
│   │   └── admin.py
│   ├── services/               # 业务逻辑
│   │   ├── model_registry.py   # 实时模型获取 + 缓存
│   │   ├── llm_router.py       # 多模型智能路由
│   │   ├── token_tracker.py    # Token 用量追踪
│   │   ├── agent_manager.py    # 智能体管理
│   │   ├── skill_engine.py     # 技能引擎
│   │   ├── pipeline_engine.py  # 流水线引擎
│   │   └── collaboration.py    # 智能体协作
│   ├── agents/                 # 智能体定义
│   │   ├── base.py             # 基类
│   │   ├── roles.py            # 角色枚举
│   │   └── definitions/        # 各角色配置 YAML
│   └── middleware/             # 中间件
│       ├── rate_limit.py
│       ├── cors.py
│       └── logging.py
├── tests/
├── requirements.txt
├── alembic.ini
└── Dockerfile
```

### 数据库设计（核心表）
- `orgs` — 组织
- `users` — 用户（RBAC: admin/member/viewer）
- `conversations` — 对话（乐观锁 revision）
- `agents` — 智能体定义（动态，非硬编码）
- `agent_skills` — 技能绑定
- `agent_rules` — 规则配置
- `agent_hooks` — 钩子配置
- `agent_plugins` — 插件配置
- `agent_mcps` — MCP 配置
- `skills` — 技能库
- `model_providers` — 模型提供商配置
- `model_cache` — 模型列表缓存
- `token_usage` — Token 用量记录
- `pipeline_tasks` — 流水线任务
- `pipeline_stages` — 阶段详情
- `pipeline_artifacts` — 产物
- `api_keys` — API Key 管理

---

## Phase 2: 实时模型注册 & 费用管控

### 实时模型获取
- 各厂商 API 实时拉取可用模型列表
- Redis 缓存（TTL 10min），避免频繁请求
- 前端模型选择器从 API 获取，不再硬编码
- 支持自定义模型端点

### Token 费用追踪
- 每次 LLM 调用记录: provider, model, prompt_tokens, completion_tokens, cost
- 按日/周/月聚合统计
- 预算告警（达到阈值通知）
- 智能路由：根据任务复杂度选择性价比最高的模型

---

## Phase 3: 智能体架构重定义

### 角色矩阵

| 类型 | 角色 | Title | 核心能力 |
|------|------|-------|---------|
| **核心** | CEO / 总控 | Agent Orchestrator | 战略决策、任务编排、审批 |
| **核心** | CTO / 架构师 | Tech Lead | 技术架构、代码审查、技术选型 |
| **核心** | 产品经理 | Product Manager | PRD、用户故事、验收标准 |
| **核心** | 开发工程师 | Developer | 代码实现、技术方案 |
| **核心** | 测试工程师 | QA Engineer | 测试计划、自动化测试 |
| **核心** | UI/UX | Designer | 设计规范、交互设计 |
| **辅助** | DevOps | SRE | CI/CD、监控、部署 |
| **辅助** | 安全 | Security | 安全审计、漏洞扫描 |
| **辅助** | 数据分析 | Data Analyst | 指标分析、报表 |
| **辅助** | 营销 | CMO | 内容营销、品牌 |
| **辅助** | 财务 | CFO | 成本分析、预算 |
| **辅助** | 法务 | Legal | 合规、合同 |
| **网关** | OpenClaw | Gateway | 消息接入、意图识别 |
| **验收** | 验收官 | Acceptance | 最终验收、发布决策 |

### 每个智能体具备
- **Skills**: 可配置技能列表
- **Rules**: 行为规则（YAML 配置）
- **Hooks**: 生命周期钩子（before/after 各阶段）
- **Plugins**: 扩展插件
- **MCP**: Model Context Protocol 配置
- **SubAgents**: 可调用的子智能体

---

## Phase 4: 技能中心

### 技能数据模型
```yaml
skill:
  id: code-review
  name: 代码审查
  category: development
  description: 自动化代码审查
  version: 1.0.0
  author: system
  enabled: true
  config:
    rules: [...]
    hooks: [before_commit, after_push]
    plugins: [eslint, prettier]
    mcp_tools: [file_read, git_diff]
  prompt_template: |
    你是一位资深的代码审查专家...
  input_schema: {...}
  output_schema: {...}
```

### UI 功能
- 技能市场（浏览、搜索、安装）
- 技能详情（配置、测试、日志）
- 自定义技能创建
- 技能与智能体绑定管理

---

## Phase 5: 智能体协作 & 流水线

### 协作模式
1. **串行流水线**: 需求 → PRD → 设计 → 开发 → 测试 → 部署
2. **并行协作**: 多个智能体同时处理不同子任务
3. **审核链**: 关键节点需要特定角色审批
4. **反馈环**: 下游发现问题可回退上游

### 自主学习
- 历史对话学习（提取模式、最佳实践）
- 外部资源采集（技术文档、行业报告）
- 知识库自动更新

---

## Phase 6: 前端升级 & 移动端

### API 适配
- 前端 service 层适配 Python 后端新 API
- WebSocket/SSE 实时通信
- RESTful + OpenAPI 文档

### 移动端就绪
- API 设计遵循 RESTful 最佳实践
- JWT Token 认证（兼容移动端）
- 响应式 UI（现有 Element Plus）

---

## Phase 7: 部署 & 运维

### Docker Compose 生产配置
```yaml
services:
  backend:    # FastAPI (Uvicorn)
  frontend:   # Nginx (Vue SPA)
  postgres:   # PostgreSQL 16
  redis:      # Redis 7
  nginx:      # 反向代理 + SSL
```

### 安全清单
- [x] JWT + HttpOnly Cookie
- [x] RBAC (admin/member/viewer)
- [x] 限流 (Redis + sliding window)
- [x] CORS 白名单
- [x] SQL 注入防护 (SQLAlchemy ORM)
- [x] XSS 防护 (CSP headers)
- [x] API Key 加密存储
- [x] 日志审计
- [x] HTTPS (Let's Encrypt)

### 监控
- 健康检查端点
- Prometheus 指标导出
- 结构化日志 (JSON)
- 错误追踪 (Sentry 可选)
