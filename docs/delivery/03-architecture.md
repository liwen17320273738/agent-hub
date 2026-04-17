
# DAG测试平台技术方案

## 1. 技术选型

| 层次 | 技术 | 选择理由 | 替代方案 |
|------|------|----------|----------|
| 前端 | React 18 + TypeScript | 现代化UI框架，组件化开发，类型安全 | Vue.js, Angular |
| 前端UI | Ant Design | 企业级UI组件库，丰富的图表组件，符合数据可视化需求 | Material-UI, Element UI |
| 前端状态管理 | Redux Toolkit | 标准化状态管理，适合复杂应用，良好的开发工具支持 | MobX, Zustand |
| 后端 | Node.js + Express.js | 轻量级，适合构建RESTful API，事件驱动模型，适合DAG执行 | Python + Flask, Java + Spring Boot |
| 后端类型 | TypeScript | 提供类型安全，减少运行时错误，提高代码质量 | JavaScript, Flow |
| 数据库 | PostgreSQL | 强大的关系型数据库，支持复杂查询和事务，适合存储DAG结构 | MySQL, MongoDB |
| ORM | Prisma | 现代化的数据库ORM，提供类型安全的数据库访问，支持数据库迁移 | TypeORM, Sequelize |
| 缓存 | Redis | 高性能内存数据库，用于缓存和任务队列，提高系统性能 | Memcached |
| 任务队列 | BullMQ | 基于Redis的队列系统，适合处理DAG执行任务 | Bee-Queue, RabbitMQ |
| 前端构建 | Vite | 快速的前端构建工具，提供热更新和优化的开发体验 | Webpack, Rollup |
| 测试框架 | Jest + React Testing Library | 单元测试和集成测试框架，与React生态集成良好 | Mocha + Chai, Cypress |

## 2. 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    前端层 (React)                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ DAG编辑器   │  │ DAG执行器   │  │ 结果可视化  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP/HTTPS
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    后端层 (Node.js + Express)                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ API路由     │  │ DAG引擎     │  │ 日志服务   │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ 数据库连接
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    数据层                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ PostgreSQL  │  │   Redis     │  │ BullMQ队列 │         │
│  │ (主数据)    │  │ (缓存/队列) │  │ (任务队列)  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

### 组件职责说明

- **前端层**：负责用户界面交互，包括DAG编辑器、执行控制和结果展示
- **后端层**：处理业务逻辑，包括API路由、DAG执行引擎和日志服务
- **数据层**：负责数据持久化、缓存和任务队列管理

### 数据流和通信方式

1. **前端到后端**：通过RESTful API进行通信，使用HTTPS加密
2. **后端到数据库**：通过Prisma ORM进行数据库操作
3. **DAG执行**：通过BullMQ队列系统管理任务执行
4. **缓存机制**：使用Redis缓存热点数据和临时结果

## 3. 数据模型设计

### 核心实体关系

```
User (用户)
├── Project (项目) ───┬──> DAG (DAG)
│                   │     ├──> Node (节点)
│                   │     └──> Edge (边)
│                   └──> TestExecution (测试执行)
│                       ├──> TestResult (测试结果)
│                       └──> TestLog (测试日志)
└──> Permission (权限)
```

### 核心表结构和字段

#### 用户表 (User)
```sql
- id: UUID (主键)
- username: String (唯一)
- email: String (唯一)
- password_hash: String
- created_at: DateTime
- updated_at: DateTime
```

#### 项目表 (Project)
```sql
- id: UUID (主键)
- name: String
- description: Text
- user_id: UUID (外键，关联User)
- created_at: DateTime
- updated_at: DateTime
```

#### DAG表 (DAG)
```sql
- id: UUID (主键)
- name: String
- description: Text
- project_id: UUID (外键，关联Project)
- graph_data: JSON (存储DAG结构数据)
- created_at: DateTime
- updated_at: DateTime
```

#### 节点表 (Node)
```sql
- id: UUID (主键)
- dag_id: UUID (外键，关联DAG)
- name: String
- node_type: String (节点类型：transform, extract, load, etc.)
- config: JSON (节点配置)
- position_x: Float (节点位置X坐标)
- position_y: Float (节点位置Y坐标)
- created_at: DateTime
- updated_at: DateTime
```

#### 边表 (Edge)
```sql
- id: UUID (主键)
- source_node_id: UUID (外键，关联源节点)
- target_node_id: UUID (外键，关联目标节点)
- created_at: DateTime
```

#### 测试执行表 (TestExecution)
```sql
- id: UUID (主键)
- dag_id: UUID (外键，关联DAG)
- status: String (状态：pending, running, success, failed)
- start_time: DateTime
- end_time: DateTime
- created_by: UUID (外键，关联User)
```

#### 测试结果表 (TestResult)
```sql
- id: UUID (主键)
- execution_id: UUID (外键，关联TestExecution)
- node_id: UUID (外键，关联Node)
- status: String (状态：success, failed)
- execution_time: Float (执行时间，秒)
- error_message: Text
- created_at: DateTime
```

#### 测试日志表 (TestLog)
```sql
- id: UUID (主键)
- execution_id: UUID (外键，关联TestExecution)
- node_id: UUID (外键，关联Node)
- log_level: String (日志级别：info, warn, error)
- message: Text
- timestamp: DateTime
```

### 存储选型

- **PostgreSQL**：存储结构化数据，如用户、项目、DAG结构、测试结果等
- **Redis**：缓存热点数据，存储临时执行状态，管理任务队列
- **BullMQ**：基于Redis的任务队列系统，处理DAG执行任务

### 数据一致性策略

- 使用数据库事务确保关键操作的原子性
- 采用乐观锁机制处理并发更新
- 通过事件溯源模式记录DAG执行状态变更

## 4. API 设计

### RESTful API 路由表

#### 用户认证
| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| POST | /api/auth/register | 用户注册 | 请求: `{username, email, password}`<br>响应: `{user, token}` |
| POST | /api/auth/login | 用户登录 | 请求: `{email, password}`<br>响应: `{user, token}` |
| POST | /api/auth/logout | 用户登出 | 请求: `{token}`<br>响应: `{success}` |
| GET | /api/auth/me | 获取当前用户信息 | 请求: `Authorization: Bearer <token>`<br>响应: `{user}` |

#### 项目管理
| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| GET | /api/projects | 获取项目列表 | 请求: `Authorization: Bearer <token>`<br>响应: `[{id, name, description, created_at}, ...]` |
| POST | /api/projects | 创建新项目 | 请求: `Authorization: Bearer <token>`<br>请求体: `{name, description}`<br>响应: `{project}` |
| GET | /api/projects/:id | 获取项目详情 | 请求: `Authorization: Bearer <token>`<br>响应: `{project}` |
| PUT | /api/projects/:id | 更新项目 | 请求: `Authorization: Bearer <token>`<br>请求体: `{name, description}`<br>响应: `{project}` |
| DELETE | /api/projects/:id | 删除项目 | 请求: `Authorization: Bearer <token>`<br>响应: `{success}` |

#### DAG管理
| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| GET | /api/projects/:projectId/dags | 获取DAG列表 | 请求: `Authorization: Bearer <token>`<br>响应: `[{id, name, description, created_at}, ...]` |
| POST | /api/projects/:projectId/dags | 创建新DAG | 请求: `Authorization: Bearer <token>`<br>请求体: `{name, description, graph_data}`<br>响应: `{dag}` |
| GET | /api/dags/:id | 获取DAG详情 | 请求: `Authorization: Bearer <token>`<br>响应: `{dag, nodes, edges}` |
| PUT | /api/dags/:id | 更新DAG | 请求: `Authorization: Bearer <token>`<br>请求体: `{name, description, graph_data}`<br>响应: `{dag}` |
| DELETE | /api/dags/:id | 删除DAG | 请求: `Authorization: Bearer <token>`<br>响应: `{success}` |

#### 节点管理
| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| GET | /api/dags/:dagId/nodes | 获取节点列表 | 请求: `Authorization: Bearer <token>`<br>响应: `[{id, name, node_type, config, position_x, position_y}, ...]` |
| POST | /api/dags/:dagId/nodes | 创建新节点 | 请求: `Authorization: Bearer <token>`<br>请求体: `{name, node_type, config, position_x, position_y}`<br>响应: `{node}` |
| GET | /api/nodes/:id | 获取节点详情 | 请求: `Authorization: Bearer <token>`<br>响应: `{node}` |
| PUT | /api/nodes/:id | 更新节点 | 请求: `Authorization: Bearer <token>`<br>请求体: `{name, node_type, config, position_x, position_y}`<br>响应: `{node}` |
| DELETE | /api/nodes/:id | 删除节点 | 请求: `Authorization: Bearer <token>`<br>响应: `{success}` |

#### 边管理
| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| GET | /api/dags/:dagId/edges | 获取边列表 | 请求: `Authorization: Bearer <token>`<br>响应: `[{id, source_node_id, target_node_id}, ...]` |
| POST | /api/dags/:dagId/edges | 创建新边 | 请求: `Authorization: Bearer <token>`<br>请求体: `{source_node_id, target_node_id}`<br>响应: `{edge}` |
| DELETE | /api/edges/:id | 删除边 | 请求: `Authorization: Bearer <token>`<br>响应: `{success}` |

#### DAG测试执行
| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| POST | /api/dags/:id/execute | 执行DAG测试 | 请求: `Authorization: Bearer <token>`<br>请求体: `{config}`<br>响应: `{execution_id}` |
| GET | /api/executions/:id | 获取执行状态 | 请求: `Authorization: Bearer <token>`<br>响应: `{execution, status, progress}` |
| GET | /api/executions/:id/results | 获取测试结果 | 请求: `Authorization: Bearer <token>`<br>响应: `[{node_id, status, execution_time, error_message}, ...]` |
| GET | /api/executions/:id/logs | 获取测试日志 | 请求: `Authorization: Bearer <token>`<br>响应: `[{log_level, message, timestamp}, ...]` |

#### 分页
所有列表API支持分页参数：
- `page`: 页码 (默认: 1)
- `limit`: 每页数量 (默认: 10, 最大: 100)

#### 错误码
| 错误码 | 描述 |
|--------|------|
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 409 | 资源冲突 |
| 500 | 服务器内部错误 |

## 5. 前端架构

### 页面/组件树

```
App
├── Layout (布局组件)
│   ├── Header (头部导航)
│   ├── Sidebar (侧边栏导航)
│   └── Main (主内容区)
├── Auth (认证相关页面)
│   ├── Login (登录页面)
│   └── Register (注册页面)
├── Dashboard (仪表板)
│   ├── ProjectList (项目列表)
│   ├── ProjectDetail (项目详情)
│   └── DAGList (DAG列表)
├── DAGEditor (DAG编辑器)
│   ├── Canvas (画布组件)
│   ├── NodePalette (节点面板)
│   ├── PropertiesPanel (属性面板)
│   └── Toolbar (工具栏)
├── DAGExecutor (DAG执行器)
│   ├── ExecutionControl (执行控制)
│   ├── ExecutionProgress (执行进度)
│   └── ExecutionLogs (执行日志)
├── Visualization (结果可视化)
│   ├── GraphVisualization (图形可视化)
│   ├── ResultTable (结果表格)
│   └── PerformanceChart (性能图表)
└── Settings (设置页面)
    ├── UserProfile (用户资料)
    └── SystemSettings (系统设置)
```

### 路由表

| 路径 | 组件 | 描述 |
|------|------|------|
| / | Dashboard | 仪表板，显示项目概览 |
| /login | Login | 登录页面 |
| /register | Register | 注册页面 |
| /projects | ProjectList | 项目列表 |
| /projects/:id | ProjectDetail | 项目详情 |
| /projects/:projectId/dags | DAGList | DAG列表 |
| /dags/:id/edit | DAGEditor | DAG编辑器 |
| /dags/:id/execute | DAGExecutor | DAG执行器 |
| /dags/:id/results | Visualization | 结果可视化 |
| /settings | Settings | 设置页面 |

### 状态管理方案

使用Redux Toolkit进行状态管理，主要状态包括：

1. **认证状态 (authSlice)**
   - user: 当前用户信息
   - token: 认证令牌
   - isAuthenticated: 是否已认证

2. **项目状态 (projectSlice)**
   - projects: 项目列表
   - currentProject: 当前项目
   - isLoading: 加载状态

3. **DAG状态 (dagSlice)**
   - dags: DAG列表
   - currentDAG: 当前DAG
   - nodes: 节点列表
   - edges: 边列表
   - selectedNode: 选中的节点

4. **执行状态 (executionSlice)**
   - executions: 执行历史
   - currentExecution: 当前执行
   - executionResults: 执行结果
   - executionLogs: 执行日志

5. **UI状态 (uiSlice)**
   - theme: 主题 (light/dark)
   - sidebarOpen: 侧边栏状态
   - notifications: 通知列表

### 数据获取策略

1. 使用React Query进行服务端状态管理
2. 实现乐观更新提升用户体验
3. 使用SWR进行数据预取和缓存
4. 实现自动重试和错误处理机制

## 6. 实现路线图

### 阶段 1: 基础架构搭建 (4周)

| 任务 | 工时 | 依赖 |
|------|------|------|
| 环境搭建与配置 | 1周 | 无 |
| 数据库设计 | 1周 | 无 |
| 后端API框架搭建 | 1周 | 数据库设计 |
| 前端项目初始化 | 1周 | 无 |

### 阶段 2: 核心功能开发 (8周)

| 任务 | 工时 | 依赖 |
|------|------|------|
| 用户认证系统 | 1周 | 基础架构 |
| 项目管理功能 | 1周 | 用户认证 |
| DAG基础数据结构 | 1.5周 | 项目管理 |
| 节点和边管理 | 1.5周 | DAG基础数据结构 |
| DAG编辑器前端 | 2周 | 节点和边管理 |
| DAG执行引擎 | 2周 | DAG基础数据结构 |
| 测试结果收集 | 1周 | DAG执行引擎 |

### 阶段 3: 可视化和优化 (4周)

| 任务 | 工时 | 依赖 |
|------|------|------|
| 结果可视化