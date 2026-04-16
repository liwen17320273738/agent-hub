import { apiUrl } from './enterpriseApi'
import { getAuthToken } from './api'

function authHeaders(): HeadersInit {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export interface DeliveryDocMeta {
  name: string
  title: string
  description: string
  exists: boolean
  updatedAt: number | null
}

export interface DeliveryDoc extends Omit<DeliveryDocMeta, 'exists'> {
  content: string
}

export async function initDeliveryDocs(): Promise<DeliveryDocMeta[]> {
  const response = await fetch(apiUrl('/delivery-docs/init'), {
    method: 'POST',
    credentials: 'same-origin',
    headers: { ...authHeaders() },
  })
  if (!response.ok) throw new Error('初始化交付文档失败')
  const data = await response.json()
  return data.docs as DeliveryDocMeta[]
}

export async function listDeliveryDocs(): Promise<DeliveryDocMeta[]> {
  const response = await fetch(apiUrl('/delivery-docs'), {
    credentials: 'same-origin',
    headers: { ...authHeaders() },
  })
  if (!response.ok) throw new Error('读取交付文档列表失败')
  const data = await response.json()
  return data.docs as DeliveryDocMeta[]
}

export async function readDeliveryDoc(name: string): Promise<DeliveryDoc> {
  const response = await fetch(apiUrl(`/delivery-docs/${encodeURIComponent(name)}`), {
    credentials: 'same-origin',
    headers: { ...authHeaders() },
  })
  if (!response.ok) throw new Error('读取交付文档失败')
  return (await response.json()) as DeliveryDoc
}

export async function writeDeliveryDoc(name: string, content: string): Promise<DeliveryDoc> {
  const response = await fetch(apiUrl(`/delivery-docs/${encodeURIComponent(name)}`), {
    method: 'PUT',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ content }),
  })
  if (!response.ok) throw new Error('保存交付文档失败')
  return (await response.json()) as DeliveryDoc
}
