/**
 * AI 军团流水线端到端测试脚本
 *
 * 用法：
 *   node scripts/test-pipeline.mjs
 *
 * 前置：需要先启动 server（pnpm dev:server 或 pnpm dev:enterprise）
 *
 * 流水线 API 需登录或设置 PIPELINE_API_KEY（与 server/.env 中一致），例如：
 *   PIPELINE_API_KEY=your-secret node scripts/test-pipeline.mjs
 */

const BASE = process.env.API_BASE || 'http://127.0.0.1:8787'
const PIPELINE_API_KEY = process.env.PIPELINE_API_KEY

async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (PIPELINE_API_KEY) {
    opts.headers.Authorization = `Bearer ${PIPELINE_API_KEY}`
  }
  if (body) opts.body = JSON.stringify(body)
  const res = await fetch(`${BASE}${path}`, opts)
  const data = await res.json()
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}: ${JSON.stringify(data)}`)
  return data
}

function ok(label) { console.log(`  ✅ ${label}`) }
function fail(label, e) { console.error(`  ❌ ${label}:`, e.message); process.exitCode = 1 }

async function main() {
  console.log(`\n🚀 AI 军团流水线测试 (${BASE})\n`)

  // 1. Health check
  console.log('1️⃣  Pipeline Health')
  try {
    const h = await api('GET', '/pipeline/health')
    if (h.pipeline !== 'online') throw new Error('pipeline not online')
    ok(`pipeline=${h.pipeline}, executor=${h.executor}, feishu=${h.feishu}, qq=${h.qq}`)
  } catch (e) { fail('health', e); return }

  // 2. List stages
  console.log('2️⃣  Pipeline Stages')
  try {
    const s = await api('GET', '/pipeline/stages')
    ok(`${s.stages.length} 个阶段: ${s.stages.map(x => x.id).join(' → ')}`)
  } catch (e) { fail('stages', e) }

  // 3. Create task via pipeline API
  console.log('3️⃣  创建任务 (Pipeline API)')
  let taskId
  try {
    const d = await api('POST', '/pipeline/tasks', {
      title: '测试：实现暗黑模式',
      description: '需要支持系统级暗黑模式切换，包括所有页面和组件',
      source: 'web',
    })
    taskId = d.task.id
    ok(`任务已创建: ${taskId.slice(0, 8)}... stage=${d.task.currentStageId}`)
  } catch (e) { fail('create task', e); return }

  // 4. Advance: intake → planning
  console.log('4️⃣  推进阶段 (intake → planning)')
  try {
    const d = await api('POST', `/pipeline/tasks/${taskId}/advance`, {
      output: '需求已结构化：暗黑模式，全站适配',
    })
    if (d.task.currentStageId !== 'planning') throw new Error(`expected planning, got ${d.task.currentStageId}`)
    ok(`当前阶段: ${d.task.currentStageId}`)
  } catch (e) { fail('advance', e) }

  // 5. Advance: planning → architecture
  console.log('5️⃣  推进阶段 (planning → architecture)')
  try {
    const d = await api('POST', `/pipeline/tasks/${taskId}/advance`, {
      output: 'PRD 完成：支持 prefers-color-scheme，用 CSS 变量实现',
    })
    ok(`当前阶段: ${d.task.currentStageId}`)
  } catch (e) { fail('advance', e) }

  // 6. Reject: architecture → planning
  console.log('6️⃣  打回阶段 (architecture → planning)')
  try {
    const d = await api('POST', `/pipeline/tasks/${taskId}/reject`, {
      targetStageId: 'planning',
      reason: 'PRD 缺少用户偏好设置存储方案',
    })
    if (d.task.currentStageId !== 'planning') throw new Error(`expected planning, got ${d.task.currentStageId}`)
    ok(`打回成功，当前阶段: ${d.task.currentStageId}`)
  } catch (e) { fail('reject', e) }

  // 7. Add artifact
  console.log('7️⃣  添加产物')
  try {
    const d = await api('POST', `/pipeline/tasks/${taskId}/artifacts`, {
      type: 'prd',
      name: 'dark-mode-prd-v2.md',
      content: '# 暗黑模式 PRD v2\n\n## 目标\n支持系统级暗黑模式...\n\n## 存储方案\nlocalStorage 存储用户偏好',
    })
    ok(`产物数量: ${d.task.artifacts.length}`)
  } catch (e) { fail('artifact', e) }

  // 8. OpenClaw gateway intake (with auto-advance)
  console.log('8️⃣  OpenClaw 网关接入 (模拟飞书)')
  let gatewayTaskId
  try {
    const d = await api('POST', '/gateway/openclaw/intake', {
      title: '优化搜索功能的性能',
      description: '搜索接口 P99 延迟 > 2s，需要加索引和缓存',
      source: 'feishu',
      sourceUserId: 'feishu_user_456',
    })
    gatewayTaskId = d.task.id
    ok(`网关接入成功: ${d.task.id.slice(0, 8)}... stage=${d.task.currentStageId}`)
  } catch (e) { fail('gateway intake', e) }

  // 9. OpenClaw status
  console.log('9️⃣  OpenClaw 网关状态')
  try {
    const d = await api('GET', '/gateway/openclaw/status')
    ok(`网关: ${d.gateway} (${d.status}), channels: web=${d.channels.web.enabled}, feishu=${d.channels.feishu.enabled}`)
  } catch (e) { fail('gateway status', e) }

  // 10. List all tasks
  console.log('🔟  任务列表')
  try {
    const d = await api('GET', '/pipeline/tasks')
    ok(`共 ${d.tasks.length} 个任务`)
    for (const t of d.tasks) {
      console.log(`     ${t.id.slice(0, 8)}... | ${t.title.slice(0, 20).padEnd(20)} | ${t.currentStageId.padEnd(12)} | ${t.source}`)
    }
  } catch (e) { fail('list tasks', e) }

  // 11. Simulate Feishu webhook
  console.log('1️⃣1️⃣  模拟飞书 Webhook')
  try {
    const d = await api('POST', '/gateway/feishu/webhook', {
      schema: '2.0',
      header: {
        event_id: 'test_evt_' + Date.now(),
        event_type: 'im.message.receive_v1',
      },
      event: {
        message: {
          message_id: 'msg_test_123',
          message_type: 'text',
          content: JSON.stringify({ text: '帮我做一个用户反馈收集功能' }),
        },
        sender: {
          sender_id: { open_id: 'ou_test_789' },
        },
      },
    })
    ok(`飞书 Webhook 返回: ${JSON.stringify(d)}`)
  } catch (e) { fail('feishu webhook', e) }

  // 12. Verify tasks increased
  console.log('1️⃣2️⃣  验证任务增长')
  try {
    const d = await api('GET', '/pipeline/tasks')
    ok(`最终任务数: ${d.tasks.length}`)
  } catch (e) { fail('final count', e) }

  // Cleanup test tasks
  console.log('\n🧹  清理测试任务')
  try {
    if (taskId) await api('DELETE', `/pipeline/tasks/${taskId}`)
    if (gatewayTaskId) await api('DELETE', `/pipeline/tasks/${gatewayTaskId}`)
    const allTasks = await api('GET', '/pipeline/tasks')
    for (const t of allTasks.tasks) {
      if (t.title.includes('测试') || t.title.includes('帮我做')) {
        await api('DELETE', `/pipeline/tasks/${t.id}`)
      }
    }
    ok('测试数据已清理')
  } catch (e) { fail('cleanup', e) }

  console.log('\n✨ 测试完成\n')
}

main().catch((e) => {
  console.error('\n💥 测试脚本异常:', e.message)
  process.exit(1)
})
