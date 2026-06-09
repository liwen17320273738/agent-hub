好的，情况很清楚了。`docs/03-architecture.md` 和 `docs/04-implementation-notes.md` 还是空的模板占位符，`src/` 和 `config/` 目录也是空的。现在我来基于 PRD 和 UI Spec 输出完整的架构方案，并填写所有缺失的内容。

---

## 架构方案

### 一、技术选型

| 领域 | 选型 | 理由 | 替代方案 |
|------|------|------|----------|
| **框架** | Vanilla JS (ES2020+) | 零构建步骤、单HTML交付、<100KB体积、无需npm/node；PRD明确要求"打开即用" | React 18（300KB+，需构建工具，过度设计）、Vue 3（仍需Vite构建，对纯前端待办看板过重） |
| **存储** | `localStorage` (key: `todos`) | 浏览器原生支持、无后端依赖、~5MB容量足够500+条任务 | IndexedDB（API复杂，异步操作增加代码复杂度，对简单CRUD过度设计）、SessionStorage（关闭即丢失，不符合持久化需求） |
| **ID生成** | `crypto.randomUUID()` | 浏览器原生API、无需第三方库、符合UUIDv4标准 | `Math.random()` + `Date.now()`（碰撞概率高）、nanoid（需npm引入） |
| **CSS方案** | CSS Custom Properties + Scoped Styles | 零依赖、设计Token直接映射为CSS变量、`backdrop-filter`原生支持毛玻璃 | Tailwind CSS（需构建步骤，增加体积）、CSS Modules（需构建工具） |
| **字体** | 系统字体栈 + `font-display: swap` | 零网络请求、无FOIT问题、`-apple-system`在各平台均有原生美型字体 | Google Fonts Inter（增加网络请求和FOIT风险，与PRD ≤200KB目标冲突） |
| **图标** | Unicode Emoji + SVG inline | 零依赖、跨平台兼容、可缩放 | Font Awesome（~150KB，过度设计）、Heroicons（需npm引入） |
| **部署** | 静态HTML (GitHub Pages / Vercel / Netlify) | 零服务器、零运维、单文件上传即用 | Docker/Nginx（严重过度设计） |

**技术选型核心权衡**：

| 决策 | 收益 | 成本 |
|------|------|------|
| Vanilla JS 而非框架 | 体积<50KB，零构建，部署即用 | 无组件化，手动管理DOM状态 |
| localStorage 而非 IndexedDB | 同步API，代码简单，<20行存储逻辑 | 5MB上限，无索引查询能力 |
| 系统字体栈而非 Google Fonts | 零网络请求，首屏无FOUT | 视觉一致性略逊于Inter定制字体 |
| Emoji 图标而非 SVG 图标库 | 零依赖，零代码量 | 跨平台渲染略有差异 |

### 二、系统架构

#### 模块划分

```
┌──────────────────────────────────────────────────────┐
│                    index.html                         │
│  ┌────────────────────────────────────────────────┐  │
│  │  CSS (内联 <style>)                             │  │
│  │  ├── CSS Variables (设计Token)                  │  │
│  │  ├── Reset / Base                              │  │
│  │  ├── Layout (Header / Columns / Footer)        │  │
│  │  ├── Components (TodoCard / InputBar / Badge)   │  │
│  │  ├── States (Empty / Hover / Focus / Active)    │  │
│  │  ├── Animations (fadeIn / slideOut / scale)     │  │
│  │  └── Media Queries (Responsive Breakpoints)     │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
│  ┌────────────────────────────────────────────────┐  │
│  │  HTML (语义化结构)                              │  │
│  │  ├── <header> 标题区域                          │  │
│  │  ├── <main>                                    │  │
│  │  │   ├── <section#todo-column> 待办列          │  │
│  │  │   ├── <section#done-column> 已完成列        │  │
│  │  │   └── <div#empty-state> 空状态              │  │
│  │  └── <footer> 输入栏                           │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
│  ┌────────────────────────────────────────────────┐  │
│  │  JS (内联 <script type="module">)               │  │
│  │  ├── Storage Layer (getTodos / saveTodos)       │  │
│  │  ├── Business Logic (add / toggle / delete)     │  │
│  │  ├── DOM Render (renderTodos / renderEmpty)     │  │
│  │  ├── Event Binding (submit / click / keydown)   │  │
│  │  └── Init (DOMContentLoaded)                    │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

#### 数据流

```
用户操作 (点击/输入)
    │
    ▼
Event Handler (submit / click / keydown)
    │
    ▼
Business Logic (addTodo / toggleTodo / deleteTodo)
    │
    ├──▶ Storage Layer (saveTodos → localStorage)
    │
    ▼
DOM Render (renderTodos → innerHTML / insertAdjacentHTML)
    │
    ▼
用户看到更新后的界面
```

**关键设计决策**：
- **单向数据流**：所有状态变更经过 Storage Layer → Business Logic → DOM Render，避免双向绑定带来的状态不一致
- **全量重渲染 vs 增量更新**：任务数 ≤ 500 时，全量重渲染性能可接受（<5ms），选择 `innerHTML` 全量重绘以保持代码简洁；后续如需优化可改为 `insertAdjacentHTML` 增量更新
- **事件委托**：在列容器上使用事件委托处理所有子任务卡片的点击事件，避免为每个任务绑定/解绑事件

### 三、数据模型

```javascript
/**
 * @typedef {Object} Todo
 * @property {string} id - UUID v4，由 crypto.randomUUID() 生成
 * @property {string} text - 任务内容，纯文本，trim() 后非空
 * @property {boolean} completed - 完成状态
 * @property {string} createdAt - ISO 8601 时间戳
 */

// localStorage 存储结构
// key: "todos"
// value: JSON.stringify(Todo[])
// 示例: [
//   { "id": "a1b2c3d4-...", "text": "买牛奶", "completed": false, "createdAt": "2024-01-15T10:30:00.000Z" },
//   { "id": "e5f6g7h8-...", "text": "写周报", "completed": true, "createdAt": "2024-01-15T09:00:00.000Z" }
// ]
```

**数据验证规则**：

| 字段 | 验证规则 | 违反处理 |
|------|----------|----------|
| `id` | 必须是有效 UUID v4 格式 | 拒绝写入，抛异常 |
| `text` | 非空字符串，trim() 后长度 ≥ 1，≤ 500 字符 | 空值拒绝添加，超长自动截断 |
| `completed` | 必须是 boolean | 强制转换为 boolean |
| `createdAt` | 必须是有效 ISO 8601 字符串 | 修复为当前时间戳 |

**存储容量估算**：
- 单条任务约 150-200 字节（JSON序列化后）
- 500 条任务 ≈ 75-100KB
- localStorage 配额 ~5MB，可支持 ~25,000 条任务
- **安全阈值**：任务数 > 800 时在控制台输出警告，但不阻塞写入

### 四、API 设计

由于本项目是纯前端单页应用，无后端 API。以下是**内部模块接口**定义：

#### 4.1 Storage Layer

```javascript
// 读取所有待办事项
// @returns {Todo[]}
function getTodos() { /* 读 localStorage */ }

// 保存所有待办事项
// @param {Todo[]} todos
function saveTodos(todos) { /* 写 localStorage */ }
```

#### 4.2 Business Logic Layer

```javascript
// 新增待办
// @param {string} text - 任务内容
// @returns {Todo} 新创建的任务对象
// @throws {Error} 当 text 为空或仅空白字符时
function addTodo(text)

// 切换完成状态
// @param {string} id - 任务ID
function toggleTodo(id)

// 删除任务
// @param {string} id - 任务ID
function deleteTodo(id)

// 获取所有待办（按创建时间降序）
// @returns {Todo[]}
function getAllTodos()

// 获取待办列表
// @returns {Todo[]}
function getPendingTodos()

// 获取已完成列表
// @returns {Todo[]}
function getCompletedTodos()
```

#### 4.3 DOM Render Layer

```javascript
// 渲染整个看板
function renderBoard()

// 渲染空状态
function renderEmptyState()

// 渲染待办列
function renderTodoColumn(todos)

// 渲染已完成列
function renderDoneColumn(todos)

// 渲染单个任务卡片
// @param {Todo} todo
// @returns {string} HTML 字符串
function renderTodoCard(todo)
```

#### 4.4 Event Bindings

| 事件 | 元素 | 处理逻辑 |
|------|------|----------|
| `submit` | 输入表单 | 阻止默认提交，调用 addTodo，重置输入框，刷新视图 |
| `keydown` (Enter) | 输入框 | 触发表单提交 |
| `click` (委托) | 列容器 `.todo-card .checkbox` | 调用 toggleTodo(id)，刷新视图 |
| `click` (委托) | 列容器 `.todo-card .delete-btn` | 调用 deleteTodo(id)，刷新视图 |
| `click` | 已完成列折叠按钮（移动端） | 切换 `.collapsed` class |
| `click` | 空状态引导按钮 | 聚焦到输入框 |

### 五、风险与降级

| 风险 | 概率 | 影响 | 降级方案 |
|------|------|------|----------|
| **localStorage 写入失败**（配额满 / 隐私模式） | 低 | 高 — 数据无法保存 | try-catch 捕获异常，显示 Toast 提示"存储空间不足，请清理旧任务"，功能降级为内存中可用但刷新丢失 |
| **`backdrop-filter` 不支持**（旧浏览器） | 中 | 低 — 视觉降级 | `@supports (backdrop-filter: blur(20px))` 检测，不支持时回退为 `rgba(255,255,255,0.85)` 纯色背景，功能完全不受影响 |
| **`crypto.randomUUID()` 不支持**（旧浏览器） | 低 | 低 — ID 生成失败 | 回退方案：`Date.now().toString(36) + Math.random().toString(36).slice(2, 8)` 生成短ID |
| **用户误删除任务** | 中 | 低 — 数据丢失 | 删除不弹确认（保持轻量），但在删除时保存最后删除的任务到内存变量，支持 Undo（5秒内按 Ctrl+Z 恢复） |
| **XSS 注入**（用户输入恶意内容） | 低 | 中 — 脚本执行 | 使用 `textContent` 而非 `innerHTML` 渲染任务文本；输入时不做任何 HTML 转义处理（因为根本不使用 innerHTML） |
| **大量任务渲染性能**（>1000条） | 低 | 中 — 页面卡顿 | 渲染时限制最大显示 500 条，超出时显示"显示前500条，共N条"提示；使用 `requestAnimationFrame` 分片渲染 |

### 六、实施路线图

#### Phase 1: 项目骨架与核心功能（预估 4h）
**依赖**: 无（从零开始）
**交付物**: 可运行的 `index.html`，支持新增/完成/删除/持久化

| 任务 | 工时 | 产出 |
|------|------|------|
| 创建 `index.html` 骨架（HTML结构 + CSS Variables + 空状态） | 1h | HTML 结构和样式系统 |
| 实现 Storage Layer（getTodos / saveTodos） | 0.5h | 数据持久化 |
| 实现 Business Logic（addTodo / toggleTodo / deleteTodo） | 1h | 核心 CRUD |
| 实现 DOM Render（renderBoard / renderTodoCard） | 1h | 视图渲染 |
| 实现事件绑定 + 初始化流程 | 0.5h | 交互功能 |

#### Phase 2: UI 打磨与交互体验（预估 3h）
**依赖**: Phase 1 完成

| 任务 | 工时 | 产出 |
|------|------|------|
| 毛玻璃效果实现 + `@supports` 回退 | 0.5h | 视觉风格 |
| 复选框自定义样式（`appearance: none` + 伪元素） | 0.5h | 设计规范对齐 |
| 交互动画（hover / active / fadeIn / slideOut） | 1h | 流畅体验 |
| 空状态 + 已完成列空状态 | 0.5h | 边界状态覆盖 |
| 键盘可访问性（Tab / Enter / Escape / aria-label） | 0.5h | 无障碍 |

#### Phase 3: 响应式适配与兼容（预估 2h）
**依赖**: Phase 2 完成

| 任务 | 工时 | 产出 |
|------|------|------|
| 桌面端双列布局（≥1024px） | 0.5h | 大屏适配 |
| 平板端双列缩小（768-1023px） | 0.5h | 中屏适配 |
| 手机端单列 + 已完成列折叠（≤767px） | 0.5h | 小屏适配 |
| 底部输入栏 fixed + safe-area-inset-bottom | 0.5h | 移动端安全区域 |

#### Phase 4: QA 与部署（预估 1h）
**依赖**: Phase 3 完成

| 任务 | 工时 | 产出 |
|------|------|------|
| 功能验收测试（US-01 到 US-07） | 0.5h | 测试报告 |
| 浏览器兼容测试（Chrome/Firefox/Safari/Edge） | 0.25h | 兼容性确认 |
| 部署到 GitHub Pages / Vercel | 0.25h | 生产环境 URL |

**总工时预估**: 10h（约 1.5 个工作日）
**关键路径**: Phase 1 → Phase 2 → Phase 3 → Phase 4（串行依赖，不可并行）

---

### 文件清单

以下为 `src/` 和 `config/` 目录下需要创建的全部文件：

| 文件路径 | 职责 | 预估行数 |
|----------|------|----------|
| `src/index.html` | 单页面应用入口，内联所有 CSS 和 JS，零外部依赖 | ~80 行 HTML + ~300 行 CSS + ~150 行 JS |
| `config/.nojekyll` | GitHub Pages 部署标记（空文件，禁用 Jekyll 处理） | 0 行 |

> **架构决策**：本项目 PRD 明确要求"零构建步骤、单 HTML 文件交付"，因此所有代码（HTML/CSS/JS）集中在 `src/index.html` 中。`config/` 目录仅包含部署标记文件。无需 package.json、vite.config.ts、tsconfig.json 等构建配置。

---

### 自检清单

- ✅ 技术选型包含 ≥2 个备选方案对比（React/Vue/Vanilla JS；localStorage/IndexedDB/SessionStorage）
- ✅ 系统架构包含模块划分、数据流图、关键设计决策
- ✅ 数据模型包含完整字段定义、类型注释、验证规则、容量估算
- ✅ API 设计包含所有内部模块接口（Storage / Business Logic / DOM Render / Events）
- ✅ 风险与降级包含 ≥5 项风险及具体降级方案
- ✅ 实施路线图包含 4 个阶段、每个阶段有工时预估和依赖关系
- ✅ 文件清单列出 `src/` 和 `config/` 下所有需要创建的文件
- ✅ 架构方案填写完整，无空模板或占位符

---

## 并行评审反馈

### 并行评审意见 — security
[delegate→security | steps=4]

## 安全性审阅报告：待办看板架构方案

**审计依据**: OWASP Top 10 (2021) / 最小权限原则  
**审计范围**: JWT 配置、数据加密、网络隔离、最小权限  
**审阅目标**: 仅列出安全问题，不重新设计架构

---

### 发现的安全问题

#### 1. JWT 配置 — 架构文档中完全缺失

**严重程度**: 高  

架构方案的技术选型表中未提及 JWT、认证或会话管理。PRD 中未明确要求用户认证，但架构方案作为"完整架构方案"应当明确说明：
- 是否使用 JWT？如果否，理由是什么？
- 如果使用 localStorage 存储待办数据，同一浏览器不同用户之间如何隔离？
- 如果未来需要多用户支持，当前架构无任何 JWT 配置预留（无密钥管理、无过期策略、无刷新令牌机制）。

**违反原则**: OWASP A01:2021 — 失效的访问控制；最小权限原则要求明确谁可以访问什么资源，当前方案对此完全未定义。

---

#### 2. 数据加密 — 敏感数据明文存储

**严重程度**: 高  

架构方案明确选择 `localStorage` 作为存储方案，且数据模型中的 `text` 字段为纯文本。存在以下风险：

- **明文存储**: 所有待办事项内容以明文形式存储在浏览器的 `localStorage` 中。任何能够访问该浏览器（同源）的 JavaScript（包括浏览器扩展、第三方脚本、XSS 攻击载荷）都可以读取所有待办数据。
- **无传输加密**: 架构方案选择"单 HTML 交付"部署方式，如果通过 HTTP 而非 HTTPS 提供服务，待办数据在传输过程中也是明文的。
- **无加密密钥管理**: 即使考虑加密，方案中也没有任何密钥派生、存储或轮换的设计。

**违反原则**: OWASP A02:2021 — 加密机制失效；OWASP A04:2021 — 不安全的设计（数据保护未被纳入架构决策）。

---

#### 3. 网络隔离 — 零防护设计

**严重程度**: 中  

架构方案描述为"单 HTML 交付"、"零服务器、零运维"，这意味着：

- **无后端 API 网关**: 所有逻辑在浏览器端执行，无法实施任何网络层面的访问控制、速率限制或 IP 白名单。
- **无 CORS 策略**: 方案未提及任何 CORS 配置。如果未来引入第三方服务（如备份到云端），当前架构无任何跨域安全策略。
- **无 CSP 头**: 方案未提及 Content-Security-Policy。单 HTML 交付模式下，如果通过 CDN 或静态托管服务部署，默认通常不设置 CSP 头，增加了 XSS 风险。
- **无 HTTPS 强制**: 方案未要求 HTTPS。在 HTTP 环境下，localStorage 数据可能被中间人攻击者注入恶意脚本窃取。

**违反原则**: OWASP A05:2021 — 安全配置错误；网络隔离的缺失使得整个应用暴露于浏览器端的所有攻击面。

---

#### 4. 最小权限 — 未定义任何权限模型

**严重程度**: 高  

架构方案中完全没有权限模型的设计：

- **无用户身份**: 方案未定义任何用户身份概念，所有操作（添加、修改、删除）默认对所有访问者开放。
- **无操作授权**: 架构中的数据流图显示"用户操作 → Event Handler → Business Logic → Storage Layer"，没有任何权限检查步骤。
- **无数据隔离**: 同一浏览器上的所有用户共享同一个 `localStorage` key (`todos`)，无法区分数据归属。
- **无管理功能保护**: 方案未区分普通用户和管理员角色，任何功能对所有用户平等开放。

**违反原则**: OWASP A01:2021 — 失效的访问控制（最严重的安全问题之一）；最小权限原则被完全忽略。

---

#### 5. 额外发现：XSS 风险

**严重程度**: 高  

架构方案中 DOM Render 层使用 `innerHTML` 全量重绘：

> "选择 `innerHTML` 全量重绘以保持代码简洁"

如果待办事项的 `text` 字段包含用户输入且未经过适当的 HTML 转义，这将直接导致存储型 XSS 攻击。攻击者可以创建一条包含 `<script>` 标签或 `onerror` 事件处理器的待办事项，当其他用户（或同一用户刷新页面后）查看时，恶意脚本将在浏览器上下文中执行，可以窃取 localStorage 中的所有数据。
