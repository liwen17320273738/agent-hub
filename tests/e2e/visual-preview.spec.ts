/** Verify UI mockup + architecture diagram tabs load raw HTML (not broken img / Agent Hub shell). */
import { test, expect } from '@playwright/test'
import { loginThroughUi } from './helpers'

const taskId = process.env.E2E_VISUAL_TASK_ID ?? 'e4a7269e-faaf-4742-888c-cbc6675dcd03'
const email = process.env.E2E_EMAIL ?? 'admin@example.com'
const password = process.env.E2E_PASSWORD ?? 'changeme'

test('交付物 Tab：UI 设计稿与架构图 iframe 正常渲染', async ({ page }) => {
  test.setTimeout(120_000)

  await loginThroughUi(page, email, password)
  await page.goto(`/#/pipeline/task/${taskId}`)
  await expect(page.locator('.task-detail header h1')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('tab', { name: '交付物' })).toBeVisible()

  await page.getByRole('tab', { name: 'UI 设计稿' }).click()
  const uiFrame = page.locator('.ui-mockup-view iframe.prototype-frame')
  await expect(uiFrame).toBeVisible({ timeout: 15_000 })
  const uiSrc = await uiFrame.getAttribute('src')
  expect(uiSrc).toMatch(/worktree\/raw\/ui_mockups\//)
  expect(uiSrc).not.toMatch(/\/worktree\/ui_mockups\//)

  await page.getByRole('tab', { name: '架构图' }).click()
  const archFrame = page.locator('.arch-diagram-frame')
  await expect(archFrame).toBeVisible({ timeout: 15_000 })
  const archSrc = await archFrame.getAttribute('src')
  expect(archSrc).toMatch(/worktree\/raw\/architecture_diagrams\//)

  await page.screenshot({ path: 'test-results/visual-preview-tabs.png', fullPage: true })
})
