import { defineStore } from 'pinia'
import { ref } from 'vue'
import { defaultSettings, type LLMSettings } from '@/services/llm'
import { isEnterpriseBuild } from '@/services/enterpriseApi'
import { useAuthStore } from '@/stores/auth'

const STORAGE_KEY = 'agent-hub-settings'

function stripApiKeyForEnterprise(s: LLMSettings): LLMSettings {
  if (!isEnterpriseBuild) return s
  return { ...s, apiKey: '' }
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<LLMSettings>(loadSettings())

  function loadSettings(): LLMSettings {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const loaded = { ...defaultSettings, ...JSON.parse(raw) }
        if (loaded.maxTokens > 16384) loaded.maxTokens = 16384
        if (typeof loaded.contextMaxMessages !== 'number') loaded.contextMaxMessages = defaultSettings.contextMaxMessages
        else loaded.contextMaxMessages = Math.min(128, Math.max(4, Math.round(loaded.contextMaxMessages)))
        if (typeof loaded.contextMaxChars !== 'number') loaded.contextMaxChars = defaultSettings.contextMaxChars
        else loaded.contextMaxChars = Math.min(200_000, Math.max(4000, Math.round(loaded.contextMaxChars)))
        if (typeof loaded.enableTools !== 'boolean') loaded.enableTools = defaultSettings.enableTools
        return stripApiKeyForEnterprise(loaded)
      }
    } catch {
      /* ignore */
    }
    return stripApiKeyForEnterprise({ ...defaultSettings })
  }

  function save(newSettings: LLMSettings) {
    const next = stripApiKeyForEnterprise({ ...newSettings })
    if (next.maxTokens > 16384) next.maxTokens = 16384
    next.contextMaxMessages = Math.min(128, Math.max(4, Math.round(next.contextMaxMessages)))
    next.contextMaxChars = Math.min(200_000, Math.max(4000, Math.round(next.contextMaxChars)))
    settings.value = next
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings.value))
  }

  function isConfigured(): boolean {
    if (isEnterpriseBuild) {
      const auth = useAuthStore()
      return auth.isLoggedIn && auth.llmConfigured
    }
    return !!settings.value.apiKey
  }

  /** 企业模式：优先使用界面中的 model，未填则用服务端配置的默认模型 */
  function effectiveModel(): string {
    if (isEnterpriseBuild) {
      const pub = useAuthStore().publicLlm
      if (settings.value.model?.trim()) return settings.value.model.trim()
      if (pub?.model) return pub.model
    }
    return settings.value.model
  }

  return { settings, save, isConfigured, effectiveModel }
})
