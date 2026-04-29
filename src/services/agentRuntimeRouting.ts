/**
 * Agent Runtime Routing — maps frontend AgentConfig to backend stream endpoint keys.
 *
 * The backend `/agents/{agent_id}/run/stream` endpoint accepts either:
 *   - a seed id (e.g. 'wayne-developer')
 *   - a role alias (e.g. 'developer')
 *
 * This module centralises the mapping so AgentChat.vue (and any other UI surface)
 * can resolve the correct key without duplicating role tables.
 */

import type { AgentConfig } from '@/agents/types'

/** Role aliases understood by the backend ROLE_TO_SEED_ID table. */
const ROLE_ALIASES: Record<string, string> = {
  'wayne-ceo': 'ceo',
  'wayne-cto': 'cto',
  'wayne-product': 'product',
  'wayne-developer': 'developer',
  'wayne-qa': 'qa',
  'wayne-designer': 'designer',
  'wayne-devops': 'devops',
  'wayne-security': 'security',
  'wayne-acceptance': 'acceptance',
  'wayne-data': 'data',
  'wayne-marketing': 'marketing',
  'wayne-finance': 'finance',
  'wayne-legal': 'legal',
}

/**
 * Resolve the stream key for an agent.
 * Returns the agent's id (seed id) directly — the backend's
 * `_resolve_seed_id` handles both seed ids and role aliases.
 */
export function resolveStreamAgentKey(ag: AgentConfig): string | null {
  if (!ag?.id) return null
  // Backend accepts seed ids directly, so we can pass ag.id as-is.
  // If we ever need role aliases, map through ROLE_ALIASES here.
  return ag.id
}

/** Reverse lookup: given a role alias, return the canonical seed id. */
export function resolveSeedIdFromRole(role: string): string | null {
  const alias = role.toLowerCase()
  for (const [seedId, mappedRole] of Object.entries(ROLE_ALIASES)) {
    if (mappedRole === alias) return seedId
  }
  return null
}
