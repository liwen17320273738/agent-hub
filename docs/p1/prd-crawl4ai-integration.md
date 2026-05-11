# P1-1: crawl4ai 爬虫服务集成方案

## 1. 产品目标

为 Agent Hub 平台集成 crawl4ai 网页爬虫能力，支持 AI 任务执行过程中的网页内容提取、结构化数据抓取和深度搜索研究。

### 核心价值
- **LLM 友好输出**：生成 Markdown 格式内容，直接可用于 RAG 和上下文注入
- **研究任务支撑**：为 planning、architecture 等阶段提供实时网页数据采集能力
- **多策略爬取**：支持 BFS/DFS/Best-First 深度爬取策略
- **结构化提取**：基于 CSS/JSON Pathfinder 实现精准数据提取

---

## 2. 用户故事

| # | 用户故事 | 阶段 |
|---|---------|------|
| US-01 | 作为 AI Agent，我希望在执行研究任务时能够抓取指定网页的完整内容，以便获取最新信息 | planning / architecture |
| US-02 | 作为 AI Agent，我希望爬虫能够生成 LLM 友好的 Markdown 格式，减少后续处理成本 | development |
| US-03 | 作为 AI Agent，我希望能够对目标网站进行深度爬取，发现多层关联页面 | architecture / research |
| US-04 | 作为 AI Agent，我希望能够基于 CSS 选择器或 JSON Path 提取特定结构化数据 | development |
| US-05 | 作为运维人员，我希望爬虫服务支持配置化，支持超时、重试、并发控制 | deployment |
| US-06 | 作为用户，我希望通过 API 调用爬虫服务，支持同步/异步两种模式 | API |

---

## 3. 功能需求

### P0 — 核心功能（必须实现）

| ID | 功能 | 描述 |
|----|------|------|
| F-P0-01 | 基础网页抓取 | 支持给定 URL 的 HTML 获取，生成 Markdown 输出 |
| F-P0-02 | Markdown 生成 | 调用 crawl4ai 的 `crawl()` 或 `arun()` 生成 LLM 友好的 Markdown |
| F-P0-03 | 工具注册 | 在 `tools/registry.py` 中注册 `crawl4ai` 工具，遵循现有工具规范 |
| F-P0-04 | 异步执行支持 | 长时间爬取任务支持异步执行，通过 task_id 查询结果 |
| F-P0-05 | 错误处理 | 超时、连接失败、JavaScript 渲染失败等异常处理 |

### P1 — 重要功能（计划实现）

| ID | 功能 | 描述 |
|----|------|------|
| F-P1-01 | 深度爬取策略 | 支持 BFS/DFS/Best-First 多策略爬取指定域名下的多个页面 |
| F-P1-02 | 结构化数据提取 | 支持 CSS Selector / JSON Pathfinder 提取特定数据 |
| F-P1-03 | 浏览器控制 | 支持 headless Chrome 配置、UA 伪装、Cookie 设置 |
| F-P1-04 | 结果缓存 | 对频繁访问的 URL 结果进行缓存，提升响应速度 |

### P2 — 增强功能（后续迭代）

| ID | 功能 | 描述 |
|----|------|------|
| F-P2-01 | 爬取调度 | 支持按计划周期性爬取任务 |
| F-P2-02 | 爬取历史 | 记录爬取历史，支持回溯和审计 |
| F-P2-03 | 增量爬取 | 仅爬取自上次以来有变化的内容 |

---

## 4. API 设计

### 4.1 内部工具接口（Agent 调用）

```
工具名称: crawl4ai
描述: 爬取指定网页并生成 LLM 友好的 Markdown 内容
参数:
  - url (string, required): 目标网页 URL
  - strategy (string, optional): 爬取策略 [bfs|dfs|best_first], 默认: "smart"
  - max_depth (int, optional): 最大爬取深度, 默认: 2
  - max_pages (int, optional): 最大页面数, 默认: 10
  - css_selector (string, optional): CSS 选择器，用于提取特定内容
  - js_timeout (int, optional): JavaScript 渲染超时(秒), 默认: 30
  - cache_ttl (int, optional): 缓存 TTL(秒), 默认: 3600
返回: JSON { markdown: string, url: string, metadata: object }
```

### 4.2 REST API 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/crawl` | 同步爬取单个 URL，返回 Markdown |
| POST | `/api/v1/crawl/async` | 异步爬取，返回 task_id |
| GET | `/api/v1/crawl/{task_id}` | 查询异步爬取任务状态和结果 |
| POST | `/api/v1/crawl/deep` | 深度爬取，支持多策略 |
| DELETE | `/api/v1/crawl/{task_id}` | 取消爬取任务 |

### 4.3 API 请求/响应示例

#### POST /api/v1/crawl（同步）
**Request:**
```json
{
  "url": "https://example.com/article",
  "css_selector": "article.content",
  "js_timeout": 30
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "markdown": "# Article Title\n\n文章内容...",
    "url": "https://example.com/article",
    "metadata": {
      "title": "页面标题",
      "description": "页面描述",
      "crawl_time_ms": 1523,
      "word_count": 2048
    }
  }
}
```

#### POST /api/v1/crawl/async（异步）
**Request:**
```json
{
  "url": "https://example.com/",
  "strategy": "bfs",
  "max_depth": 3,
  "max_pages": 50
}
```

**Response:**
```json
{
  "success": true,
  "task_id": "crawl_abc123",
  "status": "pending"
}
```

---

## 5. 集成方案

### 5.1 模块结构

```
backend/app/services/
├── tools/
│   ├── crawl4ai_tool.py       # 新增：crawl4ai 工具实现
│   └── registry.py            # 修改：注册 crawl4ai 工具
├── crawl/
│   ├── __init__.py
│   ├── service.py             # 新增：爬虫服务核心逻辑
│   ├── router.py              # 新增：FastAPI 路由
│   └── models.py              # 新增：Pydantic 模型
└── pipeline_engine.py         # 参考：现有架构
```

### 5.2 工具注册（tools/registry.py）

参考现有工具注册模式，在 `TOOL_REGISTRY` 中添加：

```python
"crawl4ai": {
    "name": "crawl4ai",
    "description": "Crawl a URL and return LLM-friendly Markdown content",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL to crawl"},
            "strategy": {"type": "string", "description": "Crawl strategy: bfs, dfs, best_first, smart"},
            "max_depth": {"type": "integer", "description": "Max crawl depth"},
            "max_pages": {"type": "integer", "description": "Max pages to crawl"},
            "css_selector": {"type": "string", "description": "CSS selector for content extraction"},
            "js_timeout": {"type": "integer", "description": "JavaScript render timeout in seconds"},
        },
        "required": ["url"],
    },
    "permissions": ["network"],
    "handler": crawl4ai_execute,  # 新增
}
```

### 5.3 服务实现要点

1. **异步任务管理**：复用现有的 `task_scheduler.py` 任务调度机制
2. **结果存储**：爬取结果存储到 `task_artifact` 表
3. **Pipeline 集成**：在 planning/architecture 阶段的 agent system prompt 中注入 `crawl4ai` 工具说明
4. **依赖管理**：通过 `pip install crawl4ai` 安装，保持与现有依赖一致

### 5.4 与现有系统的对接

| 现有组件 | 对接方式 |
|---------|---------|
| pipeline_engine.py | Agent 调用 `crawl4ai` 工具时触发服务 |
| task_scheduler.py | 异步任务复用任务调度框架 |
| observability.py | 爬取操作写入 trace span |
| memory.py | 爬取结果可选择性存入 memory 供后续检索 |

---

## 6. 验收标准

### 6.1 功能验收

| 标准 | 验证方式 |
|------|---------|
| 给定 URL 返回 Markdown 内容 | 调用 `crawl4ai` 工具，检查返回内容 |
| 支持 CSS 选择器提取 | 使用 `css_selector` 参数验证 |
| 深度爬取多页面 | 调用 `/crawl/deep` 接口，检查返回页面数 |
| 异步任务查询 | 提交异步任务，通过 task_id 查询状态 |
| 错误处理 | 传入无效 URL，验证错误返回格式 |

### 6.2 非功能验收

| 标准 | 目标 |
|------|------|
| 响应时间 | 简单页面 < 5s，复杂页面 < 30s |
| 可用性 | 服务独立运行，支持 graceful shutdown |
| 可观测性 | 爬取操作产生 trace span |

### 6.3 集成验收

| 标准 | 验证方式 |
|------|---------|
| 工具可被 Agent 调用 | 在 planning 阶段 agent 中触发爬虫任务 |
| 结果可注入 pipeline | 爬取内容作为 context 传递给后续 stage |
| API 文档完整 | OpenAPI/Swagger 文档可访问 |

---

## 7. 技术依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| crawl4ai | >= 0.2.0 | 爬虫核心库 |
| playwright | latest | 浏览器自动化 |
| fastapi | 现有版本 | API 框架 |
| sqlalchemy | 现有版本 | 数据库 |

---

## 8. 里程碑

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| M1 | 完成 crawl4ai_tool.py 基础实现 | P0 |
| M2 | 完成 REST API 端点 | P0 |
| M3 | 完成工具注册和 pipeline 集成 | P0 |
| M4 | 异步任务支持 | P1 |
| M5 | 深度爬取策略 | P1 |
| M6 | 完整测试覆盖 | P1 |
