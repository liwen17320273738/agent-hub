<template>
  <div class="ws-switcher">
    <el-dropdown trigger="click" @command="switchWorkspace">
      <div class="ws-current">
        <el-icon><OfficeBuilding /></el-icon>
        <span class="ws-name">{{ currentWs?.name || $t('workspace.title') }}</span>
        <el-icon class="ws-arrow"><ArrowDown /></el-icon>
      </div>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="ws in workspaces"
            :key="ws.id"
            :command="ws.id"
            :class="{ active: ws.id === currentWsId }"
          >
            {{ ws.name }}
            <el-tag v-if="ws.is_default" size="small" type="info" style="margin-left: 6px">{{ $t('workspace.default') }}</el-tag>
          </el-dropdown-item>
          <el-dropdown-item divided command="__create__">
            <el-icon><Plus /></el-icon> {{ $t('workspace.create') }}
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>

    <el-dialog v-model="showCreate" :title="$t('workspace.create')" width="420px">
      <el-form label-width="60px">
        <el-form-item :label="$t('workspace.name')">
          <el-input v-model="newName" maxlength="50" />
        </el-form-item>
        <el-form-item :label="$t('workspace.description')">
          <el-input v-model="newDesc" type="textarea" :rows="2" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="creating" @click="createWs">{{ $t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()

interface WsItem {
  id: string
  name: string
  is_default: boolean
}

const workspaces = ref<WsItem[]>([])
const currentWsId = ref(localStorage.getItem('agent-hub-ws') || '')
const showCreate = ref(false)
const newName = ref('')
const newDesc = ref('')
const creating = ref(false)

const currentWs = computed(() => workspaces.value.find(w => w.id === currentWsId.value))

function getBaseUrl() {
  return import.meta.env.VITE_API_BASE || '/api'
}

function getHeaders(): Record<string, string> {
  const token = localStorage.getItem('auth_token')
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

async function loadWorkspaces() {
  try {
    const res = await fetch(`${getBaseUrl()}/workspaces/`, { headers: getHeaders() })
    if (res.ok) {
      workspaces.value = await res.json()
      if (!currentWsId.value && workspaces.value.length) {
        const def = workspaces.value.find(w => w.is_default) || workspaces.value[0]
        currentWsId.value = def.id
        localStorage.setItem('agent-hub-ws', def.id)
      }
    }
  } catch { /* silent */ }
}

function switchWorkspace(id: string) {
  if (id === '__create__') {
    showCreate.value = true
    return
  }
  currentWsId.value = id
  localStorage.setItem('agent-hub-ws', id)
  window.dispatchEvent(new CustomEvent('workspace-changed', { detail: { id } }))
}

async function createWs() {
  if (!newName.value.trim()) { ElMessage.warning(t('workspace.nameRequired')); return }
  creating.value = true
  try {
    const res = await fetch(`${getBaseUrl()}/workspaces/`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ name: newName.value.trim(), description: newDesc.value.trim() }),
    })
    if (res.ok) {
      const ws = await res.json()
      ElMessage.success(t('workspace.created'))
      showCreate.value = false
      newName.value = ''
      newDesc.value = ''
      await loadWorkspaces()
      switchWorkspace(ws.id)
    } else {
      const data = await res.json()
      ElMessage.error(data.detail || t('workspace.createFailed'))
    }
  } catch (e: any) {
    ElMessage.error(e.message || t('workspace.createFailed'))
  } finally {
    creating.value = false
  }
}

onMounted(loadWorkspaces)
</script>

<style scoped>
.ws-switcher {
  padding: 10px 12px;
  border-bottom: 1px solid var(--glass-border);
}

.ws-current {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 8px 12px;
  border-radius: 10px;
  transition: all 0.2s;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid transparent;
}

.ws-current:hover {
  background: var(--accent-soft);
  border-color: rgba(129, 140, 248, 0.1);
  color: var(--text-primary);
}

.ws-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ws-arrow {
  font-size: 12px;
  color: var(--text-muted);
  transition: transform 0.2s;
}

.ws-current:hover .ws-arrow {
  color: var(--accent);
}

:deep(.active) {
  background: var(--primary-bg);
  color: var(--accent);
}
</style>
