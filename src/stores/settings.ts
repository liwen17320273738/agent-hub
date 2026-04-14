import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { defaultSettings, type LLMSettings } from '@/services/llm'
import { isEnterpriseBuild } from '@/services/enterpriseApi'
import { useAuthStore } from '@/stores/auth'
import { coerceModelForProvider, detectProviderFromApiUrl } from '@/services/modelCatalog'

const STORAGE_KEY = 'agent-hub-settings'

export interface ModelProfile {
  id: string
  name: string
  settings: LLMSettings
  createdAt: number
  updatedAt: number
}

interface StoredSettingsState {
  profiles: ModelProfile[]
  activeProfileId: string
  roleBindings: Record<string, string>
}

function stripApiKeyForEnterprise(s: LLMSettings): LLMSettings {
  if (!isEnterpriseBuild) return s
  return { ...s, apiKey: '' }
}

function normalizeSettings(input: LLMSettings): LLMSettings {
  const next = stripApiKeyForEnterprise({ ...input })
  if (!next.provider) next.provider = detectProviderFromApiUrl(next.apiUrl) ?? defaultSettings.provider
  if (next.model?.trim()) {
    next.model = coerceModelForProvider(next.model, next.provider)
  } else if (!isEnterpriseBuild) {
    next.model = coerceModelForProvider('', next.provider)
  }
  if (!next.wayneCostMode) next.wayneCostMode = defaultSettings.wayneCostMode
  if (next.maxTokens > 16384) next.maxTokens = 16384
  next.contextMaxMessages = Math.min(128, Math.max(4, Math.round(next.contextMaxMessages)))
  next.contextMaxChars = Math.min(200_000, Math.max(4000, Math.round(next.contextMaxChars)))
  if (typeof next.enableTools !== 'boolean') next.enableTools = defaultSettings.enableTools
  return next
}

function createProfile(name: string, settings: LLMSettings): ModelProfile {
  const now = Date.now()
  return {
    id: crypto.randomUUID(),
    name,
    settings: normalizeSettings(settings),
    createdAt: now,
    updatedAt: now,
  }
}

function defaultProfileName(index = 1) {
  return index === 1 ? '默认模型档案' : `模型档案 ${index}`
}

export const useSettingsStore = defineStore('settings', () => {
  const profiles = ref<ModelProfile[]>([])
  const activeProfileId = ref<string>('')
  const roleBindings = ref<Record<string, string>>({})

  function loadSettings(): StoredSettingsState {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw)

        if (Array.isArray(parsed?.profiles) && typeof parsed?.activeProfileId === 'string') {
          const normalizedProfiles = parsed.profiles.map((profile: ModelProfile, index: number) => ({
            ...profile,
            name: profile?.name || defaultProfileName(index + 1),
            settings: normalizeSettings({ ...defaultSettings, ...profile.settings }),
          }))
          const activeExists = normalizedProfiles.some((item: ModelProfile) => item.id === parsed.activeProfileId)
          return {
            profiles: normalizedProfiles,
            activeProfileId: activeExists ? parsed.activeProfileId : normalizedProfiles[0]?.id ?? '',
            roleBindings: typeof parsed?.roleBindings === 'object' && parsed.roleBindings ? parsed.roleBindings : {},
          }
        }

        const migrated = normalizeSettings({ ...defaultSettings, ...parsed })
        const profile = createProfile(defaultProfileName(), migrated)
        return {
          profiles: [profile],
          activeProfileId: profile.id,
          roleBindings: {},
        }
      }
    } catch {
      /* ignore */
    }

    const profile = createProfile(defaultProfileName(), { ...defaultSettings })
    return {
      profiles: [profile],
      activeProfileId: profile.id,
      roleBindings: {},
    }
  }

  function persist() {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        profiles: profiles.value,
        activeProfileId: activeProfileId.value,
        roleBindings: roleBindings.value,
      }),
    )
  }

  const loadedState = loadSettings()
  profiles.value = loadedState.profiles
  activeProfileId.value = loadedState.activeProfileId
  roleBindings.value = loadedState.roleBindings

  const activeProfile = computed<ModelProfile | null>(
    () => profiles.value.find((item) => item.id === activeProfileId.value) ?? null,
  )

  const settings = computed<LLMSettings>(() => activeProfile.value?.settings ?? normalizeSettings({ ...defaultSettings }))

  function activateProfile(id: string) {
    if (!profiles.value.some((item) => item.id === id)) return
    activeProfileId.value = id
    persist()
  }

  function save(newSettings: LLMSettings) {
    const next = normalizeSettings(newSettings)
    const profile = activeProfile.value
    if (!profile) return
    profile.settings = next
    profile.updatedAt = Date.now()
    persist()
  }

  function saveActiveProfileName(name: string) {
    const profile = activeProfile.value
    if (!profile) return
    profile.name = name.trim() || profile.name
    profile.updatedAt = Date.now()
    persist()
  }

  function createNewProfile(seed?: Partial<ModelProfile> & { settings?: Partial<LLMSettings> }) {
    const profile = createProfile(
      seed?.name || defaultProfileName(profiles.value.length + 1),
      { ...defaultSettings, ...seed?.settings },
    )
    profiles.value.push(profile)
    activeProfileId.value = profile.id
    persist()
    return profile
  }

  function duplicateActiveProfile() {
    const profile = activeProfile.value
    if (!profile) return null
    const copy = createProfile(`${profile.name} 副本`, { ...profile.settings })
    profiles.value.push(copy)
    activeProfileId.value = copy.id
    persist()
    return copy
  }

  function deleteProfile(id: string) {
    if (profiles.value.length <= 1) return false
    const idx = profiles.value.findIndex((item) => item.id === id)
    if (idx < 0) return false
    profiles.value.splice(idx, 1)
    if (activeProfileId.value === id) {
      activeProfileId.value = profiles.value[0]?.id ?? ''
    }
    for (const [agentId, profileId] of Object.entries(roleBindings.value)) {
      if (profileId === id) delete roleBindings.value[agentId]
    }
    persist()
    return true
  }

  function bindRoleProfile(agentId: string, profileId: string) {
    if (!profiles.value.some((item) => item.id === profileId)) return false
    roleBindings.value[agentId] = profileId
    persist()
    return true
  }

  function unbindRoleProfile(agentId: string) {
    delete roleBindings.value[agentId]
    persist()
  }

  function getRoleBoundProfileId(agentId: string) {
    return roleBindings.value[agentId] ?? null
  }

  function getRoleBoundProfile(agentId: string) {
    const id = getRoleBoundProfileId(agentId)
    if (!id) return null
    return profiles.value.find((item) => item.id === id) ?? null
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

  return {
    profiles,
    activeProfileId,
    roleBindings,
    activeProfile,
    settings,
    activateProfile,
    save,
    saveActiveProfileName,
    createNewProfile,
    duplicateActiveProfile,
    deleteProfile,
    bindRoleProfile,
    unbindRoleProfile,
    getRoleBoundProfileId,
    getRoleBoundProfile,
    isConfigured,
    effectiveModel,
  }
})
