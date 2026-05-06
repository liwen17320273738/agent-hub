import { test, expect } from '@playwright/test'

const apiOrigin = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8000'
const email = process.env.E2E_EMAIL ?? 'admin@example.com'
const password = process.env.E2E_PASSWORD ?? 'changeme'

/** After the last assertion, keep the window open this many ms (headed demo). */
function endPauseMs(): number {
  const raw = process.env.E2E_PAUSE_MS
  if (raw === undefined || raw === '') return 0
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : 0
}

test.describe('登录与五入口侧栏', () => {
  test.beforeAll(async ({ request }) => {
    const res = await request.get(`${apiOrigin}/health`).catch(() => null)
    if (!res?.ok()) {
      test.skip(
        true,
        `后端不可达 ${apiOrigin}/health — 请先启动数据库、Redis 与后端（例如 make dev 或 pnpm dev:full）。`,
      )
    }
  })

  test('登录后可走 控制台 → 收件箱 → 团队 → 工作流 → 资产', async ({ page }) => {
    await page.goto('/#/login')
    await expect(page.locator('.login-card h1')).toContainText(/Agent Hub/i)

    await page.locator('input[type="email"]').fill(email)
    await page.locator('input[type="password"]').fill(password)
    await page.locator('.login-form button[type="submit"]').click()

    await expect(page.locator('aside.app-sidebar')).toBeVisible({ timeout: 30_000 })

    const nav = page.locator('aside .sidebar-nav')

    await nav.locator('a[href="#/"]').click()
    await expect(page).toHaveURL(/#\/$/)

    await nav.locator('a[href="#/inbox"]').click()
    await expect(page).toHaveURL(/#\/inbox/)

    await nav.locator('a[href="#/team"]').click()
    await expect(page).toHaveURL(/#\/team/)

    await nav.locator('a[href="#/workflow"]').click()
    await expect(page).toHaveURL(/#\/workflow/)

    await nav.locator('a[href="#/assets"]').click()
    await expect(page).toHaveURL(/#\/assets/)

    const pause = endPauseMs()
    if (pause > 0) {
      await page.waitForTimeout(pause)
    }
  })
})
