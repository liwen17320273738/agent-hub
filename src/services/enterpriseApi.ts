/**
 * Enterprise mode flag.
 * With unified Python backend, enterprise mode is always available.
 * Set VITE_ENTERPRISE=true to enable login/auth features in the UI.
 */
export const isEnterpriseBuild = import.meta.env.VITE_ENTERPRISE === 'true'

/**
 * Unified API base URL — always points to the Python FastAPI backend.
 * - Dev: `/api` — Vite proxy forwards to http://127.0.0.1:8000
 * - Prod: `/api` — Nginx proxies to backend container
 * - Custom: set VITE_API_BASE for separate domain deployment
 */
export function getApiBase(): string {
  const raw = import.meta.env.VITE_API_BASE
  if (typeof raw === 'string' && raw.trim()) return raw.replace(/\/$/, '')
  return '/api'
}

export function apiUrl(path: string): string {
  const base = getApiBase()
  const p = path.startsWith('/') ? path : `/${path}`
  return `${base}${p}`
}

export function shouldUseBackendLlm(): boolean {
  return isEnterpriseBuild
}
