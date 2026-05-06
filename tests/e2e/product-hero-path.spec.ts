/**
 * 全链路产品验收（不跑真实 LLM 流水线）
 *
 * 覆盖：Web 登录 → 创建任务（API，与 UI 同一 JWT/组织）→ 任务详情交付物 Tab
 *       → 收件箱直达 → 分享令牌 → 匿名访问分享页
 *
 * 控制台「一句话」走 gateway intake 会触发规划/流水线；稳定 CI 用 REST 建单。
 * 若要试真实 Hero 输入，另设 E2E_DASHBOARD_INTAKE=1 且配置 PIPELINE_API_KEY（见下方 test）。
 */
import { test, expect } from '@playwright/test'
import { createPipelineTaskApi, generateShareTokenApi } from './helpers'

const apiOrigin = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8000'
const email = process.env.E2E_EMAIL ?? 'admin@example.com'
const password = process.env.E2E_PASSWORD ?? 'changeme'

test.describe('全链路 Hero Path（稳定版）', () => {
  test.beforeAll(async ({ request }) => {
    const res = await request.get(`${apiOrigin}/health`).catch(() => null)
    if (!res?.ok()) {
      test.skip(true, `后端不可达 ${apiOrigin}/health — 请先启动依赖与后端。`)
    }
  })

  test('登录 → 任务详情 → 收件箱 → 匿名分享页', async ({ page, context, browser, request }) => {
    test.setTimeout(180_000)

    const title = `E2E 全链路 ${Date.now()}`

    await page.goto('/#/login')
    await page.locator('input[type="email"]').fill(email)
    await page.locator('input[type="password"]').fill(password)
    await page.locator('.login-form button[type="submit"]').click()
    await expect(page.locator('aside.app-sidebar')).toBeVisible({ timeout: 30_000 })

    const jwtFromBrowser = await page.evaluate(() => localStorage.getItem('agent-hub-token'))
    expect(jwtFromBrowser).toBeTruthy()
    const jwt = jwtFromBrowser as string

    const { id: taskId, title: createdTitle } = await createPipelineTaskApi(request, jwt, {
      title,
      description: 'Playwright 全链路验收用任务',
      source: 'e2e',
    })
    expect(createdTitle).toContain('E2E 全链路')

    await page.goto(`/#/pipeline/task/${taskId}`)
    await expect(page.locator('.task-detail header h1')).toContainText(title, { timeout: 30_000 })
    await expect(page.getByRole('tab', { name: '交付物' })).toBeVisible()
    await expect(page.locator('.task-artifact-tabs .completion-bar')).toBeVisible()

    await page.goto('/#/inbox?tab=running')
    await expect(page.locator('.inbox-view')).toBeVisible()
    await page.getByRole('row').filter({ hasText: title }).first().click()
    await expect(page).toHaveURL(new RegExp(`#/pipeline/task/${taskId}`))

    const shareToken = await generateShareTokenApi(request, jwt, taskId, 7)

    const anon = await browser.newContext({ locale: 'zh-CN' })
    const sharePage = await anon.newPage()
    await sharePage.goto(`/#/share/${shareToken}`)
    await expect(sharePage.getByText('Agent Hub · 任务分享')).toBeVisible({ timeout: 30_000 })
    await expect(sharePage.getByRole('heading', { level: 1 })).toContainText(title.slice(0, 24), {
      timeout: 15_000,
    })
    await anon.close()
  })
})

test.describe('可选：控制台一句话 intake（gateway）', () => {
  test.beforeAll(async ({ request }) => {
    const res = await request.get(`${apiOrigin}/health`).catch(() => null)
    if (!res?.ok()) {
      test.skip(true, `后端不可达 ${apiOrigin}/health`)
    }
    if (!process.env.E2E_DASHBOARD_INTAKE || process.env.E2E_DASHBOARD_INTAKE === '0') {
      test.skip(true, '设 E2E_DASHBOARD_INTAKE=1 且配置 E2E_PIPELINE_API_KEY（与后端 PIPELINE_API_KEY 一致）后启用')
    }
    if (!process.env.E2E_PIPELINE_API_KEY?.trim()) {
      test.skip(true, '缺少 E2E_PIPELINE_API_KEY')
    }
  })

  test('首页输入 → 直执行创建任务并跳进详情', async ({ page }) => {
    test.setTimeout(300_000)
    const pipelineKey = process.env.E2E_PIPELINE_API_KEY!.trim()

    await page.addInitScript((k) => {
      localStorage.setItem('agent-hub-pipeline-key', k)
    }, pipelineKey)

    await page.goto('/#/login')
    await page.locator('input[type="email"]').fill(email)
    await page.locator('input[type="password"]').fill(password)
    await page.locator('.login-form button[type="submit"]').click()
    await expect(page.locator('aside.app-sidebar')).toBeVisible({ timeout: 30_000 })

    await page.goto('/#/')
    const phrase = `E2E intake ${Date.now()} 仅验证建单与跳转`
    await page.locator('.hero-input-row input').fill(phrase)
    await page.getByRole('button', { name: '直接执行' }).click()
    await expect(page).toHaveURL(/#\/pipeline\/task\/[a-f0-9-]+/i, { timeout: 120_000 })
    await expect(page.locator('.task-detail header h1')).toContainText(phrase.slice(0, 20))
  })
})
