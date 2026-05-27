/**
 * 页面流程测试 — 关键用户旅程（不依赖真实 LLM pipeline，仅验证 UI 交互与导航）。
 *
 * 分为两区：
 *   无后端区 — 纯前端路由、登录表单、分享页错误态、404 页
 *   需后端区 — 登录后页面导航、Tab 切换、跨页流程（后端不可达时整体跳过）
 */
import { test, expect } from '@playwright/test'
import { loginThroughUi, loginGetJwt, createPipelineTaskApi } from './helpers'

const apiOrigin = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8000'
const email = process.env.E2E_EMAIL ?? 'admin@example.com'
const password = process.env.E2E_PASSWORD ?? 'changeme'

/* ── 辅助 ── */
async function backendUp(request: Parameters<Parameters<typeof test>[1]>[0]['request']): Promise<boolean> {
  const ok = await request.get(`${apiOrigin}/health`).catch(() => null)
  return ok?.ok() === true
}

async function login(page: Parameters<Parameters<typeof test>[1]>[0]['page']): Promise<void> {
  await loginThroughUi(page, email, password)
}

/* ══════════════════════════════════════════════════════════════════
   无后端区 — 纯前端路由与表单 (6 tests)
   ══════════════════════════════════════════════════════════════════ */
test.describe('无后端：路由守卫与错误态', () => {
  test('登录页渲染品牌与表单', async ({ page }) => {
    await page.goto('/#/login')
    await expect(page.locator('.login-card h1')).toContainText(/Agent Hub/i)
    await expect(page.getByTestId('login-email')).toBeVisible()
    await expect(page.locator('input[type="password"]')).toBeVisible()
    await expect(page.locator('.login-form button[type="submit"]')).toBeVisible()
  })

  test('空表单提交 → 客户端校验文案', async ({ page }) => {
    await page.goto('/#/login')
    await page.locator('.login-form button[type="submit"]').click()
    await expect(page.locator('.login-card .error-text')).toContainText(/请输入邮箱/, { timeout: 5000 })
  })

  test('未登录访问 /inbox → /login 并写入回程路径', async ({ page }) => {
    await page.goto('/#/inbox')
    await expect(page).toHaveURL(/#\/login/, { timeout: 15000 })
    const stored = await page.evaluate(() => sessionStorage.getItem('agent-hub-login-redirect'))
    expect(stored).toBe('/inbox')
  })

  test('未登录访问 / → /login', async ({ page }) => {
    await page.goto('/#/')
    await expect(page).toHaveURL(/#\/login/, { timeout: 15000 })
  })

  test('404 页面', async ({ page }) => {
    await page.goto('/#/no-such-route-page-flow-test')
    await expect(page.locator('.not-found-page h1')).toHaveText('404')
  })

  test('无效分享 token → 错误结果页', async ({ page }) => {
    await page.goto('/#/share/invalid-token-not-signed')
    await expect(page.locator('.share-page .share-error')).toBeVisible({ timeout: 30000 })
  })
})

/* ══════════════════════════════════════════════════════════════════
   需后端区 — 登录后的交互流程 (17 tests)
   ══════════════════════════════════════════════════════════════════ */
test.describe('需后端：控制台 Hero', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('直接执行 → 跳转到任务详情', async ({ page }) => {
    test.setTimeout(120000)
    await login(page)
    await page.goto('/#/')
    await expect(page.locator('.dashboard .hero-input-row input, .dashboard .hero-input-row .el-input__inner')).toBeVisible()
    const phrase = `E2E flow exec ${Date.now()}`
    await page.locator('.dashboard .hero-input-row input, .dashboard .hero-input-row .el-input__inner').fill(phrase)
    await page.getByRole('button', { name: '直接执行' }).click()
    await expect(page).toHaveURL(/#\/pipeline\/task\/[a-f0-9-]+/i, { timeout: 90000 })
    await expect(page.locator('.task-detail header h1')).toContainText(phrase.slice(0, 20), { timeout: 30000 })
  })

  test('模板芯片填充输入框（如有）', async ({ page }) => {
    await login(page)
    await page.goto('/#/')
    const chips = page.locator('.hero-templates .tpl-chip')
    if (await chips.count() === 0) { test.skip(true, '无模板芯片'); return }
    await chips.first().click()
    expect((await page.locator('.hero-input-row input, .hero-input-row .el-input__inner').inputValue()).length).toBeGreaterThan(0)
  })
})

test.describe('需后端：收件箱', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('统计卡片切换 Tab + 行点击跳详情', async ({ page }) => {
    await login(page)
    await page.goto('/#/inbox')
    await expect(page.locator('.inbox-view')).toBeVisible({ timeout: 15000 })

    // 切换所有统计卡片
    for (const t of ['pending', 'running', 'done', 'failed', 'cancelled']) {
      const card = page.locator(`.stat-card.${t}`)
      if (await card.isVisible()) {
        await card.click()
        await expect(card).toHaveAttribute('aria-pressed', 'true')
      }
    }

    // 点击 running tab 的行
    await page.goto('/#/inbox?tab=running')
    await expect(page.locator('.inbox-view')).toBeVisible({ timeout: 15000 })
    const rows = page.locator('.inbox-view tbody tr')
    await rows.first().waitFor({ timeout: 15000 }).catch(() => { /* 可能无行 */ })
    if (!(await rows.first().isVisible())) { test.skip(true, 'running 无任务行'); return }
    await rows.first().click()
    await expect(page).toHaveURL(/#\/pipeline\/task\/[a-f0-9-]+/i, { timeout: 15000 })
  })
})

test.describe('需后端：团队页', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('Agent 网格 → 点击进入 Chat + 标签可见', async ({ page }) => {
    await login(page)
    await page.goto('/#/team')
    await expect(page.locator('.team-view .agent-grid')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('.agent-tag').first()).toBeVisible({ timeout: 10000 })

    const cards = page.locator('.agent-card')
    if (await cards.count() === 0) { test.skip(true, '无 Agent 卡片'); return }
    await cards.first().click()
    await expect(page).toHaveURL(/#\/agent\//, { timeout: 15000 })
  })
})

test.describe('需后端：工作流', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('三个 Tab 可切换 + 运行按钮默认禁用', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow')
    await expect(page.locator('.workflow-view .el-tabs')).toBeVisible({ timeout: 15000 })

    const tabs = page.locator('.workflow-view .el-tabs__item')
    expect(await tabs.count()).toBeGreaterThanOrEqual(2)
    for (let i = 0; i < await tabs.count(); i++) {
      const tab = tabs.nth(i)
      if (!(await tab.textContent())?.trim()) continue
      await tab.click()
      await expect(tab).toHaveClass(/is-active/)
    }

    // 运行 tab 按钮禁用
    await page.locator('.workflow-view .el-tabs__item').filter({ hasText: /运行|run/i }).click()
    const runBtn = page.getByRole('button', { name: /运行|run/i })
    await expect(runBtn).toBeVisible({ timeout: 5000 })
    await expect(runBtn).toBeDisabled()
  })
})

test.describe('需后端：资产中心', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('全部 Tab 遍历 + relay 面板', async ({ page }) => {
    await login(page)
    await page.goto('/#/assets')
    await expect(page.locator('.assets-view .el-tabs')).toBeVisible({ timeout: 15000 })

    const tabItems = page.locator('.assets-view .el-tabs__item')
    expect(await tabItems.count()).toBeGreaterThanOrEqual(4)
    for (let i = 0; i < await tabItems.count(); i++) {
      const tab = tabItems.nth(i)
      if (!(await tab.textContent())?.trim()) continue
      await tab.click()
      await page.waitForTimeout(200)
      const hasContent = await page.locator('.assets-view .asset-action, .assets-view .relay-panel, .assets-view .tab-lead, .assets-view .el-empty').first().isVisible({ timeout: 3000 }).catch(() => false)
      expect(hasContent).toBe(true)
    }

    // relay 面板
    await page.goto('/#/assets?tab=relay')
    await expect(page.locator('.relay-panel')).toBeVisible({ timeout: 20000 })
    await expect(page.locator('.relay-panel').getByRole('button', { name: /创建/ })).toBeVisible()
  })
})

test.describe('需后端：任务详情', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('主 Tab + 交付物子 Tab 切换', async ({ page, request }) => {
    test.setTimeout(120000)
    await login(page)
    const jwt = await loginGetJwt(request, email, password)
    const { id: taskId } = await createPipelineTaskApi(request, jwt, {
      title: `E2E detail ${Date.now()}`, source: 'e2e',
    })
    await page.goto(`/#/pipeline/task/${taskId}`)
    await expect(page.locator('.task-detail header h1')).toBeVisible({ timeout: 20000 })

    for (const name of ['交付物', '概览', '流程泳道', '交付文档']) {
      const tab = page.getByRole('tab', { name })
      if (await tab.isVisible()) {
        await tab.click()
        await page.waitForTimeout(200)
        await expect(tab).toHaveAttribute('aria-selected', 'true')
      }
    }

    await page.getByRole('tab', { name: '交付物' }).click()
    await page.waitForTimeout(300)
    const artTabs = page.locator('.task-artifact-tabs .el-tabs__item')
    expect(await artTabs.count(), '交付物子 Tab 不足').toBeGreaterThanOrEqual(4)
  })

  test('无效任务 ID → 加载失败 + 重试', async ({ page }) => {
    await login(page)
    await page.goto('/#/pipeline/task/a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d')
    await expect(page.locator('.task-loading .error-text')).toBeVisible({ timeout: 30000 })
    await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
  })
})

test.describe('需后端：设置页', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('设置卡片 + 模型配置列表', async ({ page }) => {
    await login(page)
    await page.goto('/#/settings')
    await expect(page.locator('.settings-page .page-header h1')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('.settings-card').first()).toBeVisible()
    expect(await page.locator('.profile-item').count()).toBeGreaterThanOrEqual(1)
  })
})

test.describe('需后端：侧栏语言切换', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('中英切换 + localStorage 持久化', async ({ page }) => {
    await login(page)
    // zh → en
    await page.locator('.sidebar-footer .lang-toggle').click()
    await page.getByRole('menuitem', { name: 'English' }).click()
    await expect(page.locator('aside .sidebar-nav a[href="#/"]')).toContainText('Home', { timeout: 10000 })

    // en → zh 回切
    await page.locator('.sidebar-footer .lang-toggle').click()
    await page.getByRole('menuitem', { name: '中文' }).click()
    await expect(page.locator('aside .sidebar-nav a[href="#/"]')).toContainText('控制台', { timeout: 10000 })

    // 持久化
    await page.locator('.sidebar-footer .lang-toggle').click()
    await page.getByRole('menuitem', { name: 'English' }).click()
    await page.waitForTimeout(300)
    expect(await page.evaluate(() => localStorage.getItem('agent-hub-lang'))).toBe('en')
    await page.reload()
    await expect(page.locator('aside .sidebar-nav a[href="#/"]')).toContainText('Home', { timeout: 15000 })
  })
})

test.describe('需后端：跨页导航', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('收件箱→详情→后退→收件箱 + 侧栏回控制台 + 五入口连续点击', async ({ page }) => {
    await login(page)
    await page.goto('/#/inbox?tab=running')
    await expect(page.locator('.inbox-view')).toBeVisible({ timeout: 15000 })

    // 行点击 → 详情 → 后退
    const rows = page.locator('.inbox-view tbody tr')
    await rows.first().waitFor({ timeout: 15000 }).catch(() => { /* 可能无行 */ })
    if (await rows.first().isVisible()) {
      await rows.first().click()
      await expect(page).toHaveURL(/#\/pipeline\/task\/[a-f0-9-]+/i, { timeout: 15000 })
      await page.goBack()
      await expect(page.locator('.inbox-view')).toBeVisible({ timeout: 15000 })
    }

    // 侧栏回控制台
    await page.locator('aside .sidebar-nav a[href="#/"]').click()
    await expect(page).toHaveURL(/#\/$/)
    await expect(page.locator('.dashboard')).toBeVisible()

    // 五入口连续点击不崩溃
    const nav = page.locator('aside .sidebar-nav')
    for (const { href, view } of [
      { href: '#/', view: '.dashboard' },
      { href: '#/inbox', view: '.inbox-view' },
      { href: '#/team', view: '.team-view' },
      { href: '#/workflow', view: '.workflow-view' },
      { href: '#/assets', view: '.assets-view' },
    ]) {
      await nav.locator(`a[href="${href}"]`).click()
      await expect(page.locator(view)).toBeVisible({ timeout: 15000 })
    }
  })
})
