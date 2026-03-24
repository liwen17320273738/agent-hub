#!/usr/bin/env node
/**
 * agent-hub 配置验证
 * 检查前端、代理、API 配置
 */

const FRONTEND = 'http://localhost:5200'
const DASHSCOPE_KEY = process.env.DASHSCOPE_API_KEY || process.argv[2]

async function check(name, fn) {
  try {
    const ok = await fn()
    console.log(ok ? `✅ ${name}` : `❌ ${name}`)
    return ok
  } catch (e) {
    console.log(`❌ ${name}: ${e.message}`)
    return false
  }
}

async function main() {
  console.log('=== agent-hub 验证 ===\n')

  await check('前端服务 (localhost:5200)', async () => {
    const r = await fetch(FRONTEND)
    return r.ok
  })

  await check('DashScope 代理路由', async () => {
    const r = await fetch(`${FRONTEND}/api/proxy/dashscope/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer sk-test' },
      body: JSON.stringify({
        model: 'qwen-turbo',
        messages: [{ role: 'user', content: 'hi' }],
        max_tokens: 10,
      }),
    })
    const text = await r.text()
    return r.status === 401 && text.includes('invalid_api_key')
  })

  await check('DeepSeek 代理路由', async () => {
    const r = await fetch(`${FRONTEND}/api/proxy/deepseek/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer sk-test' },
      body: JSON.stringify({
        model: 'deepseek-chat',
        messages: [{ role: 'user', content: 'hi' }],
        max_tokens: 10,
      }),
    })
    const data = await r.json().catch(() => ({}))
    return r.ok || data?.error?.code === 'invalid_request_error'
  })

  if (DASHSCOPE_KEY) {
    await check('千问 API 连接 (需有效 Key)', async () => {
      const r = await fetch('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${DASHSCOPE_KEY}`,
        },
        body: JSON.stringify({
          model: 'qwen-turbo',
          messages: [{ role: 'user', content: '你好，请用一句话回复。' }],
          max_tokens: 50,
        }),
      })
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      return !!data.choices?.[0]?.message?.content
    })
  } else {
    console.log('⏭ 千问 API: 跳过 (设置 DASHSCOPE_API_KEY 或传入 Key 可验证)')
  }

  console.log('\n验证完成')
}

main().catch(console.error)
