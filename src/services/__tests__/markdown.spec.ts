/**
 * Unit tests for the markdown rendering service.
 *
 * Covers: HTML escaping, heading levels, bold, code, lists, line breaks.
 */
import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../markdown'

describe('markdown.ts', () => {
  it('returns empty string for falsy input', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown(null as unknown as string)).toBe('')
    expect(renderMarkdown(undefined as unknown as string)).toBe('')
  })

  it('escapes HTML entities in input', () => {
    const result = renderMarkdown('<script>alert("xss")</script>')
    expect(result).not.toContain('<script>')
    expect(result).toContain('&lt;script&gt;')
  })

  it('renders h1 headings', () => {
    expect(renderMarkdown('# Title')).toContain('<h2>Title</h2>')
  })

  it('renders h2 headings', () => {
    expect(renderMarkdown('## Section')).toContain('<h3>Section</h3>')
  })

  it('renders h3 headings', () => {
    expect(renderMarkdown('### Subsection')).toContain('<h4>Subsection</h4>')
  })

  it('renders bold text', () => {
    expect(renderMarkdown('This is **important**')).toContain('<strong>important</strong>')
  })

  it('renders inline code', () => {
    expect(renderMarkdown('Use `pip install`')).toContain('<code>pip install</code>')
  })

  it('renders unordered list items', () => {
    expect(renderMarkdown('- First item')).toContain('<li>First item</li>')
  })

  it('renders ordered list items', () => {
    expect(renderMarkdown('1. Step one')).toContain('<li>Step one</li>')
  })

  it('converts double newlines to br tags', () => {
    const result = renderMarkdown('Line 1\n\nLine 2')
    expect(result).toContain('<br/><br/>')
  })

  it('converts single newlines to br tags', () => {
    const result = renderMarkdown('Line 1\nLine 2')
    expect(result).toContain('<br/>')
  })
})
