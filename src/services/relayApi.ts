import { apiFetch } from '@/services/api'

export interface RelayBalance {
  relay_balance_usd: number
}

export interface RelayPolicy {
  markup_multiplier: number
  fallback_usd_per_1k_total: number
  min_balance_usd: number
  rate_limit_per_minute: number
}

export interface RelayKeyPublic {
  id: string
  name: string
  key_prefix: string
  created_at: string | null
  last_used_at: string | null
}

export interface RelayKeyCreated extends RelayKeyPublic {
  plaintext_key: string
}

export async function fetchRelayBalance(): Promise<RelayBalance> {
  return apiFetch<RelayBalance>('/relay/balance')
}

export async function fetchRelayPolicy(): Promise<RelayPolicy> {
  return apiFetch<RelayPolicy>('/relay/policy')
}

export async function topupRelayBalance(amount_usd: number): Promise<RelayBalance> {
  return apiFetch<RelayBalance>('/relay/balance/topup', {
    method: 'POST',
    body: JSON.stringify({ amount_usd }),
  })
}

export async function fetchRelayKeys(): Promise<RelayKeyPublic[]> {
  return apiFetch<RelayKeyPublic[]>('/relay/keys')
}

export async function createRelayKey(name: string): Promise<RelayKeyCreated> {
  return apiFetch<RelayKeyCreated>('/relay/keys', {
    method: 'POST',
    body: JSON.stringify({ name: name || '' }),
  })
}

export async function revokeRelayKey(keyId: string): Promise<void> {
  await apiFetch(`/relay/keys/${keyId}`, { method: 'DELETE' })
}
