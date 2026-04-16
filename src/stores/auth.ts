import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiUrl, isEnterpriseBuild } from '@/services/enterpriseApi'
import { setAuthToken } from '@/services/api'

export interface AuthUser {
  id: string
  email: string
  displayName: string
  role: 'admin' | 'member'
  orgId: string
  orgName: string
}

export interface PublicLlmMeta {
  model: string
  host: string
}

async function clearChatOnEnterpriseSessionEnd() {
  const { useChatStore } = await import('@/stores/chat')
  useChatStore().resetConversationsForEnterpriseLogout()
}

async function pullEnterpriseConversations() {
  const { useChatStore } = await import('@/stores/chat')
  await useChatStore().loadRemoteConversations()
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const llmConfigured = ref(false)
  const publicLlm = ref<PublicLlmMeta | null>(null)
  const initialized = ref(false)

  const isLoggedIn = computed(() => !!user.value)

  async function hydrate(): Promise<void> {
    try {
      const { getAuthToken } = await import('@/services/api')
      const token = getAuthToken()

      // Enterprise mode: use session cookie; standalone mode: use localStorage JWT
      const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {}
      const credentials: RequestCredentials = isEnterpriseBuild ? 'include' : 'same-origin'

      const r = await fetch(apiUrl('/auth/me'), { credentials, headers })
      if (r.ok) {
        const raw = await r.json()
        // /auth/me returns the user object directly (snake_case from backend)
        const u = raw.user ?? raw
        user.value = {
          id: u.id,
          email: u.email,
          displayName: u.display_name ?? u.displayName ?? u.email,
          role: u.role,
          orgId: u.org_id ?? u.orgId ?? '',
          orgName: u.org_name ?? u.orgName ?? '',
        }
        llmConfigured.value = raw.llmConfigured ?? true
        publicLlm.value = raw.publicLlm ?? null
        if (isEnterpriseBuild) await pullEnterpriseConversations()
      } else if (r.status === 401 || r.status === 403) {
        setAuthToken(null)
        user.value = null
        llmConfigured.value = false
        publicLlm.value = null
        if (isEnterpriseBuild) await clearChatOnEnterpriseSessionEnd()
      }
      // Other HTTP errors (500, network issues): keep existing user state
    } catch {
      // Network failure: don't clear user — they might just be offline
    } finally {
      initialized.value = true
    }
  }

  async function login(email: string, password: string): Promise<void> {
    const r = await fetch(apiUrl('/auth/login'), {
      method: 'POST',
      credentials: isEnterpriseBuild ? 'include' : 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    const data = await r.json().catch(() => ({}))
    if (!r.ok) {
      throw new Error(data.detail ?? (typeof data.error === 'string' ? data.error : '登录失败'))
    }
    if (data.access_token) {
      setAuthToken(data.access_token)
    }
    const u = data.user ?? {}
    user.value = {
      id: u.id,
      email: u.email,
      displayName: u.display_name ?? u.displayName ?? u.email,
      role: u.role,
      orgId: u.org_id ?? u.orgId ?? '',
      orgName: u.org_name ?? u.orgName ?? '',
    }
    llmConfigured.value = !!data.llmConfigured
    publicLlm.value = data.publicLlm ?? null
    if (isEnterpriseBuild) await pullEnterpriseConversations()
  }

  async function logout(): Promise<void> {
    try {
      await fetch(apiUrl('/auth/logout'), { method: 'POST', credentials: 'include' })
    } catch {
      /* ignore */
    }
    setAuthToken(null)
    user.value = null
    llmConfigured.value = false
    publicLlm.value = null
    await clearChatOnEnterpriseSessionEnd()
  }

  return {
    user,
    llmConfigured,
    publicLlm,
    initialized,
    isLoggedIn,
    hydrate,
    login,
    logout,
  }
})
