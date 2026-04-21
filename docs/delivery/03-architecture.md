
# Todo App 技术方案

## 1. 技术选型

| 层次 | 技术 | 选择理由 | 替代方案 |
|------|------|----------|----------|
| 前端框架 | Vue 3 + TypeScript | 渐进式框架，组件化开发，Composition API提升代码复用性，TypeScript提供类型安全 | React（学习曲线陡峭），Angular（过于庞大） |
| UI组件库 | Element Plus | 成熟的Vue组件库，丰富的组件，良好的中文文档，适合快速开发 | Ant Design（React生态），Vuetify（定制化不足） |
| 前端状态管理 | Pinia | Vue官方推荐，轻量级，TypeScript支持良好，比Vuex更简洁 | Vuex（较冗余），Redux（需要额外适配） |
| 后端框架 | FastAPI | 高性能异步框架，自动API文档，类型安全，Python生态丰富 | Django（重量级），Flask（功能较少） |
| 数据库 | PostgreSQL | 强大的关系型数据库，支持复杂查询，事务支持良好，扩展性强 | MySQL（社区支持好），SQLite（不适合生产环境） |
| ORM | SQLAlchemy | 成熟的Python ORM，支持多种数据库，查询灵活，文档完善 | Django ORM（与Django耦合度高），SQLModel（较新） |
| 认证方案 | JWT | 无状态认证，适合分布式系统，易于扩展 | Session认证（不适合分布式），OAuth（过于复杂） |
| 部署方案 | Docker + Docker Compose | 容器化部署，环境一致性，易于扩展和迁移 | 传统服务器部署（环境管理复杂），Kubernetes（学习成本高） |
| 缓存 | Redis | 高性能内存数据库，适合缓存和会话存储 | Memcached（功能较少），内存缓存（无法持久化） |
| 任务队列 | Celery | 成熟的任务队列系统，支持定时任务和分布式任务 | RQ（功能较少），任务队列（自定义实现） |

## 2. 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    用户浏览器 (Client)                        │
└───────────────────────┬───────────────────────────────────────┘
                       │ HTTPS
┌───────────────────────▼───────────────────────────────────────┐
│                    Nginx (反向代理)                          │
└───────────────────────┬───────────────────────────────────────┘
                       │
┌───────────────────────▼───────────────────────────────────────┐
│                 Vue 3 前端应用                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   用户界面      │  │   状态管理      │  │   路由管理      │ │
│  │   (Element Plus)│  │   (Pinia)       │  │   (Vue Router)  │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└───────────────────────┬───────────────────────────────────────┘
                       │ API 调用
┌───────────────────────▼───────────────────────────────────────┐
│                  FastAPI 后端服务                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   API 路由      │  │   业务逻辑      │  │   中间件        │ │
│  │   (RESTful)     │  │   (Pydantic)    │  │   (认证/日志)   │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   认证服务      │  │   任务处理      │  │   定时任务      │ │
│  │   (JWT)         │  │   (Celery)      │  │   (APScheduler) │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└───────────────────────┬───────────────────────────────────────┘
                       │ 数据库查询
┌───────────────────────▼───────────────────────────────────────┐
│                     数据层                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   PostgreSQL    │  │     Redis       │  │   文件存储      │ │
│  │   (主数据库)    │  │   (缓存/队列)  │  │   (用户数据)    │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 3. 数据模型

### 核心实体关系

```
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   User        │    │   Category     │    │   Task        │
│───────────────│    │───────────────│    │───────────────│
│ id (PK)       │    │ id (PK)       │    │ id (PK)       │
│ username      │◄───│ user_id (FK)  │    │ title         │
│ email         │    │ name          │    │ description   │
│ password_hash │    │ color         │    │ due_date      │
│ created_at    │    │ created_at    │    │ is_completed  │
│ updated_at    │    │ updated_at    │    │ category_id(FK)│
│ last_login    │    │               │    │ user_id (FK)  │
└───────────────┘    └───────────────┘    │ reminder_time │
                                          │ created_at    │
                                          │ updated_at    │
                                          └───────────────┘
```

### 核心表结构

#### User 表
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP WITH TIME ZONE
);
```

#### Category 表
```sql
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    color VARCHAR(7) DEFAULT '#3498db',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, name)
);
```

#### Task 表
```sql
CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    due_date TIMESTAMP WITH TIME ZONE,
    reminder_time TIMESTAMP WITH TIME ZONE,
    is_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);
```

#### Index 优化
```sql
CREATE INDEX idx_tasks_user_id ON tasks(user_id);
CREATE INDEX idx_tasks_category_id ON tasks(category_id);
CREATE INDEX idx_tasks_is_completed ON tasks(is_completed);
CREATE INDEX idx_tasks_due_date ON tasks(due_date);
CREATE INDEX idx_categories_user_id ON categories(user_id);
```

## 4. API 设计

### 认证相关 API

#### 用户注册
```
POST /api/auth/register
```
请求体:
```json
{
    "username": "string",
    "email": "string",
    "password": "string"
}
```
响应:
```json
{
    "id": 1,
    "username": "string",
    "email": "string",
    "created_at": "2023-01-01T00:00:00Z"
}
```

#### 用户登录
```
POST /api/auth/login
```
请求体:
```json
{
    "username": "string",
    "password": "string"
}
```
响应:
```json
{
    "access_token": "string",
    "token_type": "bearer"
}
```

### 任务管理 API

#### 获取任务列表
```
GET /api/tasks
```
查询参数:
- `page`: 页码 (默认: 1)
- `limit`: 每页数量 (默认: 20)
- `category_id`: 分类ID过滤
- `is_completed`: 是否完成过滤 (true/false)
- `sort`: 排序字段 (created_at, due_date) (默认: created_at)
- `order`: 排序方向 (asc, desc) (默认: desc)

响应:
```json
{
    "total": 100,
    "page": 1,
    "limit": 20,
    "data": [
        {
            "id": 1,
            "title": "完成项目报告",
            "description": "需要在本周五之前完成",
            "due_date": "2023-01-05T18:00:00Z",
            "reminder_time": "2023-01-04T18:00:00Z",
            "is_completed": false,
            "category": {
                "id": 1,
                "name": "工作",
                "color": "#3498db"
            },
            "created_at": "2023-01-01T10:00:00Z",
            "updated_at": "2023-01-01T10:00:00Z"
        }
    ]
}
```

#### 创建任务
```
POST /api/tasks
```
请求体:
```json
{
    "title": "string",
    "description": "string",
    "due_date": "2023-01-05T18:00:00Z",
    "reminder_time": "2023-01-04T18:00:00Z",
    "category_id": 1
}
```
响应:
```json
{
    "id": 1,
    "title": "string",
    "description": "string",
    "due_date": "2023-01-05T18:00:00Z",
    "reminder_time": "2023-01-04T18:00:00Z",
    "is_completed": false,
    "category": {
        "id": 1,
        "name": "工作",
        "color": "#3498db"
    },
    "created_at": "2023-01-01T10:00:00Z",
    "updated_at": "2023-01-01T10:00:00Z"
}
```

#### 更新任务
```
PUT /api/tasks/{task_id}
```
请求体:
```json
{
    "title": "string",
    "description": "string",
    "due_date": "2023-01-05T18:00:00Z",
    "reminder_time": "2023-01-04T18:00:00Z",
    "category_id": 1,
    "is_completed": true
}
```
响应:
```json
{
    "id": 1,
    "title": "string",
    "description": "string",
    "due_date": "2023-01-05T18:00:00Z",
    "reminder_time": "2023-01-04T18:00:00Z",
    "is_completed": true,
    "category": {
        "id": 1,
        "name": "工作",
        "color": "#3498db"
    },
    "created_at": "2023-01-01T10:00:00Z",
    "updated_at": "2023-01-01T10:30:00Z"
}
```

#### 删除任务
```
DELETE /api/tasks/{task_id}
```
响应:
```json
{
    "message": "Task deleted successfully"
}
```

#### 批量删除任务
```
DELETE /api/tasks
```
请求体:
```json
{
    "task_ids": [1, 2, 3]
}
```
响应:
```json
{
    "message": "3 tasks deleted successfully"
}
```

### 分类管理 API

#### 获取分类列表
```
GET /api/categories
```
响应:
```json
{
    "data": [
        {
            "id": 1,
            "name": "工作",
            "color": "#3498db",
            "task_count": 10
        }
    ]
}
```

#### 创建分类
```
POST /api/categories
```
请求体:
```json
{
    "name": "个人",
    "color": "#2ecc71"
}
```
响应:
```json
{
    "id": 2,
    "name": "个人",
    "color": "#2ecc71",
    "created_at": "2023-01-01T11:00:00Z",
    "updated_at": "2023-01-01T11:00:00Z"
}
```

#### 更新分类
```
PUT /api/categories/{category_id}
```
请求体:
```json
{
    "name": "学习",
    "color": "#e74c3c"
}
```
响应:
```json
{
    "id": 2,
    "name": "学习",
    "color": "#e74c3c",
    "created_at": "2023-01-01T11:00:00Z",
    "updated_at": "2023-01-01T11:30:00Z"
}
```

#### 删除分类
```
DELETE /api/categories/{category_id}
```
响应:
```json
{
    "message": "Category deleted successfully"
}
```

### 提醒服务 API

#### 获取待发送提醒
```
GET /api/reminders/pending
```
响应:
```json
{
    "data": [
        {
            "id": 1,
            "task_id": 1,
            "user_id": 1,
            "message": "您的任务「完成项目报告」即将到期",
            "scheduled_time": "2023-01-04T18:00:00Z",
            "sent": false
        }
    ]
}
```

## 5. 前端架构

### 页面/组件树

```
App
├── Auth
│   ├── Login.vue
│   └── Register.vue
├── Layout
│   ├── Sidebar.vue
│   ├── Header.vue
│   └── Main.vue
├── Dashboard
│   ├── TaskList.vue
│   ├── TaskForm.vue
│   ├── TaskItem.vue
│   └── TaskFilters.vue
├── Categories
│   ├── CategoryList.vue
│   ├── CategoryForm.vue
│   └── CategoryItem.vue
├── Profile
│   ├── UserProfile.vue
│   └── UserSettings.vue
└── Error
    ├── NotFound.vue
    └── Forbidden.vue
```

### 路由表

```javascript
const routes = [
    {
        path: '/',
        component: Layout,
        meta: { requiresAuth: true },
        children: [
            {
                path: '',
                name: 'dashboard',
                component: Dashboard
            },
            {
                path: 'categories',
                name: 'categories',
                component: Categories
            },
            {
                path: 'profile',
                name: 'profile',
                component: Profile
            }
        ]
    },
    {
        path: '/login',
        name: 'login',
        component: Login,
        meta: { guest: true }
    },
    {
        path: '/register',
        name: 'register',
        component: Register,
        meta: { guest: true }
    },
    {
        path: '/404',
        name: 'not-found',
        component: NotFound
    },
    {
        path: '/403',
        name: 'forbidden',
        component: Forbidden
    },
    {
        path: '/:pathMatch(.*)*',
        redirect: '/404'
    }
]
```

### 状态管理方案 (Pinia)

```javascript
// stores/auth.js
export const useAuthStore = defineStore('auth', {
    state: () => ({
        user: null,
        token: localStorage.getItem('token')
    }),
    actions: {
        async login(credentials) {
            // 登录逻辑
        },
        async register(userData) {
            // 注册逻辑
        },
        logout() {
            // 登出逻辑
        }
    }
})

// stores/tasks.js
export const useTaskStore = defineStore('tasks', {
    state: () => ({
        tasks: [],
        currentTask: null,
        loading: false,
        pagination: {
            page: 1,
            limit: 20,
            total: 0
        }
    }),
    actions: {
        async fetchTasks(params = {}) {
            // 获取任务列表
        },
        async createTask(taskData) {
            // 创建任务
        },
        async updateTask(taskId, taskData) {
            // 更新任务
        },
        async deleteTask(taskId) {
            // 删除任务
        },
        async toggleTaskCompletion(taskId) {
            // 切换任务完成状态
        }
    }
})

// stores/categories.js
export const useCategoryStore = defineStore('categories', {
    state: () => ({
        categories: [],
        currentCategory: null,
        loading: false
    }),
    actions: {
        async fetchCategories() {
            // 获取分类列表
        },
        async createCategory(categoryData) {
            // 创建分类
        },
        async updateCategory(categoryId, categoryData) {
            // 更新分类
        },
        async deleteCategory(categoryId) {
            // 删除分类
        }
    }
})
```

### API 客户端封装

```javascript
// utils/api.js
const api = axios.create({
    baseURL: process.env.VUE_APP_API_URL,
    timeout: 10000
})

// 请求拦截器
api.interceptors.request.use(
    config => {
        const token = localStorage.getItem('token')
        if (token) {
            config.headers.Authorization = `Bearer ${token}`
        }
        return config
    },
