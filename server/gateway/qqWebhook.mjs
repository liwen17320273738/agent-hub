import { Router } from 'express'
import { dispatchToOpenClaw } from './openclawRouter.mjs'

const router = Router()

const QQ_BOT_ENDPOINT = () => process.env.QQ_BOT_ENDPOINT || ''
const QQ_BOT_SECRET = () => process.env.QQ_BOT_SECRET || ''

/**
 * QQ 机器人事件回调（兼容 OneBot v11 HTTP POST 上报格式）。
 * go-cqhttp / Lagrange.OneBot / NapCat 等实现均可对接。
 */
router.post('/', (req, res) => {
  const need = QQ_BOT_SECRET()
  if (need) {
    const h =
      req.headers['x-qq-secret'] ||
      (typeof req.headers.authorization === 'string'
        ? req.headers.authorization.replace(/^Bearer\s+/i, '').trim()
        : '')
    if (h !== need) return res.status(401).json({ error: '未授权' })
  }

  const body = req.body
  const postType = body?.post_type

  if (postType === 'meta_event') {
    return res.json({ ok: true })
  }

  if (postType === 'message') {
    return handleMessage(body, res)
  }

  if (postType === 'notice' || postType === 'request') {
    console.log(`[qq] ${postType} event: ${body?.notice_type || body?.request_type}`)
    return res.json({ ok: true })
  }

  res.json({ ok: true })
})

async function handleMessage(body, res) {
  const messageType = body.message_type
  const rawMessage = body.raw_message || body.message || ''
  const userId = String(body.user_id || '')
  const messageId = String(body.message_id || '')

  const text = typeof rawMessage === 'string'
    ? rawMessage.replace(/\[CQ:[^\]]+\]/g, '').trim()
    : ''

  if (!text) return res.json({ ok: true })

  const isCommand = text.startsWith('/task ') || text.startsWith('/需求 ')
  if (!isCommand && messageType === 'group') {
    return res.json({ ok: true })
  }

  const cleanText = text.replace(/^\/(task|需求)\s+/, '')

  if (cleanText.trim()) {
    const task = await dispatchToOpenClaw({
      title: cleanText.slice(0, 80),
      description: cleanText,
      source: 'qq',
      sourceMessageId: messageId,
      sourceUserId: userId,
    })

    console.log(`[qq] 需求已接入 → task ${task.id}: ${task.title}`)

    replyToQQ(body, `✅ 需求已接入流水线\n任务ID: ${task.id}\n标题: ${task.title}\n当前阶段: 需求接入`)
  }

  res.json({ ok: true })
}

async function replyToQQ(original, text) {
  const endpoint = QQ_BOT_ENDPOINT()
  if (!endpoint) return

  const action = original.message_type === 'group' ? 'send_group_msg' : 'send_private_msg'
  const params =
    original.message_type === 'group'
      ? { group_id: original.group_id, message: text }
      : { user_id: original.user_id, message: text }

  try {
    await fetch(`${endpoint}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
  } catch (e) {
    console.error('[qq] reply error:', e.message)
  }
}

export default router
