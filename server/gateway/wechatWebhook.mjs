import { Router } from 'express'
import crypto from 'node:crypto'
import { dispatchToOpenClaw } from './openclawRouter.mjs'

const router = Router()

const WECHAT_TOKEN = () => process.env.WECHAT_MP_TOKEN || ''

/**
 * 微信公众号消息回调（兼容 XML 格式）。
 * 
 * GET: 签名验证（微信服务器配置回调地址时发送）
 * POST: 消息事件（用户在公众号发送消息）
 * 
 * 微信消息 XML 格式:
 * <xml>
 *   <ToUserName><![CDATA[gh_xxx]]></ToUserName>
 *   <FromUserName><![CDATA[o_xxx]]></FromUserName>
 *   <CreateTime>1234567890</CreateTime>
 *   <MsgType><![CDATA[text]]></MsgType>
 *   <Content><![CDATA[消息内容]]></Content>
 *   <MsgId>1234567890</MsgId>
 * </xml>
 */

// 签名验证
function checkSignature(signature, timestamp, nonce) {
  const token = WECHAT_TOKEN()
  if (!token || !signature || !timestamp || !nonce) return false
  const tmp = [token, timestamp, nonce].sort().join('')
  const hash = crypto.createHash('sha1').update(tmp).digest('hex')
  return hash === signature
}

// 简易 XML 解析（不依赖额外库）
function parseXmlToJSON(xml) {
  const result = {}
  const tagRe = /<(\w+)><!\[CDATA\[(.*?)\]\]><\/\1>/gs
  let match
  while ((match = tagRe.exec(xml)) !== null) {
    result[match[1]] = match[2]
  }
  // Fallback: plain text tags (no CDATA)
  const plainRe = /<(\w+)>(.*?)<\/\1>/gs
  while ((match = plainRe.exec(xml)) !== null) {
    if (!(match[1] in result)) {
      result[match[1]] = match[2]
    }
  }
  return result
}

// 构造文本回复 XML
function buildTextReply(toUser, fromUser, content) {
  const createTime = Math.floor(Date.now() / 1000)
  return [
    '<xml>',
    `<ToUserName><![CDATA[${toUser}]]></ToUserName>`,
    `<FromUserName><![CDATA[${fromUser}]]></FromUserName>`,
    `<CreateTime>${createTime}</CreateTime>`,
    '<MsgType><![CDATA[text]]></MsgType>',
    `<Content><![CDATA[${content}]]></Content>`,
    '</xml>',
  ].join('\n')
}

router.get('/', (req, res) => {
  const { signature, timestamp, nonce, echostr } = req.query
  if (checkSignature(signature, timestamp, nonce)) {
    res.type('text/plain').send(echostr || '')
  } else {
    res.status(403).send('signature check failed')
  }
})

router.post('/', async (req, res) => {
  const { signature, timestamp, nonce } = req.query
  if (!checkSignature(signature, timestamp, nonce)) {
    return res.status(403).send('signature check failed')
  }

  const body = req.body
  // body may be raw XML if express.text middleware is used, or parsed
  const rawXml = typeof body === 'string' ? body : ''
  if (!rawXml) return res.send('success')

  const msg = parseXmlToJSON(rawXml)
  const msgType = msg.MsgType
  const fromUser = msg.FromUserName || ''
  const toUser = msg.ToUserName || ''

  console.log(`[wechat] event: ${msgType} from ${fromUser}`)

  if (msgType === 'text') {
    const text = (msg.Content || '').trim()
    if (text) {
      try {
        const task = await dispatchToOpenClaw({
          title: text.slice(0, 80),
          description: text,
          source: 'wechat',
          sourceMessageId: msg.MsgId || '',
          sourceUserId: fromUser,
        })
        console.log(`[wechat] 需求已接入 → task ${task.id}: ${task.title}`)
        return res.type('application/xml').send(
          buildTextReply(fromUser, toUser,
            `✅ 需求已接入流水线\n任务ID: ${task.id}\n标题: ${task.title}\n当前阶段: 需求接入`
          )
        )
      } catch (e) {
        console.error('[wechat] dispatch error:', e.message)
        return res.type('application/xml').send(
          buildTextReply(fromUser, toUser, '❌ 接入失败，请稍后重试')
        )
      }
    }
  }

  if (msgType === 'event') {
    const event = msg.Event || ''
    console.log(`[wechat] event type: ${event}`)
    if (event === 'subscribe') {
      return res.type('application/xml').send(
        buildTextReply(fromUser, toUser,
          '👋 欢迎使用 Agent Hub！\n直接发送需求，AI 军团将自动处理。\n例如：「开发一个 todo 应用」'
        )
      )
    }
  }

  // 非文本消息或未处理事件 → 200 OK
  res.send('success')
})

export default router
