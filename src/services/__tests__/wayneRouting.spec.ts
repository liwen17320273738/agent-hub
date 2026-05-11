import { describe, it, expect } from 'vitest'

import {
  Agent_COST_MODE_OPTIONS,
  type AgentCostMode,
  type AgentRoleKey,
} from '../wayneRouting'

describe('wayneRouting', () => {
  it('Agent_COST_MODE_OPTIONS has 4 cost modes', () => {
    expect(Agent_COST_MODE_OPTIONS).toHaveLength(4)
    const values = Agent_COST_MODE_OPTIONS.map(o => o.value)
    expect(values).toContain('economy')
    expect(values).toContain('balanced')
    expect(values).toContain('quality')
    expect(values).toContain('critical')
  })

  it('each cost mode has label and description', () => {
    for (const mode of Agent_COST_MODE_OPTIONS) {
      expect(mode.label).toBeTruthy()
      expect(mode.description).toBeTruthy()
      expect(mode.description.length).toBeGreaterThan(5)
    }
  })
})
