import { Router } from 'express'
import { dispatchToOpenClaw } from './openclawRouter.mjs'

const router = Router()

const FEISHU_APP_ID = () => process.env.FEISHU_APP_ID || ''
const FEISHU_APP_SECRET = () => process.env.FEISHU_APP_SECRET || ''
const FEISHU_VERIFICATION_TOKEN = () => process.env.FEISHU_VERIFICATION_TOKEN || ''

const processedEvents = new Map()
const EVENT_DEDUP_TTL = 300_000

function dedup(eventId) {
  if (!eventId) return false
  if (processedEvents.has(eventId)) return true
  processedEvents.set(eventId, Date.now())
  if (processedEvents.size > 5000) {
    const now = Date.now()
    for (const [k, v] of processedEvents) {
      if (now - v > EVENT_DEDUP_TTL) processedEvents.delete(k)
    }
  }
  return false
}

/**
 * 飞书事件回调入口。
 * 飞书推送的事件类型：
 * - url_verification: 验证回调地址
 * - event_callback: 实际事件（消息、审批等）
 */
router.post('/', (req, res) => {
  const body = req.body
  const need = FEISHU_VERIFICATION_TOKEN()
  if (need && body?.token !== undefined && body.token !== need) {
    return res.status(403).json({ error: 'forbidden' })
  }

  if (body?.type === 'url_verification') {
    return res.json({ challenge: body.challenge })
  }

  if (body?.schema === '2.0' && body?.header?.event_type) {
    return handleV2Event(body, res)
  }

  if (body?.event) {
    return handleV1Event(body, res)
  }

  res.json({ ok: true })
})

async function handleV2Event(body, res) {
  const eventId = body.header?.event_id
  if (dedup(eventId)) return res.json({ ok: true })

  const eventType = body.header?.event_type
  const event = body.event

  console.log(`[feishu] v2 event: ${eventType}`)

  if (eventType === 'im.message.receive_v1') {
    const message = event?.message
    const sender = event?.sender

    if (message?.message_type === 'text') {
      let text = ''
      try {
        const content = JSON.parse(message.content || '{}')
        text = content.text || ''
      } catch {
        text = message.content || ''
      }

      if (text.trim()) {
        const task = await dispatchToOpenClaw({
          title: text.slice(0, 80),
          description: text,
          source: 'feishu',
          sourceMessageId: message.message_id,
          sourceUserId: sender?.sender_id?.open_id || sender?.sender_id?.user_id,
        })

        console.log(`[feishu] 需求已接入 → task ${task.id}: ${task.title}`)

        replyToFeishu(message.message_id, `✅ 需求已接入流水线\n任务ID: ${task.id}\n标题: ${task.title}\n当前阶段: 需求接入`)
      }
    }
  }

  res.json({ ok: true })
}

async function handleV1Event(body, res) {
  const event = body.event
  const eventType = event?.type

  if (body.uuid && dedup(body.uuid)) return res.json({ ok: true })

  console.log(`[feishu] v1 event: ${eventType}`)

  if (eventType === 'message' || eventType === 'im.message.receive_v1') {
    const text = event?.text || event?.content?.text || ''
    if (text.trim()) {
      const task = await dispatchToOpenClaw({
        title: text.slice(0, 80),
        description: text,
        source: 'feishu',
        sourceMessageId: event?.message_id || event?.msg_key,
        sourceUserId: event?.open_id || event?.user_open_id,
      })
      console.log(`[feishu] 需求已接入 → task ${task.id}: ${task.title}`)
    }
  }

  res.json({ ok: true })
}

async function replyToFeishu(messageId, text) {
  const appId = FEISHU_APP_ID()
  const appSecret = FEISHU_APP_SECRET()
  if (!appId || !appSecret) return

  try {
    const tokenRes = await fetch(
      'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
      },
    )
    const tokenData = await tokenRes.json()
    if (tokenData.code !== 0) return

    await fetch(
      `https://open.feishu.cn/open-apis/im/v1/messages/${messageId}/reply`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokenData.tenant_access_token}`,
        },
        body: JSON.stringify({
          content: JSON.stringify({ text }),
          msg_type: 'text',
        }),
      },
    )
  } catch (e) {
    console.error('[feishu] reply error:', e.message)
  }
}

export default router

export { replyToFeishu }
