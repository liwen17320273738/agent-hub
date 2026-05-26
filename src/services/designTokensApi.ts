/**
 * Design Tokens API — fetches parsed design tokens from the backend.
 */
import { getAuthToken } from './api'

export interface DesignTokens {
  colors: Record<string, string>
  typography: Record<string, string>
  spacing: Record<string, string>
}

export interface DesignTokensResponse {
  task_id: string
  tokens: DesignTokens
  cached?: boolean
}

export async function fetchDesignTokens(taskId: string): Promise<DesignTokens> {
  const baseUrl = import.meta.env.VITE_API_BASE || '/api'
  const token = getAuthToken()
  const res = await fetch(
    `${baseUrl}/tasks/${taskId}/design-tokens`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  )
  if (!res.ok) {
    return { colors: {}, typography: {}, spacing: {} }
  }
  const data: DesignTokensResponse = await res.json()
  return data.tokens
}

const CSS_VARIABLE_MAP: Record<string, Record<string, string>> = {
  colors: {
    primary: '--dt-color-primary',
    secondary: '--dt-color-secondary',
    background: '--dt-color-background',
    text: '--dt-color-text',
    accent: '--dt-color-accent',
  },
  typography: {
    '正文字号': '--dt-font-size-body',
    '标题字号': '--dt-font-size-heading',
    '字体族': '--dt-font-family',
  },
  spacing: {
    '间距': '--dt-spacing',
    '圆角': '--dt-border-radius',
  },
}

/**
 * Apply design tokens as CSS custom properties on the document root.
 */
export function applyDesignTokens(tokens: DesignTokens): void {
  const root = document.documentElement

  for (const [category, keys] of Object.entries(CSS_VARIABLE_MAP)) {
    const values = (tokens as any)[category] || {}
    for (const [key, cssVar] of Object.entries(keys)) {
      const value = values[key] || (values as any)[key]
      if (value) {
        root.style.setProperty(cssVar, value)
      }
    }
  }

  // Also apply generic color tokens not in the predefined map
  for (const [name, value] of Object.entries(tokens.colors)) {
    const cssVar = `--dt-color-${name.replace(/\s+/g, '-')}`
    root.style.setProperty(cssVar, value)
  }
}

/**
 * Clear all applied design token CSS custom properties.
 */
export function clearDesignTokens(): void {
  const root = document.documentElement
  for (const category of Object.values(CSS_VARIABLE_MAP)) {
    for (const cssVar of Object.values(category)) {
      root.style.removeProperty(cssVar)
    }
  }
}
