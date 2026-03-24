#!/usr/bin/env node
/**
 * 验证 DashScope（千问）API 连接
 * 用法: DASHSCOPE_API_KEY=sk-xxx node scripts/verify-dashscope.mjs
 * 或: node scripts/verify-dashscope.mjs sk-xxx
 */

const API_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
const MODEL = 'qwen-turbo'

const apiKey = process.env.DASHSCOPE_API_KEY || process.argv[2]
if (!apiKey) {
  console.error('请提供 API Key:')
  console.error('  方式1: DASHSCOPE_API_KEY=sk-xxx node scripts/verify-dashscope.mjs')
  console.error('  方式2: node scripts/verify-dashscope.mjs sk-xxx')
  process.exit(1)
}

async function verify() {
  console.log('正在验证 DashScope API...')
  console.log('  URL:', API_URL)
  console.log('  模型:', MODEL)
  console.log('')

  try {
    const res = await fetch(API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: MODEL,
        messages: [{ role: 'user', content: '你好，请用一句话回复确认连接成功。' }],
        temperature: 0.7,
        max_tokens: 100,
      }),
    })

    const text = await res.text()
    if (!res.ok) {
      console.error('❌ 连接失败:', res.status, res.statusText)
      console.error('响应:', text)
      process.exit(1)
    }

    const data = JSON.parse(text)
    const reply = data.choices?.[0]?.message?.content ?? '(无回复)'
    console.log('✅ 连接成功！')
    console.log('回复:', reply)
  } catch (e) {
    console.error('❌ 请求异常:', e.message)
    if (e.cause) console.error('原因:', e.cause)
    process.exit(1)
  }
}

verify()
