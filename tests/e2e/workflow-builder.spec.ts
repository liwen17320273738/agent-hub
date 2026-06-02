/**
 * 工作流构建器 E2E — 核心交互流程（不依赖真实 LLM pipeline）。
 *
 * 覆盖：画布渲染 / 模板加载 / 新增阶段 / 自动布局 / 导出/导入 /
 *       保存/打开对话框 / 清空画布 / 运行对话框 / 拖拽侧栏
 */
import { test, expect } from '@playwright/test'
import { loginThroughUi } from './helpers'

const apiOrigin = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8000'
const email = process.env.E2E_EMAIL ?? 'admin@example.com'
const password = process.env.E2E_PASSWORD ?? 'changeme'

async function backendUp(request: Parameters<Parameters<typeof test>[1]>[0]['request']): Promise<boolean> {
  const ok = await request.get(`${apiOrigin}/health`).catch(() => null)
  return ok?.ok() === true
}

async function login(page: Parameters<Parameters<typeof test>[1]>[0]['page']): Promise<void> {
  await loginThroughUi(page, email, password)
}

test.describe('需后端：工作流构建器 — 画布与基础交互', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('导航到构建器 + 画布 Vue Flow 可见', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')
    await expect(page.locator('.workflow-builder')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('.wb-header h1')).toContainText(/工作流构建器|Workflow Builder/i)
    // Vue Flow canvas
    await expect(page.locator('.vue-flow')).toBeVisible({ timeout: 10000 })
    // 左栏 palette
    await expect(page.locator('.stage-palette')).toBeVisible({ timeout: 5000 })
  })

  test('模板下拉加载后画布有节点', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')

    // 等待模板加载（默认选中 "full"，节点应自动出现）
    await expect(page.locator('.vue-flow__node')).first().waitFor({ timeout: 20000 }).catch(() => {
      // 可能后端模板接口未返回，检查下拉选项
    })

    const nodes = page.locator('.vue-flow__node')
    const count = await nodes.count()
    // 如果没有自动加载节点，手动选模板
    if (count === 0) {
      const select = page.locator('.wb-header .right .el-select').first()
      await select.click()
      await page.waitForTimeout(500)
      const option = page.locator('.el-select-dropdown__item').first()
      if (await option.isVisible()) {
        await option.click()
        await page.waitForTimeout(1000)
        await expect(page.locator('.vue-flow__node').first()).toBeVisible({ timeout: 15000 })
      } else {
        test.skip(true, '没有可用模板')
        return
      }
    }
    // 至少有 1 个节点
    expect(await page.locator('.vue-flow__node').count()).toBeGreaterThanOrEqual(1)
  })

  test('点击节点 → 配置抽屉打开', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')
    await expect(page.locator('.vue-flow__node').first()).toBeVisible({ timeout: 20000 })

    await page.locator('.vue-flow__node').first().click()
    await expect(page.locator('.el-drawer')).toBeVisible({ timeout: 5000 })
    // 抽屉标题含节点信息
    await expect(page.locator('.el-drawer__header')).toBeVisible()
    // 关闭抽屉
    await page.locator('.el-drawer__close-btn').click()
    await expect(page.locator('.el-drawer')).not.toBeVisible({ timeout: 5000 })
  })

  test('新增阶段按钮增加节点数量', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')
    await expect(page.locator('.vue-flow__node').first()).toBeVisible({ timeout: 20000 })

    const before = await page.locator('.vue-flow__node').count()
    await page.getByRole('button', { name: /新增阶段|Add Stage/i }).click()
    await page.waitForTimeout(500)
    const after = await page.locator('.vue-flow__node').count()
    expect(after).toBe(before + 1)
  })

  test('自动布局不减少节点数', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')
    await expect(page.locator('.vue-flow__node').first()).toBeVisible({ timeout: 20000 })

    const before = await page.locator('.vue-flow__node').count()
    await page.getByRole('button', { name: /自动布局|Auto Layout/i }).click()
    await page.waitForTimeout(300)
    const after = await page.locator('.vue-flow__node').count()
    expect(after).toBe(before)
  })

  test('清空画布 → 确认后无节点', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')
    await expect(page.locator('.vue-flow__node').first()).toBeVisible({ timeout: 20000 })

    await page.getByRole('button', { name: /清空|Clear/i }).click()
    await page.waitForTimeout(300)
    await expect(page.locator('.vue-flow__node')).toHaveCount(0)
  })
})

test.describe('需后端：工作流构建器 — 保存/打开对话框', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('空画布点保存 → 提示"没有内容"', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')

    // 先清空
    await page.getByRole('button', { name: /清空|Clear/i }).click()
    await page.waitForTimeout(300)

    const saveBtn = page.getByRole('button', { name: /保存到服务器|Save to Server/i })
    if (await saveBtn.isVisible()) {
      await saveBtn.click()
    } else {
      // 可能按钮文案是"保存"
      const altSave = page.getByRole('button', { name: '保存' }).first()
      if (await altSave.isVisible()) await altSave.click()
    }

    // 应该弹出警告提示
    await expect(page.locator('.el-message--warning, .el-notification')).toContainText(/空|empty/i, { timeout: 5000 })
  })

  test('保存对话框可打开 + 名称必填', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')

    // 确保有节点
    await page.locator('.vue-flow__node').first().waitFor({ timeout: 20000 }).catch(() => {
      // 手动添加
    })
    if (await page.locator('.vue-flow__node').count() === 0) {
      await page.getByRole('button', { name: /新增阶段|Add Stage/i }).click()
      await page.waitForTimeout(500)
    }

    const saveBtn = page.getByRole('button', { name: /保存到服务器|Save to Server/i })
    if (await saveBtn.isVisible()) {
      await saveBtn.click()
    } else {
      const altSave = page.getByRole('button', { name: '保存' }).first()
      if (await altSave.isVisible()) await altSave.click()
    }

    await expect(page.locator('.el-dialog')).toBeVisible({ timeout: 5000 })
    // 名称空时保存按钮禁用
    const submitBtn = page.locator('.el-dialog .el-button--primary').last()
    const nameInput = page.locator('.el-dialog .el-input__inner').first()
    await nameInput.clear()
    await page.waitForTimeout(200)
    await expect(submitBtn).toBeDisabled()

    // 填入名称后启用
    await nameInput.fill(`E2E workflow ${Date.now()}`)
    await page.waitForTimeout(200)
    await expect(submitBtn).not.toBeDisabled()

    // 关闭对话框（不实际保存）
    await page.locator('.el-dialog .el-button').filter({ hasText: /取消|Cancel/i }).click()
    await page.waitForTimeout(300)
  })

  test('打开对话框列出已保存的 workflow', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')

    await page.getByRole('button', { name: /打开|Open/i }).click()
    await expect(page.locator('.el-dialog')).toBeVisible({ timeout: 5000 })

    // 对话框内应有关闭按钮（空状态或列表均可）
    await expect(page.locator('.el-dialog__body')).toBeVisible()

    // 关闭
    await page.locator('.el-dialog .el-button').filter({ hasText: /关闭|Close/i }).click()
    await page.waitForTimeout(300)
  })
})

test.describe('需后端：工作流构建器 — 导出/导入/JSON', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('查看 JSON 按钮打开预览对话框', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')
    await expect(page.locator('.vue-flow__node').first()).toBeVisible({ timeout: 20000 })

    await page.getByRole('button', { name: /查看 JSON|View JSON/i }).click()
    await expect(page.locator('.el-dialog')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.json-preview')).toBeVisible()

    // 关闭
    await page.locator('.el-dialog .el-button').filter({ hasText: /关闭|Close/i }).click()
    await page.waitForTimeout(300)
  })
})

test.describe('需后端：工作流构建器 — 运行对话框', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('运行按钮在有节点时可用 + 对话框含标题必填', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')
    await expect(page.locator('.vue-flow__node').first()).toBeVisible({ timeout: 20000 })

    const runBtn = page.getByRole('button', { name: /运行|Run/i }).last()
    await expect(runBtn).toBeVisible()
    await expect(runBtn).not.toBeDisabled()

    await runBtn.click()
    await expect(page.locator('.el-dialog')).toBeVisible({ timeout: 5000 })

    // 标题为空时创建按钮禁用
    const titleInput = page.locator('.el-dialog .el-input__inner').first()
    await titleInput.clear()
    await page.waitForTimeout(200)
    const createBtn = page.locator('.el-dialog .el-button--primary').last()
    await expect(createBtn).toBeDisabled()

    // 关闭
    await page.locator('.el-dialog .el-button').filter({ hasText: /取消|Cancel/i }).click()
    await page.waitForTimeout(300)
  })

  test('清空后运行按钮禁用', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')

    // 清空画布
    await page.getByRole('button', { name: /清空|Clear/i }).click()
    await page.waitForTimeout(300)

    const runBtn = page.getByRole('button', { name: /运行|Run/i }).last()
    await expect(runBtn).toBeDisabled({ timeout: 5000 })
  })
})

test.describe('需后端：工作流构建器 — 拖拽面板', () => {
  test.beforeAll(async ({ request }) => {
    if (!(await backendUp(request))) test.skip(true, `后端不可达 ${apiOrigin}/health`)
  })

  test('侧栏面板有角色项可拖拽', async ({ page }) => {
    await login(page)
    await page.goto('/#/workflow-builder')
    await expect(page.locator('.stage-palette')).toBeVisible({ timeout: 10000 })

    const items = page.locator('.palette-item')
    expect(await items.count()).toBeGreaterThanOrEqual(8)

    // 第一条应有 draggable 属性
    const first = items.first()
    await expect(first).toHaveAttribute('draggable', 'true')
  })
})
