<template>
  <div class="relay-panel">
    <p class="tab-lead">{{ t('assets.relay.lead') }}</p>

    <el-alert v-if="policy" type="info" :closable="false" show-icon class="policy-alert">
      <template #title>{{ t('assets.relay.policyTitle') }}</template>
      <div class="policy-lines">
        <div>
          {{ t('assets.relay.policyMarkup') }}
          <strong class="mono">{{ policy.markup_multiplier }}</strong>
        </div>
        <div>
          {{ t('assets.relay.policyFallback') }}
          <strong class="mono">{{ policy.fallback_usd_per_1k_total }}</strong>
          {{ t('assets.relay.policyPer1k') }}
        </div>
        <div>
          {{ t('assets.relay.policyRateLimit') }}
          <strong class="mono">{{ policy.rate_limit_per_minute }}</strong>
          {{ t('assets.relay.policyPerMin') }}
        </div>
        <div>
          {{ t('assets.relay.policyMinBalance') }}
          <strong class="mono">{{ policy.min_balance_usd }}</strong>
        </div>
      </div>
      <p class="policy-note">{{ t('assets.relay.policyNote') }}</p>
    </el-alert>

    <el-row :gutter="16" class="relay-row">
      <el-col :xs="24" :md="12">
        <el-card shadow="never">
          <div class="balance-line">
            <span class="label">{{ t('assets.relay.balanceUsd') }}</span>
            <strong class="amount">{{ balanceText }}</strong>
            <el-button text type="primary" :loading="balanceLoading" @click="loadBalance">
              {{ t('assets.relay.refresh') }}
            </el-button>
          </div>
          <template v-if="canTopup">
            <div class="topup-line">
              <el-input-number
                v-model="topupAmount"
                :min="0.01"
                :max="1_000_000"
                :step="1"
                :precision="2"
                controls-position="right"
              />
              <el-button type="primary" :loading="topupLoading" @click="onTopup">
                {{ t('assets.relay.topup') }}
              </el-button>
            </div>
            <p class="hint-muted">{{ t('assets.relay.topupHint') }}</p>
          </template>
          <el-alert v-else type="info" :closable="false" class="mt-2">
            {{ t('assets.relay.topupAdminOnly') }}
          </el-alert>
        </el-card>
      </el-col>
      <el-col :xs="24" :md="12">
        <el-card shadow="never">
          <div class="snippet-title">{{ t('assets.relay.curlTitle') }}</div>
          <pre class="curl-snippet">{{ curlSnippet }}</pre>
          <el-button size="small" @click="copySnippet">{{ t('assets.relay.copySnippet') }}</el-button>
        </el-card>
      </el-col>
    </el-row>

    <div class="keys-toolbar">
      <el-button type="primary" :loading="keysLoading" @click="openCreateDialog">
        {{ t('assets.relay.createKey') }}
      </el-button>
    </div>

    <el-table :data="keys" v-loading="keysLoading" stripe size="small" class="keys-table">
      <el-table-column prop="name" :label="t('assets.relay.colName')" min-width="100">
        <template #default="{ row }">{{ row.name || '—' }}</template>
      </el-table-column>
      <el-table-column prop="key_prefix" :label="t('assets.relay.colPrefix')" min-width="160" />
      <el-table-column prop="created_at" :label="t('assets.relay.colCreated')" min-width="160" />
      <el-table-column prop="last_used_at" :label="t('assets.relay.colLastUsed')" min-width="160">
        <template #default="{ row }">{{ row.last_used_at || '—' }}</template>
      </el-table-column>
      <el-table-column :label="t('assets.relay.colActions')" width="100" fixed="right">
        <template #default="{ row }">
          <el-button text type="danger" size="small" @click="confirmRevoke(row)">
            {{ t('assets.relay.revoke') }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createVisible" :title="t('assets.relay.createKey')" width="480px" @close="createName = ''">
      <el-form label-position="top">
        <el-form-item :label="t('assets.relay.keyNameOptional')">
          <el-input v-model="createName" maxlength="100" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="createLoading" @click="submitCreate">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="secretVisible" :title="t('assets.relay.secretTitle')" width="560px" @closed="newPlaintext = ''">
      <el-alert type="warning" :closable="false" show-icon class="mb-3">
        {{ t('assets.relay.secretWarn') }}
      </el-alert>
      <el-input :model-value="newPlaintext" readonly type="textarea" :rows="3" class="secret-input" />
      <template #footer>
        <el-button type="primary" @click="copyPlaintext">{{ t('assets.relay.copyKey') }}</el-button>
        <el-button @click="secretVisible = false">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/services/api'
import {
  createRelayKey,
  fetchRelayBalance,
  fetchRelayKeys,
  fetchRelayPolicy,
  revokeRelayKey,
  topupRelayBalance,
  type RelayKeyPublic,
  type RelayPolicy,
} from '@/services/relayApi'

const { t } = useI18n()
const authStore = useAuthStore()

const balanceUsd = ref<number | null>(null)
const balanceLoading = ref(false)
const policy = ref<RelayPolicy | null>(null)
const topupAmount = ref(10)
const topupLoading = ref(false)
const keys = ref<RelayKeyPublic[]>([])
const keysLoading = ref(false)
const createVisible = ref(false)
const createName = ref('')
const createLoading = ref(false)
const secretVisible = ref(false)
const newPlaintext = ref('')

const canTopup = computed(() => {
  const r = authStore.user?.role
  return r === 'admin' || r === 'manager'
})

const balanceText = computed(() => {
  if (balanceUsd.value == null) return '—'
  return balanceUsd.value.toFixed(6)
})

const curlSnippet = computed(() => {
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  return [
    `curl -sS "${origin}/v1/chat/completions" \\`,
    `  -H "Authorization: Bearer YOUR_RELAY_KEY" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"model":"YOUR_MODEL","messages":[{"role":"user","content":"Hello"}]}'`,
  ].join('\n')
})

function errDetail(e: unknown): string {
  if (e instanceof ApiError) return e.detail
  if (e instanceof Error) return e.message
  return String(e)
}

async function loadBalance() {
  balanceLoading.value = true
  try {
    const b = await fetchRelayBalance()
    balanceUsd.value = b.relay_balance_usd
  } catch (e) {
    ElMessage.error(errDetail(e))
  } finally {
    balanceLoading.value = false
  }
}

async function loadKeys() {
  keysLoading.value = true
  try {
    keys.value = await fetchRelayKeys()
  } catch (e) {
    ElMessage.error(errDetail(e))
  } finally {
    keysLoading.value = false
  }
}

async function onTopup() {
  const n = Number(topupAmount.value)
  if (!Number.isFinite(n) || n <= 0) {
    ElMessage.warning(t('assets.relay.topupInvalid'))
    return
  }
  topupLoading.value = true
  try {
    const b = await topupRelayBalance(n)
    balanceUsd.value = b.relay_balance_usd
    ElMessage.success(t('assets.relay.topupOk'))
  } catch (e) {
    ElMessage.error(errDetail(e))
  } finally {
    topupLoading.value = false
  }
}

function openCreateDialog() {
  createName.value = ''
  createVisible.value = true
}

async function submitCreate() {
  createLoading.value = true
  try {
    const created = await createRelayKey(createName.value.trim())
    createVisible.value = false
    newPlaintext.value = created.plaintext_key
    secretVisible.value = true
    await loadKeys()
  } catch (e) {
    ElMessage.error(errDetail(e))
  } finally {
    createLoading.value = false
  }
}

async function copyPlaintext() {
  try {
    await navigator.clipboard.writeText(newPlaintext.value)
    ElMessage.success(t('assets.relay.copied'))
  } catch {
    ElMessage.error(t('assets.relay.copyFailed'))
  }
}

async function copySnippet() {
  try {
    await navigator.clipboard.writeText(curlSnippet.value)
    ElMessage.success(t('assets.relay.copied'))
  } catch {
    ElMessage.error(t('assets.relay.copyFailed'))
  }
}

function confirmRevoke(row: RelayKeyPublic) {
  ElMessageBox.confirm(t('assets.relay.revokeConfirm'), t('assets.relay.revoke'), {
    type: 'warning',
    confirmButtonText: t('common.confirm'),
    cancelButtonText: t('common.cancel'),
  })
    .then(async () => {
      try {
        await revokeRelayKey(row.id)
        ElMessage.success(t('assets.relay.revoked'))
        await loadKeys()
      } catch (e) {
        ElMessage.error(errDetail(e))
      }
    })
    .catch(() => {})
}

async function loadPolicy() {
  try {
    policy.value = await fetchRelayPolicy()
  } catch {
    policy.value = null
  }
}

onMounted(() => {
  loadPolicy()
  loadBalance()
  loadKeys()
})
</script>

<style scoped>
.relay-panel {
  width: 100%;
  max-width: 1100px;
}
.policy-alert {
  margin-bottom: 16px;
}
.policy-lines {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  margin-top: 4px;
}
.policy-lines .mono {
  font-family: ui-monospace, monospace;
  margin-left: 4px;
}
.policy-note {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.45;
}
.tab-lead {
  margin: 0 0 16px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
  line-height: 1.5;
}
.relay-row {
  margin-bottom: 20px;
}
.balance-line {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.balance-line .label {
  color: var(--el-text-color-secondary);
}
.balance-line .amount {
  font-size: 1.25rem;
}
.topup-line {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.hint-muted {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.mt-2 {
  margin-top: 12px;
}
.mb-3 {
  margin-bottom: 12px;
}
.snippet-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.curl-snippet {
  margin: 0 0 12px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.45;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.keys-toolbar {
  margin-bottom: 12px;
}
.keys-table {
  width: 100%;
}
.secret-input :deep(.el-textarea__inner) {
  font-family: ui-monospace, monospace;
  font-size: 13px;
}
</style>
