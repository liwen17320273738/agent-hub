import { describe, it, expect } from 'vitest'

import { TOOL_DEFINITIONS, executeTool } from '../tools'

describe('tools', () => {
  describe('TOOL_DEFINITIONS', () => {
    it('has 3 tool definitions', () => {
      expect(TOOL_DEFINITIONS).toHaveLength(3)
    })

    it('each tool has required fields', () => {
      for (const tool of TOOL_DEFINITIONS) {
        expect(tool.type).toBe('function')
        expect(tool.function.name).toBeTruthy()
        expect(tool.function.description).toBeTruthy()
        expect(tool.function.parameters).toBeDefined()
      }
    })

    it('tool names are unique', () => {
      const names = TOOL_DEFINITIONS.map(t => t.function.name)
      expect(new Set(names).size).toBe(names.length)
    })
  })

  describe('executeTool', () => {
    it('get_current_datetime returns a non-empty string', () => {
      const result = executeTool('get_current_datetime', '{}')
      expect(result).toBeTruthy()
      expect(result.length).toBeGreaterThan(5)
    })

    it('text_word_count counts characters and CJK', () => {
      const result = executeTool('text_word_count', JSON.stringify({ text: 'Hello世界' }))
      const parsed = JSON.parse(result)
      expect(parsed['字符数']).toBe(7)
      expect(parsed['汉字约数']).toBe(2)
    })

    it('text_word_count handles empty text', () => {
      const result = executeTool('text_word_count', JSON.stringify({ text: '' }))
      const parsed = JSON.parse(result)
      expect(parsed['字符数']).toBe(0)
      expect(parsed['汉字约数']).toBe(0)
    })

    it('random_integer returns a number in range', () => {
      const result = executeTool('random_integer', JSON.stringify({ min: 1, max: 10 }))
      const parsed = JSON.parse(result)
      expect(parsed.value).toBeGreaterThanOrEqual(1)
      expect(parsed.value).toBeLessThanOrEqual(10)
    })

    it('random_integer handles swapped min/max', () => {
      const result = executeTool('random_integer', JSON.stringify({ min: 10, max: 1 }))
      const parsed = JSON.parse(result)
      expect(parsed.value).toBeGreaterThanOrEqual(1)
      expect(parsed.value).toBeLessThanOrEqual(10)
    })

    it('random_integer rejects too-large range', () => {
      const result = executeTool('random_integer', JSON.stringify({ min: 0, max: 2000000 }))
      const parsed = JSON.parse(result)
      expect(parsed.error).toBeTruthy()
    })

    it('unknown tool returns error', () => {
      const result = executeTool('nonexistent_tool', '{}')
      const parsed = JSON.parse(result)
      expect(parsed.error).toContain('未知工具')
    })
  })
})
