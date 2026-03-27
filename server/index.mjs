import { config as loadEnv } from 'dotenv'
import { fileURLToPath } from 'node:url'
import express from 'express'
import cookieSession from 'cookie-session'
import bcrypt from 'bcryptjs'
import { randomUUID } from 'node:crypto'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import { dirname, join } from 'node:path'
import { existsSync } from 'node:fs'
import { createStore } from './store.mjs'
import { rowToConversation } from './conversationDto.mjs'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

loadEnv({ path: join(__dirname, '.env') })
loadEnv({ path: join(__dirname, '..', '.env') })

const PORT = Number(process.env.PORT || 8787)
const SESSION_SECRET = process.env.SESSION_SECRET || 'dev-secret-change-in-production-min-32-chars!!'
const DATABASE_PATH = process.env.DATABASE_PATH || join(__dirname, '..', 'data', 'agent-hub.sqlite')
const LLM_API_URL = process.env.LLM_API_URL || ''
const LLM_API_KEY = process.env.LLM_API_KEY || ''
const LLM_MODEL = process.env.LLM_MODEL || 'deepseek-chat'
const ADMIN_EMAIL = (process.env.ADMIN_EMAIL || 'admin@example.com').toLowerCase().trim()
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'changeme'

const store = await createStore({
  DATABASE_URL: process.env.DATABASE_URL,
  DATABASE_PATH,
})

async function bootstrapAdmin() {
  const n = await store.countUsers()
  if (n > 0) return
  const orgId = randomUUID()
  const userId = randomUUID()
  const now = Date.now()
  const hash = bcrypt.hashSync(ADMIN_PASSWORD, 10)
  await store.bootstrapOrgAndAdmin({
    orgId,
    userId,
    email: ADMIN_EMAIL,
    passwordHash: hash,
    displayName: '管理员',
    role: 'admin',
    now,
  })
  console.log(`[agent-hub] 已创建初始组织与管理账号: ${ADMIN_EMAIL}（请尽快修改 ADMIN_PASSWORD 并登录）`)
}

await bootstrapAdmin()

const app = express()
app.set('trust proxy', 1)
app.use(express.json({ limit: '2mb' }))

app.use(
  cookieSession({
    name: 'agent_hub_session',
    keys: [SESSION_SECRET],
    maxAge: 7 * 24 * 60 * 60 * 1000,
    sameSite: 'lax',
    httpOnly: true,
    secure: process.env.COOKIE_SECURE === 'true',
  }),
)

async function requireAuth(req, res, next) {
  try {
    const uid = req.session?.userId
    if (!uid) return res.status(401).json({ error: '未登录' })
    const u = await store.getUserSession(uid)
    if (!u) return res.status(401).json({ error: '未登录' })
    req.user = u
    next()
  } catch (e) {
    next(e)
  }
}

function requireAdmin(req, res, next) {
  if (req.user.role !== 'admin') return res.status(403).json({ error: '需要管理员权限' })
  next()
}

function llmReady() {
  return !!(LLM_API_URL && LLM_API_KEY)
}

function publicLlmMeta() {
  if (!llmReady()) return null
  let host = ''
  try {
    host = new URL(LLM_API_URL).host
  } catch {
    host = ''
  }
  return { model: LLM_MODEL, host }
}

function userJson(u) {
  return {
    id: u.id,
    email: u.email,
    displayName: u.display_name,
    role: u.role,
    orgId: u.org_id,
    orgName: u.org_name,
  }
}

app.get('/health', (_req, res) => {
  res.json({ ok: true, llmConfigured: llmReady(), database: store.kind })
})

app.post('/auth/login', async (req, res, next) => {
  try {
    const email = String(req.body?.email || '')
      .toLowerCase()
      .trim()
    const password = String(req.body?.password || '')
    if (!email || !password) return res.status(400).json({ error: '请输入邮箱与密码' })
    const row = await store.findUserForLogin(email)
    if (!row || !bcrypt.compareSync(password, row.password_hash)) {
      return res.status(401).json({ error: '邮箱或密码错误' })
    }
    req.session.userId = row.id
    const u = await store.getUserSession(row.id)
    res.json({
      user: userJson(u),
      llmConfigured: llmReady(),
      publicLlm: publicLlmMeta(),
    })
  } catch (e) {
    next(e)
  }
})

app.post('/auth/logout', (req, res) => {
  req.session = null
  res.json({ ok: true })
})

app.get('/auth/me', requireAuth, (req, res) => {
  res.json({
    user: userJson(req.user),
    llmConfigured: llmReady(),
    publicLlm: publicLlmMeta(),
  })
})

app.get('/conversations', requireAuth, async (req, res, next) => {
  try {
    const rows = await store.listConversations(req.user.org_id)
    res.json(rows.map(rowToConversation))
  } catch (e) {
    next(e)
  }
})

app.post('/conversations', requireAuth, async (req, res, next) => {
  try {
    const agentId = String(req.body?.agentId || '').trim()
    if (!agentId) return res.status(400).json({ error: '缺少 agentId' })
    const title = String(req.body?.title || '新对话').trim() || '新对话'
    const id = randomUUID()
    const now = Date.now()
    const row = await store.insertConversation({
      id,
      orgId: req.user.org_id,
      agentId,
      title,
      createdBy: req.user.id,
      now,
    })
    res.status(201).json(rowToConversation(row))
  } catch (e) {
    next(e)
  }
})

app.patch('/conversations/:id', requireAuth, async (req, res, next) => {
  try {
    const id = req.params.id
    const row = await store.getConversation(id, req.user.org_id)
    if (!row) return res.status(404).json({ error: '会话不存在' })

    const exp = req.body?.expectedRevision
    if (typeof exp !== 'number' || !Number.isInteger(exp) || exp < 0) {
      return res.status(400).json({ error: '请提供非负整数 expectedRevision（乐观锁，防止并发覆盖）' })
    }

    const title = req.body?.title != null ? String(req.body.title) : row.title
    const summary =
      req.body?.summary !== undefined
        ? req.body.summary === '' || req.body.summary == null
          ? null
          : String(req.body.summary)
        : row.summary
    const messages = Array.isArray(req.body?.messages) ? req.body.messages : JSON.parse(row.messages_json || '[]')
    const updatedAt = typeof req.body?.updatedAt === 'number' ? req.body.updatedAt : Date.now()

    const result = await store.updateConversationOptimistic({
      id,
      orgId: req.user.org_id,
      title,
      summary,
      messagesJson: JSON.stringify(messages),
      updatedAt,
      expectedRevision: exp,
    })

    if (!result.ok) {
      return res.status(409).json({
        error: 'conflict',
        message: '会话已被其他成员或另一窗口更新',
        conversation: result.current ? rowToConversation(result.current) : null,
      })
    }
    res.json(rowToConversation(result.row))
  } catch (e) {
    next(e)
  }
})

app.delete('/conversations/:id', requireAuth, async (req, res, next) => {
  try {
    const id = req.params.id
    const changes = await store.deleteConversation(id, req.user.org_id)
    if (changes === 0) return res.status(404).json({ error: '会话不存在' })
    res.json({ ok: true })
  } catch (e) {
    next(e)
  }
})

app.post('/admin/users', requireAuth, requireAdmin, async (req, res, next) => {
  try {
    const email = String(req.body?.email || '')
      .toLowerCase()
      .trim()
    const password = String(req.body?.password || '')
    const displayName = String(req.body?.displayName || '').trim() || email.split('@')[0]
    const role = req.body?.role === 'admin' ? 'admin' : 'member'
    if (!email || !password || password.length < 8) {
      return res.status(400).json({ error: '邮箱必填，密码至少 8 位' })
    }
    const exists = await store.findUserIdByEmail(email)
    if (exists) return res.status(409).json({ error: '该邮箱已注册' })
    const id = randomUUID()
    const hash = bcrypt.hashSync(password, 10)
    const now = Date.now()
    try {
      await store.insertMemberUser({
        id,
        orgId: req.user.org_id,
        email,
        passwordHash: hash,
        displayName,
        role,
        now,
      })
    } catch (e) {
      return res.status(500).json({ error: '创建失败' })
    }
    res.status(201).json({ id, email, displayName, role })
  } catch (e) {
    next(e)
  }
})

const MAX_LLM_MESSAGES = 128
const MAX_BODY_CHARS = 400_000

function clampMessages(messages) {
  if (!Array.isArray(messages)) throw new Error('messages 须为数组')
  if (messages.length > MAX_LLM_MESSAGES) throw new Error(`消息条数超过上限 ${MAX_LLM_MESSAGES}`)
  let chars = 0
  for (const m of messages) {
    const c = typeof m?.content === 'string' ? m.content : JSON.stringify(m?.content ?? '')
    chars += c.length
    if (chars > MAX_BODY_CHARS) throw new Error('消息总长度超过上限')
  }
  return messages
}

app.post('/llm/chat', requireAuth, async (req, res) => {
  if (!llmReady()) return res.status(503).json({ error: '服务端未配置 LLM（LLM_API_URL / LLM_API_KEY）' })
  let messages
  try {
    messages = clampMessages(req.body?.messages)
  } catch (e) {
    return res.status(400).json({ error: e.message })
  }
  const stream = !!req.body?.stream
  const model = typeof req.body?.model === 'string' && req.body.model.trim() ? req.body.model.trim() : LLM_MODEL
  const temperature = typeof req.body?.temperature === 'number' ? req.body.temperature : 0.7
  const max_tokens = Math.min(
    16384,
    typeof req.body?.max_tokens === 'number' ? Math.round(req.body.max_tokens) : 4096,
  )

  const body = {
    model,
    messages,
    temperature,
    max_tokens,
    stream,
  }

  try {
    const response = await fetch(LLM_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${LLM_API_KEY}`,
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const errText = await response.text()
      return res.status(response.status).json({ error: errText.slice(0, 2000) })
    }

    if (stream && response.body) {
      res.status(200)
      const ct = response.headers.get('content-type')
      if (ct) res.setHeader('Content-Type', ct)
      await pipeline(Readable.fromWeb(response.body), res)
    } else {
      const data = await response.json()
      res.json(data)
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    res.status(502).json({ error: `上游请求失败: ${msg}` })
  }
})

app.post('/llm/chat-api', requireAuth, async (req, res) => {
  if (!llmReady()) return res.status(503).json({ error: '服务端未配置 LLM' })
  let messages
  try {
    messages = clampMessages(req.body?.messages)
  } catch (e) {
    return res.status(400).json({ error: e.message })
  }
  const model = typeof req.body?.model === 'string' && req.body.model.trim() ? req.body.model.trim() : LLM_MODEL
  const temperature = typeof req.body?.temperature === 'number' ? req.body.temperature : 0.7
  const max_tokens = Math.min(
    16384,
    typeof req.body?.max_tokens === 'number' ? Math.round(req.body.max_tokens) : 4096,
  )
  const tools = Array.isArray(req.body?.tools) ? req.body.tools : undefined

  const body = {
    model,
    messages,
    temperature,
    max_tokens,
    stream: false,
  }
  if (tools?.length) {
    body.tools = tools
    body.tool_choice = 'auto'
  }

  try {
    const response = await fetch(LLM_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${LLM_API_KEY}`,
      },
      body: JSON.stringify(body),
    })
    const text = await response.text()
    if (!response.ok) {
      return res.status(response.status).json({ error: text.slice(0, 2000) })
    }
    res.type('json').send(text)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    res.status(502).json({ error: msg })
  }
})

app.post('/llm/chat-once', requireAuth, async (req, res) => {
  if (!llmReady()) return res.status(503).json({ error: '服务端未配置 LLM' })
  let messages
  try {
    messages = clampMessages(req.body?.messages)
  } catch (e) {
    return res.status(400).json({ error: e.message })
  }
  const model = typeof req.body?.model === 'string' && req.body.model.trim() ? req.body.model.trim() : LLM_MODEL
  const temperature = typeof req.body?.temperature === 'number' ? req.body.temperature : 0.7
  const max_tokens = Math.min(
    16384,
    typeof req.body?.max_tokens === 'number' ? Math.round(req.body.max_tokens) : 4096,
  )
  const started = Date.now()
  try {
    const response = await fetch(LLM_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${LLM_API_KEY}`,
      },
      body: JSON.stringify({
        model,
        messages,
        temperature,
        max_tokens,
        stream: false,
      }),
    })
    const latencyMs = Date.now() - started
    if (!response.ok) {
      const err = await response.text()
      return res.status(502).json({
        content: '',
        latencyMs,
        error: `HTTP ${response.status}: ${err.slice(0, 500)}`,
      })
    }
    const data = await response.json()
    const content = data.choices?.[0]?.message?.content ?? ''
    res.json({
      content,
      latencyMs,
      usage: data.usage,
    })
  } catch (e) {
    const latencyMs = Date.now() - started
    res.json({
      content: '',
      latencyMs,
      error: e instanceof Error ? e.message : String(e),
    })
  }
})

app.use((err, _req, res, _next) => {
  console.error('[agent-hub]', err)
  res.status(500).json({ error: '服务器内部错误' })
})

const distDir = join(__dirname, '..', 'dist')
if (existsSync(distDir)) {
  app.use(express.static(distDir, { index: false }))
  app.get('*', (_req, res) => {
    res.sendFile(join(distDir, 'index.html'))
  })
}

app.listen(PORT, () => {
  console.log(
    `[agent-hub] 服务 http://127.0.0.1:${PORT}（数据库: ${store.kind}）${existsSync(distDir) ? '，已挂载 dist' : ''}`,
  )
})
