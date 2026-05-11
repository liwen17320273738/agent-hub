/**
 * Unit tests for the agent runtime routing service.
 *
 * Covers: stream key resolution, seed ID from role, edge cases.
 */
import { describe, expect, it } from 'vitest'
import { resolveStreamAgentKey, resolveSeedIdFromRole } from '../agentRuntimeRouting'

// Minimal AgentConfig stub matching the interface
function makeAgent(id: string) {
  return { id, name: id, title: id, icon: '', color: '', description: '', system_prompt: '', quick_prompts: [], category: 'core' as const, capabilities: {}, max_tokens: 4096, temperature: 0.7, is_active: true, skills: [], rules: [], hooks: [], plugins: [], mcps: [] }
}

describe('agentRuntimeRouting', () => {
  describe('resolveStreamAgentKey', () => {
    it('returns the agent id directly', () => {
      expect(resolveStreamAgentKey(makeAgent('Agent-developer'))).toBe('Agent-developer')
    })

    it('returns null for null input', () => {
      expect(resolveStreamAgentKey(null as unknown as ReturnType<typeof makeAgent>)).toBeNull()
    })

    it('returns null for agent without id', () => {
      expect(resolveStreamAgentKey({} as ReturnType<typeof makeAgent>)).toBeNull()
    })
  })

  describe('resolveSeedIdFromRole', () => {
    it('resolves developer role', () => {
      expect(resolveSeedIdFromRole('developer')).toBe('Agent-developer')
    })

    it('resolves ceo role', () => {
      expect(resolveSeedIdFromRole('ceo')).toBe('Agent-ceo')
    })

    it('is case-insensitive', () => {
      expect(resolveSeedIdFromRole('Developer')).toBe('Agent-developer')
      expect(resolveSeedIdFromRole('CEO')).toBe('Agent-ceo')
    })

    it('returns null for unknown role', () => {
      expect(resolveSeedIdFromRole('nonexistent')).toBeNull()
    })
  })
})
