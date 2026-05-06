/**
 * 15+ 场景回归：路由守卫、登录校验、主视图、语言、异常页、分享与登出。
 * 不依赖真实 LLM；需本地 Vite（playwright webServer）+ 可选后端。
 */
import { test, expect } from '@playwright/test'
import { loginThroughUi } from './helpers'

const apiOrigin = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8000'
const email = process.env.E2E_EMAIL ?? 'admin@example.com'
const password = process.env.E2E_PASSWORD ?? 'changeme'

test.describe('矩阵 A：无需后端（仅前端路由与登录表单）', () => {
  test('登录页展示品牌与表单', async ({ page }) => {
    await page.goto('/#/login')
    await expect(page.locator('.login-card h1')).toContainText(/Agent Hub/i)
    await expect(page.locator('input[type="email"]')).toBeVisible()
    await expect(page.locator('input[type="password"]')).toBeVisible()
    await expect(page.locator('.login-form button[type="submit"]')).toBeVisible()
  })

  test('空邮箱密码提交显示客户端校验', async ({ page }) => {
    await page.goto('/#/login')
    await page.locator('input[type="email"]').fill('')
    await page.locator('input[type="password"]').fill('')
    await page.locator('.login-form button[type="submit"]').click()
    await expect(page.locator('.login-card .error-text')).toContainText('请输入邮箱和密码', { timeout: 5000 })
  })

  test('未登录访问收件箱重定向到登录并保留回程路径（sessionStorage）', async ({ page }) => {
    await page.goto('/#/inbox')
    await expect(page).toHaveURL(/#\/login/, { timeout: 15_000 })
    const stored = await page.evaluate(() => sessionStorage.getItem('agent-hub-login-redirect'))
    expect(stored).toBe('/inbox')
  })

  test('未登录访问控制台重定向到登录', async ({ page }) => {
    await page.goto('/#/')
    await expect(page).toHaveURL(/#\/login/)
  })

  test('未知路由显示 404 页', async ({ page }) => {
    await page.goto('/#/no-such-route-matrix-test')
    await expect(page.locator('.not-found-page h1')).toHaveText('404')
  })
})

test.describe('矩阵 B：需后端（健康检查）', () => {
  test.beforeEach(async ({ request }) => {
    const ok = await request.get(`${apiOrigin}/health`).catch(() => null)
    if (!ok?.ok()) {
      test.skip(true, `后端不可达 ${apiOrigin}/health`)
    }
  })

  test('错误密码登录显示错误提示', async ({ page }) => {
    await page.goto('/#/login')
    await page.locator('input[type="email"]').fill(email)
    await page.locator('input[type="password"]').fill(`wrong-${Date.now()}`)
    await page.locator('.login-form button[type="submit"]').click()
    await expect(page.locator('.login-card .error-text')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('aside.app-sidebar')).toHaveCount(0)
  })

  test('登录成功：控制台 Hero 与快捷按钮', async ({ page }) => {
    await loginThroughUi(page, email, password)
    await page.goto('/#/')
    await expect(page.locator('.dashboard .hero-input-row input')).toBeVisible()
    await expect(page.getByRole('button', { name: '直接执行' })).toBeVisible()
  })

  test('登录成功：收件箱页面结构', async ({ page }) => {
    await loginThroughUi(page, email, password)
    await page.goto('/#/inbox')
    await expect(page.locator('.inbox-view')).toBeVisible()
    await expect(page.locator('.inbox-view h1')).toBeVisible()
  })

  test('登录成功：团队页 Agent 网格容器', async ({ page }) => {
    await loginThroughUi(page, email, password)
    await page.goto('/#/team')
    await expect(page.locator('.team-view')).toBeVisible()
    await expect(page.locator('.team-view .agent-grid')).toBeVisible()
  })

  test('登录成功：工作流页 Tab', async ({ page }) => {
    await loginThroughUi(page, email, password)
    await page.goto('/#/workflow')
    await expect(page.locator('.workflow-view')).toBeVisible()
    await expect(page.locator('.workflow-view .el-tabs')).toBeVisible()
  })

  test('登录成功：资产页 Tab', async ({ page }) => {
    await loginThroughUi(page, email, password)
    await page.goto('/#/assets')
    await expect(page.locator('.assets-view')).toBeVisible()
    await expect(page.locator('.assets-view .el-tabs')).toBeVisible()
  })

  test('登录成功：设置页', async ({ page }) => {
    await loginThroughUi(page, email, password)
    await page.goto('/#/settings')
    await expect(page.locator('.settings-page')).toBeVisible()
    await expect(page.locator('.settings-page .page-header h1')).toBeVisible()
  })

  test('侧栏语言切换为 English 后导航显示 Home', async ({ page }) => {
    await loginThroughUi(page, email, password)
    await page.locator('.sidebar-footer .lang-toggle').click()
    await page.getByRole('menuitem', { name: 'English' }).click()
    await expect(page.locator('aside .sidebar-nav a[href="#/"]')).toContainText('Home', { timeout: 10_000 })
  })

  test('无效任务 ID：详情页展示加载失败与重试', async ({ page }) => {
    await loginThroughUi(page, email, password)
    const fakeId = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d'
    await page.goto(`/#/pipeline/task/${fakeId}`)
    await expect(page.locator('.task-loading .error-text')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
  })

  test('无效分享令牌：分享页错误态', async ({ page }) => {
    await page.goto('/#/share/invalid-token-not-signed')
    await expect(page.locator('.share-page .share-error')).toBeVisible({ timeout: 30_000 })
  })

  test('清除本地令牌后受保护路由回到登录页（非企业版无侧栏退出按钮）', async ({ page }) => {
    await loginThroughUi(page, email, password)
    await page.evaluate(() => localStorage.removeItem('agent-hub-token'))
    await page.reload()
    await page.goto('/#/')
    await expect(page).toHaveURL(/#\/login/, { timeout: 15_000 })
    await expect(page.locator('.login-card')).toBeVisible()
  })
})
