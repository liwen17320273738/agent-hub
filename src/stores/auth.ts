import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiUrl, isEnterpriseBuild } from '@/services/enterpriseApi'

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
    if (!isEnterpriseBuild) {
      initialized.value = true
      return
    }
    try {
      const r = await fetch(apiUrl('/auth/me'), { credentials: 'include' })
      if (r.ok) {
        const data = (await r.json()) as {
          user: AuthUser
          llmConfigured: boolean
          publicLlm: PublicLlmMeta | null
        }
        user.value = data.user
        llmConfigured.value = data.llmConfigured
        publicLlm.value = data.publicLlm
        await pullEnterpriseConversations()
      } else {
        user.value = null
        llmConfigured.value = false
        publicLlm.value = null
        await clearChatOnEnterpriseSessionEnd()
      }
    } catch {
      user.value = null
      llmConfigured.value = false
      publicLlm.value = null
    } finally {
      initialized.value = true
    }
  }

  async function login(email: string, password: string): Promise<void> {
    const r = await fetch(apiUrl('/auth/login'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    const data = await r.json().catch(() => ({}))
    if (!r.ok) {
      throw new Error(typeof data.error === 'string' ? data.error : '登录失败')
    }
    user.value = data.user
    llmConfigured.value = !!data.llmConfigured
    publicLlm.value = data.publicLlm ?? null
    await pullEnterpriseConversations()
  }

  async function logout(): Promise<void> {
    try {
      await fetch(apiUrl('/auth/logout'), { method: 'POST', credentials: 'include' })
    } catch {
      /* ignore */
    }
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
