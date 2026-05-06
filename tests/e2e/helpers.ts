import type { APIRequestContext, Page } from '@playwright/test'

/** UI 登录并等待侧栏（与现有 spec 相同 JWT 流程）。 */
export async function loginThroughUi(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/#/login')
  await page.locator('input[type="email"]').fill(email)
  await page.locator('input[type="password"]').fill(password)
  await page.locator('.login-form button[type="submit"]').click()
  await page.locator('aside.app-sidebar').waitFor({ state: 'visible', timeout: 30_000 })
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
  payload: { title: string; description?: string; source?: string },
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
