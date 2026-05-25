/**
 * Hero Path smoke test — UI/API wiring only (no real LLM pipeline, no artifact quality).
 *
 * Covers: login → create task via REST → task detail tab → inbox deep-link → share page.
 *
 * For full delivery acceptance (PRD/UI/code/QA/deploy evidence), see
 * `backend/tests/test_hero_pipeline_acceptance.py` (real execute_stage + quality contract),
 * `backend/tests/test_hero_delivery_path.py` (state machine smoke; contract must NOT satisfy), and
 * `backend/tests/test_artifact_contract_quality.py` (anti-mock quality gates).
 */
import { test, expect } from '@playwright/test'
import {
  createPipelineTaskApi,
  deletePipelineTaskApi,
  generateShareTokenApi,
  loginGetJwt,
  loginThroughUi,
  prepareSmokeWorkspaceId,
} from './helpers'

const apiOrigin = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8000'
const email = process.env.E2E_EMAIL ?? 'admin@example.com'
const password = process.env.E2E_PASSWORD ?? 'changeme'

let smokeWorkspaceId = ''
// Tasks created during the suite, deleted in afterAll so the Inbox doesn't
// accumulate "执行中" zombies after every CI run.
const createdTaskIds: string[] = []

test.describe('Hero Path smoke（稳定版）', () => {
  test.beforeAll(async ({ request }) => {
    const res = await request.get(`${apiOrigin}/health`).catch(() => null)
    if (!res?.ok()) {
      test.skip(true, `后端不可达 ${apiOrigin}/health — 请先启动依赖与后端。`)
    }
    smokeWorkspaceId = prepareSmokeWorkspaceId()
  })

  test.afterAll(async ({ request }) => {
    if (!createdTaskIds.length) return
    try {
      const jwt = await loginGetJwt(request, email, password)
      for (const id of createdTaskIds) {
        await deletePipelineTaskApi(request, jwt, id)
      }
    } catch {
      /* cleanup is best-effort; never fail the suite because of it */
    } finally {
      createdTaskIds.length = 0
    }
  })

  test('登录 → 任务详情 → 收件箱 → 匿名分享页', async ({ page, context, browser, request }) => {
    test.setTimeout(180_000)

    const title = `E2E smoke ${Date.now()}`

    await page.goto('/#/login')
    await loginThroughUi(page, email, password)

    const jwtFromBrowser = await page.evaluate(() => localStorage.getItem('agent-hub-token'))
    expect(jwtFromBrowser).toBeTruthy()
    const jwt = jwtFromBrowser as string

    const { id: taskId, title: createdTitle } = await createPipelineTaskApi(request, jwt, {
      title,
      description: 'Playwright smoke：仅验证页面与 API 连通',
      source: 'e2e-smoke',
      workspace_id: smokeWorkspaceId,
    })
    createdTaskIds.push(taskId)
    expect(createdTitle).toContain('E2E smoke')

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
    await loginThroughUi(page, email, password)

    await page.goto('/#/')
    const phrase = `E2E intake ${Date.now()} 仅验证建单与跳转`
    await page.locator('.hero-input-row input').fill(phrase)
    await page.getByRole('button', { name: '直接执行' }).click()
    await expect(page).toHaveURL(/#\/pipeline\/task\/[a-f0-9-]+/i, { timeout: 120_000 })
    await expect(page.locator('.task-detail header h1')).toContainText(phrase.slice(0, 20))
  })
})
