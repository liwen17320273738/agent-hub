import { defineStore } from 'pinia'
import { ref } from 'vue'
import { defaultSettings, type LLMSettings } from '@/services/llm'

const STORAGE_KEY = 'agent-hub-settings'

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
        return loaded
      }
    } catch { /* ignore */ }
    return { ...defaultSettings }
  }

  function save(newSettings: LLMSettings) {
    const next = { ...newSettings }
    if (next.maxTokens > 16384) next.maxTokens = 16384
    next.contextMaxMessages = Math.min(128, Math.max(4, Math.round(next.contextMaxMessages)))
    next.contextMaxChars = Math.min(200_000, Math.max(4000, Math.round(next.contextMaxChars)))
    settings.value = next
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings.value))
  }

  const isConfigured = () => !!settings.value.apiKey

  return { settings, save, isConfigured }
})
