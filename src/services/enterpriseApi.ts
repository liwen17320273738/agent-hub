/** 构建为「企业模式」时启用：登录、服务端会话、组织级共享对话、LLM 走服务端代理 */
export const isEnterpriseBuild = import.meta.env.VITE_ENTERPRISE === 'true'

/**
 * 浏览器访问的 API 前缀。
 * - 开发：默认 `/api/hub`，由 Vite 代理到 Node 并去掉前缀。
 * - 生产：默认 `''`（与 `pnpm build && node server` 同域同端口时 API 在根路径 `/auth`、`/llm` 等）。
 * - 前后端分离部署时设置 `VITE_API_BASE=https://api.example.com` 或 `https://app.example.com/api/hub`。
 */
export function getApiBase(): string {
  const raw = import.meta.env.VITE_API_BASE
  if (raw === '') return ''
  if (typeof raw === 'string' && raw.trim()) return raw.replace(/\/$/, '')
  if (import.meta.env.PROD) return ''
  return '/api/hub'
}

export function apiUrl(path: string): string {
  const base = getApiBase()
  const p = path.startsWith('/') ? path : `/${path}`
  return `${base}${p}`
}

export function shouldUseBackendLlm(): boolean {
  return isEnterpriseBuild
}
