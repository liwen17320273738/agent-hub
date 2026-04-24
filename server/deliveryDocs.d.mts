type DeliveryDocDef = {
  name: string
  title: string
  description: string
  template: string
}

export const DELIVERY_DIR: string
export const DELIVERY_DOCS: readonly DeliveryDocDef[]

export function ensureDeliveryDir(): Promise<void>
export function ensureDeliveryTemplates(): Promise<void>
export function listDeliveryDocs(): Promise<
  (DeliveryDocDef & { exists: boolean; updatedAt: number | null })[]
>
export function readDeliveryDoc(
  name: string,
): Promise<{
  name: string
  title: string
  description: string
  content: string
  updatedAt: number
}>
export function writeDeliveryDoc(
  name: string,
  content: string,
): Promise<{
  name: string
  title: string
  description: string
  content: string
  updatedAt: number
}>
