# Todo App 技术方案

## 1. 技术选型

### 前端
- **Vue 3 + TypeScript**
  - 理由：Vue 3 提供了 Composition API，增强了代码复用性和可维护性；TypeScript 提供类型安全，减少运行时错误
  - 对比：React 学习曲线陡峭，Angular 过于庞大，Vue 更适合中小型项目

### 后端
- **FastAPI**
  - 理由：高性能（基于 Starlette 和 Pydantic），自动生成 API 文档，内置数据验证，支持异步处理
  - 对比：Django 过于重量级，Flask 功能相对简单，FastAPI 在性能和易用性之间取得平衡

### 数据库
- **PostgreSQL**
  - 理由：关系型数据库，支持复杂查询，事务安全，扩展性强，有良好的 JSON 支持
  - 对比：MySQL 更流行但功能相对有限，MongoDB 作为 NoSQL 不适合结构化数据存储

### 缓存
- **Redis**
  - 理由：高性能内存数据存储，支持多种数据结构，适合缓存和会话管理
  - 对比：Memcached 功能相对简单，Redis 提供更多高级特性

### 消息队列
- **Celery + Redis**
  - 理由：Celery 是流行的分布式任务队列，Redis 作为消息代理，适合处理异步任务如发送提醒邮件
  - 对比：RabbitMQ 更复杂但功能更全面，Redis + Celery 轻量级且易于集成

### 部署
- **Docker + Docker Compose**
  - 理由：容器化部署，确保环境一致性，简化部署流程
  - 对比：Kubernetes 过于复杂，Docker Compose 适合中小型项目

### 认证
- **JWT (JSON Web Tokens)**
  - 理由：无状态认证，适合 RESTful API，易于扩展
  - 对比：Session-based 认证需要服务器维护状态，不适合分布式系统

## 2. 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Vue 3)                          │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │   Login     │  │   Tasks     │  │  Categories │            │
│  │  Component  │  │  Component  │  │  Component  │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │   Profile   │  │   Tags      │  │  Reminders  │            │
│  │  Component  │  │  Component  │  │  Component  │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS/TLS
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI)                          │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │   Auth      │  │   Tasks     │  │  Categories │            │
│  │   Router    │  │   Router    │  │   Router    │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │   Tags      │  │   Reminders │  │   Users     │            │
│  │   Router    │  │   Router    │  │   Router    │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│                              │                                 │
│                              ▼                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   Business Logic                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                 │
│                              ▼                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │               Data Access Layer (ORM)                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                 │
│                              ▼                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      Data Layer                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │ PostgreSQL  │  │    Redis    │  │   Files     │            │
│  │   (Main)    │  │   (Cache)   │  │ (Backups)   │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

## 3. 数据模型

### ER 图（文字描述）

```
[User] 1--< [Task] >--1 [Category]
  |           |
  |           |--< [Tag] >--1 [TagType]
  |
  1--< [Reminder] --1 [Task]
```

### 核心表结构

#### 用户表 (users)
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);
```

#### 任务表 (tasks)
```sql
CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    priority VARCHAR(20) DEFAULT 'medium',
    due_date TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    category_id INTEGER REFERENCES categories(id)
);
```

#### 分类表 (categories)
```sql
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(50) NOT NULL,
    color VARCHAR(7) DEFAULT '#3F51B5',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### 标签表 (tags)
```sql
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(50) NOT NULL,
    color VARCHAR(7) DEFAULT '#4CAF50',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### 任务标签关联表 (task_tags)
```sql
CREATE TABLE task_tags (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, tag_id)
);
```

#### 提醒表 (reminders)
```sql
CREATE TABLE reminders (
    id SERIAL PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reminder_time TIMESTAMP WITH TIME ZONE NOT NULL,
    is_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

## 4. API 设计

### 认证相关

| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| POST | /api/auth/register | 用户注册 | 请求: `{ "username": "john_doe", "email": "john@example.com", "password": "password123", "full_name": "John Doe" }`<br>响应: `{ "id": 1, "username": "john_doe", "email": "john@example.com", "full_name": "John Doe" }` |
| POST | /api/auth/login | 用户登录 | 请求: `{ "username": "john_doe", "password": "password123" }`<br>响应: `{ "access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "bearer" }` |
| GET | /api/auth/me | 获取当前用户信息 | 响应: `{ "id": 1, "username": "john_doe", "email": "john@example.com", "full_name": "John Doe" }` |

### 任务相关

| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| GET | /api/tasks | 获取任务列表 | 响应: `[{ "id": 1, "title": "完成项目报告", "description": "需要在本周五前完成", "status": "pending", "priority": "high", "due_date": "2023-12-15T18:00:00Z" }]` |
| POST | /api/tasks | 创建新任务 | 请求: `{ "title": "完成项目报告", "description": "需要在本周五前完成", "priority": "high", "due_date": "2023-12-15T18:00:00Z" }`<br>响应: `{ "id": 1, "title": "完成项目报告", "description": "需要在本周五前完成", "status": "pending", "priority": "high", "due_date": "2023-12-15T18:00:00Z" }` |
| PUT | /api/tasks/{id} | 更新任务 | 请求: `{ "title": "完成项目报告（更新版）", "status": "in_progress" }`<br>响应: `{ "id": 1, "title": "完成项目报告（更新版）", "description": "需要在本周五前完成", "status": "in_progress", "priority": "high", "due_date": "2023-12-15T18:00:00Z" }` |
| DELETE | /api/tasks/{id} | 删除任务 | 响应: `{ "message": "任务已成功删除" }` |
| POST | /api/tasks/batch-delete | 批量删除任务 | 请求: `{ "task_ids": [1, 2, 3] }`<br>响应: `{ "message": "已删除3个任务" }` |
| PUT | /api/tasks/{id}/complete | 标记任务为完成 | 响应: `{ "id": 1, "status": "completed", "completed_at": "2023-12-10T14:30:00Z" }` |

### 分类相关

| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| GET | /api/categories | 获取分类列表 | 响应: `[{ "id": 1, "name": "工作", "color": "#3F51B5" }, { "id": 2, "name": "个人", "color": "#4CAF50" }]` |
| POST | /api/categories | 创建新分类 | 请求: `{ "name": "学习", "color": "#FF9800" }`<br>响应: `{ "id": 3, "name": "学习", "color": "#FF9800" }` |
| PUT | /api/categories/{id} | 更新分类 | 请求: `{ "name": "职业发展", "color": "#9C27B0" }`<br>响应: `{ "id": 3, "name": "职业发展", "color": "#9C27B0" }` |
| DELETE | /api/categories/{id} | 删除分类 | 响应: `{ "message": "分类已成功删除" }` |

### 标签相关

| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| GET | /api/tags | 获取标签列表 | 响应: `[{ "id": 1, "name": "紧急", "color": "#F44336" }, { "id": 2, "name": "重要", "color": "#FF9800" }]` |
| POST | /api/tags | 创建新标签 | 请求: `{ "name": "会议", "color": "#2196F3" }`<br>响应: `{ "id": 3, "name": "会议", "color": "#2196F3" }` |
| PUT | /api/tags/{id} | 更新标签 | 请求: `{ "name": "团队会议", "color": "#3F51B5" }`<br>响应: `{ "id": 3, "name": "团队会议", "color": "#3F51B5" }` |
| DELETE | /api/tags/{id} | 删除标签 | 响应: `{ "message": "标签已成功删除" }` |
| POST | /api/tasks/{id}/tags | 为任务添加标签 | 请求: `{ "tag_ids": [1, 2] }`<br>响应: `{ "message": "标签已成功添加到任务" }` |
| DELETE | /api/tasks/{id}/tags/{tag_id} | 从任务移除标签 | 响应: `{ "message": "标签已从任务中移除" }` |

### 提醒相关

| Method | Path | 描述 | 请求/响应示例 |
|--------|------|------|--------------|
| GET | /api/reminders | 获取提醒列表 | 响应: `[{ "id": 1, "task_id": 1, "reminder_time": "2023-12-14T09:00:00Z", "is_sent": false }]` |
| POST | /api/tasks/{id}/reminders | 为任务创建提醒 | 请求: `{ "reminder_time": "2023-12-14T09:00:00Z" }`<br>响应: `{ "id": 1, "task_id": 1, "reminder_time": "2023-12-14T09:00:00Z", "is_sent": false }` |
| DELETE | /api/reminders/{id} | 删除提醒 | 响应: `{ "message": "提醒已成功删除" }` |

## 5. 前端架构

### 页面/组件树

```
App
├── Auth
│   ├── Login
│   └── Register
├── Dashboard
│   ├── Header
│   ├── Sidebar
│   └── Main
│       ├── TaskList
│       │   ├── TaskItem
│       │   │   ├── TaskPriority
│       │   │   ├── TaskStatus
│       │   │   └── TaskActions
│       │   ├── TaskForm
│       │   └── TaskFilter
│       ├── TaskDetail
│       │   ├── TaskDetailHeader
│       │   ├── TaskDetailContent
│       │   ├── TaskDetailForm
│       │   └── TaskDetailReminders
│       ├── CategoryList
│       │   ├── CategoryItem
│       │   └── CategoryForm
│       ├── TagList
│       │   ├── TagItem
│       │   └── TagForm
│       └── Profile
└── Error
```

### 路由表

| 路径 | 组件 | 描述 |
|------|------|------|
| / | Dashboard | 主仪表盘 |
| /login | Login | 登录页面 |
| /register | Register | 注册页面 |
| /tasks | TaskList | 任务列表 |
| /tasks/:id | TaskDetail | 任务详情 |
| /categories | CategoryList | 分类管理 |
| /tags | TagList | 标签管理 |
| /profile | Profile | 用户资料 |

### 状态管理方案

使用 Pinia 进行状态管理，主要 store 包括：

1. **authStore**: 管理用户认证状态
   - state: user, token, isAuthenticated
   - actions: login, logout, fetchUser

2. **tasksStore**: 管理任务相关状态
   - state: tasks, filters, currentTask
   - actions: fetchTasks, createTask, updateTask, deleteTask, toggleTaskStatus

3. **categoriesStore**: 管理分类相关状态
   - state: categories
   - actions: fetchCategories, createCategory, updateCategory, deleteCategory

4. **tagsStore**: 管理标签相关状态
   - state: tags
   - actions: fetchTags, createTag, updateTag, deleteTag, addTagToTask, removeTagFromTask

5. **remindersStore**: 管理提醒相关状态
   - state: reminders
   - actions: fetchReminders, createReminder, deleteReminder

## 6. 实现路线图

### P0 优先级（核心功能）

1. **项目初始化**（1天）
   - 创建前端 Vue 3 项目
   - 创建后端 FastAPI 项目
   - 设置 PostgreSQL 数据库
   - 配置 Docker 和 Docker Compose

2. **用户认证系统**（3天）
   - 实现用户注册 API
   - 实现用户登录 API
   - 实现 JWT 认证中间件
   - 前端登录和注册页面
   - 前端路由守卫

3. **任务基础功能**（4天）
   - 设计任务数据模型
   - 实现任务 CRUD API
   - 前端任务列表页面
   - �