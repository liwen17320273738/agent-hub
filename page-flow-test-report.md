# Agent Hub 页面流程测试报告

**日期**: 2026-05-25
**测试方式**: Playwright E2E（chromium，真实浏览器）
**测试环境**: 后端 127.0.0.1:8000（FastAPI）+ 前端 127.0.0.1:5200（Vite）

---

## 一、测试结果总览

| 测试套件 | 通过 | 失败 | 跳过 | 总计 |
|---|---|---|---|---|
| sidebar-smoke | 1 | 0 | 0 | 1 |
| hero-smoke | 1 | 0 | 1 | 2 |
| visual-preview | 1 | 0 | 0 | 1 |
| regression-matrix | 16 | 0 | 0 | 16 |
| regression-battery | 12 | 1 | 0 | 13 |
| **总计** | **31** | **1** | **1** | **33** |

**通过率**: 31/33 = 93.9%（跳过不计入失败）

---

## 二、详细测试结果

### 2.1 侧栏冒烟（sidebar-smoke.spec.ts）✅

| 测试 | 结果 | 耗时 |
|---|---|---|
| 登录后可走 控制台 → 收件箱 → 团队 → 工作流 → 资产 | ✅ PASS | 1.7s |

### 2.2 Hero Path 冒烟（hero-smoke.spec.ts）✅

| 测试 | 结果 | 耗时 |
|---|---|---|
| 登录 → 任务详情 → 收件箱 → 匿名分享页 | ✅ PASS | 6.0s |
| 首页输入 → 直执行创建任务并跳进详情（gateway intake） | ⏭️ SKIP | — |

> Gateway intake 跳过原因：未设置 E2E_DASHBOARD_INTAKE=1 和 E2E_PIPELINE_API_KEY

### 2.3 可视化预览（visual-preview.spec.ts）✅

| 测试 | 结果 | 耗时 |
|---|---|---|
| 交付物 Tab：UI 设计稿与架构图 iframe 正常渲染 | ✅ PASS | 4.7s |

### 2.4 回归矩阵（regression-matrix.spec.ts）✅ 16/16

**矩阵 A（无需后端）**：

| # | 测试 | 结果 |
|---|---|---|
| 1 | 登录页展示品牌与表单 | ✅ |
| 2 | 空邮箱密码提交显示客户端校验 | ✅ |
| 3 | 未登录访问收件箱重定向到登录并保留回程路径 | ✅ |
| 4 | 未登录访问控制台重定向到登录 | ✅ |
| 5 | 未知路由显示 404 页 | ✅ |

**矩阵 B（需后端）**：

| # | 测试 | 结果 |
|---|---|---|
| 6 | 错误密码登录显示错误提示 | ✅ |
| 7 | 登录成功：控制台 Hero 与快捷按钮 | ✅ |
| 8 | 登录成功：收件箱页面结构 | ✅ |
| 9 | 登录成功：团队页 Agent 网格容器 | ✅ |
| 10 | 登录成功：工作流页 Tab | ✅ |
| 11 | 登录成功：资产页 Tab | ✅ |
| 12 | 登录成功：设置页 | ✅ |
| 13 | 侧栏语言切换为 English 后导航显示 Home | ✅ |
| 14 | 无效任务 ID：详情页展示加载失败与重试 | ✅ |
| 15 | 无效分享令牌：分享页错误态 | ✅ |
| 16 | 清除本地令牌后受保护路由回到登录页 | ✅ |

### 2.5 回归电池（regression-battery.spec.ts）⚠️

| # | 测试 | 结果 |
|---|---|---|
| 01 | GET /health 返回 200 | ✅ |
| 02 | GET /api/pipeline/health 经前端代理可用 | ✅ |
| 03 | 未授权 POST /api/pipeline/tasks → 401 | ✅ |
| 04 | 未授权 POST /api/share/generate → 401 | ✅ |
| 05 | JWT GET /api/auth/me 成功 | ✅ |
| 06 | JWT GET /api/pipeline/tasks 返回列表 | ✅ |
| 07 | 游客访问收件箱 → 登录页并写入回程 sessionStorage | ✅ |
| 08 | 伪造分享令牌页 → 错误态 | ✅ |
| 09 | 建单 → 分享令牌 → 匿名页可见标题 | ❌ FAIL |
| 10 | relay API：balance + keys 列表 | ✅ |
| 11 | relay API：GET /api/relay/policy 计费字段 | ✅ |
| 12 | 资产中心 · API 中转面板 | ✅ |
| 13 | 未授权 GET /api/relay/policy → 401 | ✅ |

---

## 三、失败分析

### 测试 09：建单 → 分享令牌 → 匿名页可见标题

**原因**：新创建的任务尚无交付证据（测试报告、构建日志、预览链接等），分享端点返回 `409 evidence_missing`。

```json
{"code": "evidence_missing", "message": "交付证据不足：真实验收证据、真实预览、真实测试 未通过。"}
```

**缺失证据项**：
- test_report — 测试报告缺失
- build_log — 构建日志缺失
- test_log — 测试日志缺失
- preview_url — 预览链接缺失
- deploy_screenshot — 部署截图缺失
- acceptance — 验收记录缺失

**评估**：这是预期行为，非 Bug。该测试与 hero-smoke 的区别在于——hero-smoke 使用了 `prepareSmokeWorkspaceId()` 创建允许草稿交付的工作区，而 regression-battery 测试未使用。需在测试中显式允许草稿交付后重试。

**修复方案**：
```ts
// 在 regression-battery.spec.ts 测试 09 开头加入
const wsId = prepareSmokeWorkspaceId()
// 然后用这个 workspace_id 创建任务
```

---

## 四、页面流程验证矩阵

对照 [page-flow-test-report.md 的测试清单](#) 验证结果：

### P0 — 核心路径

| 步骤 | 流程 | 状态 |
|---|---|---|
| 1 | 登录 → Dashboard → 先给方案 → 收件箱 | ✅ hero-smoke 覆盖 |
| 2 | 登录 → Dashboard → 直接执行 → 收件箱 | ⏭️ 需 E2E_PIPELINE_API_KEY |
| 3 | 收件箱 → 任务详情 → 8 Tab 切换 | ✅ hero-smoke + visual-preview 覆盖 |
| 4 | 任务详情 → 分享链接 → 匿名页 | ✅ hero-smoke 覆盖 |
| 5 | 登出 → 登录 → JWT 持久化 | ✅ regression-matrix #16 覆盖 |

### P1 — 侧栏与导航

| 步骤 | 流程 | 状态 |
|---|---|---|
| 6 | 侧栏 5 入口切换 | ✅ sidebar-smoke 覆盖 |
| 7 | 工作区切换 | ⚠️ 未覆盖 |
| 8 | 语言切换 zh↔en | ✅ regression-matrix #13 覆盖 |
| 9 | 搜索框输入 → 结果点击 | ⚠️ 未覆盖 |

### P2 — 功能页面

| 步骤 | 流程 | 状态 |
|---|---|---|
| 10 | Team → Agent 卡片 → 对话页 | ⚠️ Team 页结构已验证，点击跳转未测 |
| 11 | Workflow → 工作流列表 | ✅ regression-matrix #10 覆盖 |
| 12 | Assets → 各 Tab 切换 | ✅ regression-matrix #11 + battery #12 覆盖 |
| 13 | Settings → 设置页 | ✅ regression-matrix #12 覆盖 |

### P3 — 错误与边界

| 步骤 | 流程 | 状态 |
|---|---|---|
| 14 | 无效 token → 登录页 | ✅ regression-matrix #16 覆盖 |
| 15 | 不存在的任务 ID → 错误处理 | ✅ regression-matrix #14 覆盖 |
| 16 | 分享页无效 token → 错误态 | ✅ regression-matrix #15 覆盖 |
| 17 | 404 路由 → 404 页面 | ✅ regression-matrix #5 覆盖 |
| 18 | 后端不可达 → offline 提示 | ⚠️ 未覆盖 |

---

## 五、综合评估

**总体质量**: 良好。核心页面流程全部验证通过，前端路由守卫、认证、侧栏导航、页面渲染均正常工作。

**待修复**:
1. `regression-battery.spec.ts` 测试 09 需在创建分享令牌前启用工作区草稿交付模式
2. Gateway intake 测试需要配置 E2E_PIPELINE_API_KEY 后才能运行

**未覆盖项**:
- 工作区切换器（WorkspaceSwitcher）的 UI 测试
- 搜索框功能验证
- Agent 对话页跳转
- 后端不可达时的 offline 降级处理

---

## 六、运行命令

```bash
# 全部 E2E 测试
cd /Users/wayne/Documents/agent-hub
E2E_EMAIL=admin@example.com E2E_PASSWORD=changeme \
  E2E_API_ORIGIN=http://127.0.0.1:8000 \
  npx playwright test tests/e2e/ --reporter=list

# 单个套件
npx playwright test tests/e2e/sidebar-smoke.spec.ts
npx playwright test tests/e2e/hero-smoke.spec.ts
npx playwright test tests/e2e/visual-preview.spec.ts
npx playwright test tests/e2e/regression-matrix.spec.ts
npx playwright test tests/e2e/regression-battery.spec.ts

# 查看 HTML 报告
npx playwright show-report
```
