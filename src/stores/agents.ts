/**
 * Agent Store — single source of truth, loaded from backend /api/agents.
 *
 * Replaces the static src/agents/registry.ts for all runtime usage.
 * Falls back to registry.ts data if the API is unreachable (offline mode).
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiFetch } from '@/services/api'
import { agents as staticAgents } from '@/agents/registry'
import type { AgentConfig } from '@/agents/types'

export interface ToolBinding {
  name: string
  description: string
  permissions: string[]
}

export interface AgentSkillBinding {
  id: string
  skill_id: string
  config: Record<string, unknown>
  enabled: boolean
}

export interface AgentProfile {
  id: string
  name: string
  title: string
  icon: string
  color: string
  description: string
  systemPrompt: string
  quickPrompts: string[]
  category: 'core' | 'support' | 'pipeline'
  pipelineRole?: string
  capabilities: Record<string, unknown>
  preferredModel?: string
  maxTokens: number
  temperature: number
  isActive: boolean
  tools: ToolBinding[]
  skills: AgentSkillBinding[]
}

function mapBackendAgent(raw: Record<string, unknown>): AgentProfile {
  return {
    id: raw.id as string,
    name: raw.name as string,
    title: raw.title as string,
    icon: raw.icon as string,
    color: raw.color as string,
    description: raw.description as string,
    systemPrompt: raw.system_prompt as string,
    quickPrompts: (raw.quick_prompts as string[]) || [],
    category: raw.category as 'core' | 'support' | 'pipeline',
    pipelineRole: raw.pipeline_role as string | undefined,
    capabilities: (raw.capabilities as Record<string, unknown>) || {},
    preferredModel: raw.preferred_model as string | undefined,
    maxTokens: (raw.max_tokens as number) || 4096,
    temperature: (raw.temperature as number) || 0.7,
    isActive: raw.is_active !== false,
    tools: (raw.tools as ToolBinding[]) || [],
    skills: (raw.skills as AgentSkillBinding[]) || [],
  }
}

/**
 * Collapse workspace clones (e.g. wayne-ceo) that mirror seed agents (Agent-ceo) on the same
 * pipeline slot so Team / counts show one card per role. Full `agents` stays complete for getAgent().
 */
function dedupeProfilesBySlot(list: AgentProfile[]): AgentProfile[] {
  const sorted = [...list].sort((a, b) => {
    const seedA = a.id.startsWith('Agent-') ? 0 : 1
    const seedB = b.id.startsWith('Agent-') ? 0 : 1
    if (seedA !== seedB) return seedA - seedB
    return a.id.localeCompare(b.id)
  })
  const seen = new Set<string>()
  const out: AgentProfile[] = []
  for (const a of sorted) {
    const slot = `${a.category}:${a.pipelineRole ?? a.name}`
    if (seen.has(slot)) continue
    seen.add(slot)
    out.push(a)
  }
  return out
}

function staticToProfile(a: AgentConfig): AgentProfile {
  return {
    id: a.id,
    name: a.name,
    title: a.title,
    icon: a.icon,
    color: a.color,
    description: a.description,
    systemPrompt: a.systemPrompt,
    quickPrompts: a.quickPrompts,
    category: a.category,
    pipelineRole: a.pipelineRole,
    capabilities: {},
    preferredModel: undefined,
    maxTokens: 4096,
    temperature: 0.7,
    isActive: true,
    tools: [],
    skills: [],
  }
}

export const useAgentStore = defineStore('agents', () => {
  const agents = ref<AgentProfile[]>([])
  const loaded = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const coreAgents = computed(() =>
    dedupeProfilesBySlot(agents.value.filter((a) => a.category === 'core')),
  )
  const pipelineAgents = computed(() => agents.value.filter((a) => a.category === 'pipeline'))
  const supportAgents = computed(() =>
    dedupeProfilesBySlot(agents.value.filter((a) => a.category === 'support')),
  )

  function getAgent(id: string): AgentProfile | undefined {
    return agents.value.find((a) => a.id === id)
  }

  function agentAsConfig(profile: AgentProfile): AgentConfig {
    return {
      id: profile.id,
      name: profile.name,
      title: profile.title,
      icon: profile.icon,
      color: profile.color,
      description: profile.description,
      systemPrompt: profile.systemPrompt,
      quickPrompts: profile.quickPrompts,
      category: profile.category,
      pipelineRole: profile.pipelineRole as AgentConfig['pipelineRole'],
    }
  }

  async function fetchAgents() {
    if (loading.value) return
    loading.value = true
    error.value = null
    try {
      const raw = await apiFetch<Record<string, unknown>[]>('/agents/')
      agents.value = raw.map(mapBackendAgent)
      loaded.value = true
    } catch (e) {
      error.value = (e as Error).message
      if (!loaded.value) {
        agents.value = staticAgents.map(staticToProfile)
        loaded.value = true
      }
    } finally {
      loading.value = false
    }
  }

  return {
    agents,
    loaded,
    loading,
    error,
    coreAgents,
    pipelineAgents,
    supportAgents,
    getAgent,
    agentAsConfig,
    fetchAgents,
  }
})
