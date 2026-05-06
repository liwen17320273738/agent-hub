/**
 * API 与集成补集（与 regression-matrix 重叠的 UI 用例已移除，避免 serial + 长套 UI 拖垮 dev server）。
 */
import { test, expect } from '@playwright/test'
import { loginGetJwt, postJson, createPipelineTaskApi, generateShareTokenApi, loginThroughUi } from './helpers'

const apiOrigin = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8000'
const email = process.env.E2E_EMAIL ?? 'admin@example.com'
const password = process.env.E2E_PASSWORD ?? 'changeme'

test.describe('回归电池（API + 关键集成）', () => {
  test.beforeAll(async ({ request }) => {
    const res = await request.get(`${apiOrigin}/health`).catch(() => null)
    if (!res?.ok()) {
      test.skip(true, `后端不可达 ${apiOrigin}/health`)
    }
  })

  test('01 GET /health 返回 200', async ({ request }) => {
    const res = await request.get(`${apiOrigin}/health`)
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body).toHaveProperty('status')
  })

  test('02 GET /api/pipeline/health 经前端代理可用', async ({ request }) => {
    const res = await request.get('/api/pipeline/health')
    expect(res.ok()).toBeTruthy()
  })

  test('03 未授权 POST /api/pipeline/tasks → 401', async ({ request }) => {
    const { res } = await postJson(request, '/api/pipeline/tasks', {
      title: 'unauth',
      source: 'e2e',
    })
    expect(res.status()).toBe(401)
  })

  test('04 未授权 POST /api/share/generate → 401', async ({ request }) => {
    const { res } = await postJson(request, '/api/share/generate', {
      task_id: '00000000-0000-0000-0000-000000000001',
      ttl_days: 7,
    })
    expect(res.status()).toBe(401)
  })

  test('05 JWT GET /api/auth/me 成功', async ({ request }) => {
    const jwt = await loginGetJwt(request, email, password)
    const res = await request.get('/api/auth/me', {
      headers: { Authorization: `Bearer ${jwt}` },
    })
    expect(res.ok()).toBeTruthy()
    const me = await res.json()
    expect(me.email).toBeTruthy()
  })

  test('06 JWT GET /api/pipeline/tasks 返回列表', async ({ request }) => {
    const jwt = await loginGetJwt(request, email, password)
    const res = await request.get('/api/pipeline/tasks', {
      headers: { Authorization: `Bearer ${jwt}` },
    })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(Array.isArray(body.tasks)).toBeTruthy()
  })

  test('07 游客访问收件箱 → 登录页并写入回程 sessionStorage', async ({ page }) => {
    await page.goto('/#/inbox')
    await expect(page).toHaveURL(/#\/login/, { timeout: 15_000 })
    const stored = await page.evaluate(() => sessionStorage.getItem('agent-hub-login-redirect'))
    expect(stored).toBe('/inbox')
  })

  test('08 伪造分享令牌页 → 错误态', async ({ page }) => {
    await page.goto('/#/share/invalid-fake-token-not-signed')
    await expect(page.locator('.share-page .share-error')).toBeVisible({ timeout: 30_000 })
  })

  test('09 建单 → 分享令牌 → 匿名页可见标题', async ({ page, browser, request }) => {
    await loginThroughUi(page, email, password)
    const jwt = await page.evaluate(() => localStorage.getItem('agent-hub-token'))
    expect(jwt).toBeTruthy()
    const title = `E2E 电池 ${Date.now()}`
    const { id } = await createPipelineTaskApi(request, jwt as string, { title, source: 'e2e-battery' })
    const shareTok = await generateShareTokenApi(request, jwt as string, id, 7)

    const anon = await browser.newContext({ locale: 'zh-CN' })
    const p2 = await anon.newPage()
    await p2.goto(`/#/share/${shareTok}`)
    await expect(p2.locator('.share-header h1')).toContainText(title.slice(0, 16), { timeout: 20_000 })
    await anon.close()
  })
})
