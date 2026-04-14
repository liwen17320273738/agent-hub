/**
 * /models — 实时模型列表 API
 */
import { Router } from 'express'
import { fetchAllModels, resolveApiKeysFromEnv, clearModelCache } from './modelRegistry.mjs'

const router = Router()

router.get('/', async (_req, res) => {
  try {
    const apiKeys = resolveApiKeysFromEnv()
    const models = await fetchAllModels(apiKeys)
    res.json({
      providers: Object.keys(apiKeys),
      models,
      cached: true,
    })
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

router.get('/providers', (_req, res) => {
  const apiKeys = resolveApiKeysFromEnv()
  res.json({
    configured: Object.keys(apiKeys),
    available: ['openai', 'anthropic', 'deepseek', 'zhipu', 'qwen', 'google'],
  })
})

router.post('/refresh', async (_req, res) => {
  try {
    clearModelCache()
    const apiKeys = resolveApiKeysFromEnv()
    const models = await fetchAllModels(apiKeys)
    res.json({ providers: Object.keys(apiKeys), models, refreshed: true })
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

export default router
