import { execSync } from 'node:child_process'
import type { APIRequestContext, Page } from '@playwright/test'

/** UI 登录并等待侧栏（Element Plus 密码框需按 label/placeholder 定位）。 */
export async function loginThroughUi(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/#/login')
  await page.getByTestId('login-email').fill(email)
  const passwordInput = page
    .getByPlaceholder(/请输入密码|Enter password/i)
    .or(page.getByLabel(/密码|Password/i))
  await passwordInput.fill(password)
  await page.locator('.login-form button[type="submit"]').click()
  await page.locator('aside.app-sidebar').waitFor({ state: 'visible', timeout: 30_000 })
}

/** 注入 JWT，跳过 UI 登录（仍可用于后续页面流程）。 */
export async function seedAuthToken(page: Page, token: string): Promise<void> {
  await page.addInitScript((t) => {
    localStorage.setItem('agent-hub-token', t)
  }, token)
}

/** 准备 smoke 工作区（草稿交付）并返回 workspace_id。 */
export function prepareSmokeWorkspaceId(): string {
  const out = execSync('cd backend && python3 -m scripts.prepare_e2e_workspace', {
    stdio: 'pipe',
    encoding: 'utf-8',
  }).trim()
  if (!out) throw new Error('prepare_e2e_workspace returned empty workspace id')
  return out.split('\n').pop()!.trim()
}

/** @deprecated use prepareSmokeWorkspaceId in beforeAll */
export async function enableDraftDeliveryForSmoke(): Promise<string> {
  return prepareSmokeWorkspaceId()
}

const jsonHeaders = { 'Content-Type': 'application/json' } as const

export async function postJson(
  request: APIRequestContext,
  path: string,
  body: unknown,
  auth?: string,
): Promise<{ res: Awaited<ReturnType<APIRequestContext['post']>>; json: () => Promise<unknown> }> {
  const headers: Record<string, string> = { ...jsonHeaders }
  if (auth) headers.Authorization = `Bearer ${auth}`
  const res = await request.post(path, { headers, data: JSON.stringify(body) })
  return {
    res,
    json: async () => {
      try {
        return await res.json()
      } catch {
        return {}
      }
    },
  }
}

/** Login API → JWT for org-scoped pipeline + share/generate. */
export async function loginGetJwt(
  request: APIRequestContext,
  email: string,
  password: string,
): Promise<string> {
  const { res, json } = await postJson(request, '/api/auth/login', { email, password })
  if (!res.ok()) {
    const body = await json()
    throw new Error(`login failed ${res.status()}: ${JSON.stringify(body)}`)
  }
  const body = (await json()) as { access_token?: string }
  const tok = body.access_token
  if (!tok) throw new Error('login response missing access_token')
  return tok
}

export async function createPipelineTaskApi(
  request: APIRequestContext,
  jwt: string,
  payload: { title: string; description?: string; source?: string; workspace_id?: string },
): Promise<{ id: string; title: string }> {
  const { res, json } = await postJson(request, '/api/pipeline/tasks', payload, jwt)
  if (!res.ok()) {
    const body = await json()
    throw new Error(`create task failed ${res.status()}: ${JSON.stringify(body)}`)
  }
  const body = (await json()) as { task?: { id?: string; title?: string } }
  const id = body.task?.id
  if (!id) throw new Error('create task response missing task.id')
  return { id: String(id), title: String(body.task?.title ?? payload.title) }
}

/**
 * Best-effort delete of a pipeline task created by an E2E test. Swallows
 * all failures (auth gone, task already deleted, backend down) because
 * cleanup hooks must never mask the real test result.
 */
export async function deletePipelineTaskApi(
  request: APIRequestContext,
  jwt: string,
  taskId: string,
): Promise<void> {
  try {
    await request.delete(`/api/pipeline/tasks/${encodeURIComponent(taskId)}`, {
      headers: { Authorization: `Bearer ${jwt}` },
    })
  } catch {
    /* ignore — cleanup must be idempotent and silent */
  }
}

export async function generateShareTokenApi(
  request: APIRequestContext,
  jwt: string,
  taskId: string,
  ttlDays = 7,
): Promise<string> {
  const { res, json } = await postJson(
    request,
    '/api/share/generate',
    { task_id: taskId, ttl_days: ttlDays },
    jwt,
  )
  if (!res.ok()) {
    const body = await json()
    throw new Error(`share/generate failed ${res.status()}: ${JSON.stringify(body)}`)
  }
  const body = (await json()) as { token?: string }
  if (!body.token) throw new Error('share response missing token')
  return body.token
}
