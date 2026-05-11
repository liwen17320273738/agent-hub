import { describe, it, expect } from 'vitest'

import {
  PROVIDER_DEFAULT_API,
  PROVIDER_LABEL,
  liveModelProviderLabel,
  MODEL_CATALOG,
  detectProviderFromApiUrl,
  inferDefaultApiFromLlmHost,
  findCatalogEntry,
  catalogByProvider,
  coerceModelForProvider,
  type ModelProvider,
} from '../modelCatalog'

describe('modelCatalog', () => {
  it('PROVIDER_DEFAULT_API has all 6 providers', () => {
    const providers: ModelProvider[] = ['deepseek', 'openai', 'qwen', 'anthropic', 'google', 'zhipu']
    for (const p of providers) {
      expect(PROVIDER_DEFAULT_API[p]).toBeDefined()
      expect(PROVIDER_DEFAULT_API[p]).toContain('https://')
    }
  })

  it('PROVIDER_LABEL has all 6 providers', () => {
    const providers: ModelProvider[] = ['deepseek', 'openai', 'qwen', 'anthropic', 'google', 'zhipu']
    for (const p of providers) {
      expect(PROVIDER_LABEL[p]).toBeDefined()
      expect(PROVIDER_LABEL[p].length).toBeGreaterThan(0)
    }
  })

  it('liveModelProviderLabel returns correct labels', () => {
    expect(liveModelProviderLabel('gateway')).toBe('当前网关')
    expect(liveModelProviderLabel('local')).toBe('兼容网关')
    expect(liveModelProviderLabel('deepseek')).toBe('DeepSeek')
    expect(liveModelProviderLabel('unknown')).toBe('unknown')
  })

  it('MODEL_CATALOG has entries with required fields', () => {
    expect(MODEL_CATALOG.length).toBeGreaterThan(0)
    for (const entry of MODEL_CATALOG) {
      expect(entry.id).toBeTruthy()
      expect(entry.provider).toBeTruthy()
      expect(entry.label).toBeTruthy()
      expect(entry.blurb).toBeTruthy()
      expect(entry.scores).toBeDefined()
      expect(typeof entry.scores.cost).toBe('number')
      expect(typeof entry.scores.speed).toBe('number')
      expect(typeof entry.contextK).toBe('number')
      expect(entry.contextK).toBeGreaterThan(0)
    }
  })

  it('MODEL_CATALOG has at least one core model per major provider', () => {
    const coreProviders = new Set(
      MODEL_CATALOG.filter(e => e.isCore).map(e => e.provider)
    )
    expect(coreProviders.size).toBeGreaterThanOrEqual(3)
  })
})

describe('detectProviderFromApiUrl', () => {
  it('detects deepseek', () => {
    expect(detectProviderFromApiUrl('https://api.deepseek.com/v1/chat/completions')).toBe('deepseek')
  })

  it('detects openai', () => {
    expect(detectProviderFromApiUrl('https://api.openai.com/v1/chat/completions')).toBe('openai')
  })

  it('detects qwen via dashscope', () => {
    expect(detectProviderFromApiUrl('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions')).toBe('qwen')
  })

  it('detects anthropic', () => {
    expect(detectProviderFromApiUrl('https://api.anthropic.com/v1/messages')).toBe('anthropic')
  })

  it('detects google', () => {
    expect(detectProviderFromApiUrl('https://generativelanguage.googleapis.com/v1beta/models')).toBe('google')
  })

  it('detects zhipu', () => {
    expect(detectProviderFromApiUrl('https://open.bigmodel.cn/api/paas/v4/chat/completions')).toBe('zhipu')
  })

  it('returns null for unknown URL', () => {
    expect(detectProviderFromApiUrl('https://example.com/api')).toBeNull()
  })

  it('is case-insensitive', () => {
    expect(detectProviderFromApiUrl('HTTPS://API.DEEPSEEK.COM/v1')).toBe('deepseek')
  })
})

describe('inferDefaultApiFromLlmHost', () => {
  it('infers deepseek API from host', () => {
    expect(inferDefaultApiFromLlmHost('api.deepseek.com')).toBe(PROVIDER_DEFAULT_API.deepseek)
  })

  it('returns empty string for unknown host', () => {
    expect(inferDefaultApiFromLlmHost('example.com')).toBe('')
  })
})

describe('findCatalogEntry', () => {
  it('finds an existing model by id', () => {
    const first = MODEL_CATALOG[0]
    expect(findCatalogEntry(first.id)).toBeDefined()
    expect(findCatalogEntry(first.id)!.id).toBe(first.id)
  })

  it('returns undefined for unknown model', () => {
    expect(findCatalogEntry('nonexistent-model-xyz')).toBeUndefined()
  })
})

describe('catalogByProvider', () => {
  it('returns only models for given provider', () => {
    const deepseekModels = catalogByProvider('deepseek')
    expect(deepseekModels.length).toBeGreaterThan(0)
    for (const m of deepseekModels) {
      expect(m.provider).toBe('deepseek')
    }
  })
})

describe('coerceModelForProvider', () => {
  it('keeps model if it matches provider', () => {
    const dsModel = catalogByProvider('deepseek')[0]
    if (dsModel) {
      expect(coerceModelForProvider(dsModel.id, 'deepseek')).toBe(dsModel.id)
    }
  })

  it('returns empty string fallback for empty model', () => {
    const result = coerceModelForProvider('', 'deepseek')
    const first = catalogByProvider('deepseek')[0]
    if (first) {
      expect(result).toBe(first.id)
    }
  })
})
