<template>
  <div class="task-qa-tab">
    <el-card v-if="loading" shadow="never">
      <div class="qa-loading">{{ $t('artifactContract.loading') }}</div>
    </el-card>

    <template v-else>
      <!-- Build / Test / Install Commands Table -->
      <el-card class="qa-section" shadow="never" v-if="hasCommands">
        <template #header>
          <span class="qa-header-icon">⚙️</span>
          {{ $t('qa.testCommands') }}
        </template>

        <el-table :data="commandRows" stripe size="small">
          <el-table-column prop="step" :label="$t('qa.step')" width="100" />
          <el-table-column prop="command" :label="$t('qa.command')" />
          <el-table-column prop="exitCode" :label="$t('qa.exitCode')" width="90" />
          <el-table-column prop="duration" :label="$t('qa.duration')" width="100" />
          <el-table-column prop="status" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.ok" type="success" size="small">✅ {{ $t('qa.pass') }}</el-tag>
              <el-tag v-else type="danger" size="small">❌ {{ $t('qa.fail') }}</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <!-- Build log collapsible -->
        <el-collapse v-if="buildLog" class="qa-collapse">
          <el-collapse-item :title="$t('qa.buildLog')" :name="buildFailed ? 'build' : ''">
            <pre class="qa-log">{{ buildLog }}</pre>
          </el-collapse-item>
        </el-collapse>

        <!-- Test log collapsible -->
        <el-collapse v-if="testLog" class="qa-collapse">
          <el-collapse-item :title="$t('qa.testLog')" :name="testFailed ? 'test' : ''">
            <pre class="qa-log">{{ testLog }}</pre>
          </el-collapse-item>
        </el-collapse>
      </el-card>

      <!-- Browser Screenshot -->
      <el-card class="qa-section" shadow="never" v-if="hasScreenshot">
        <template #header>
          <span class="qa-header-icon">📸</span>
          {{ $t('qa.browserScreenshot') }}
        </template>
        <div class="screenshot-wrapper">
          <img
            :src="screenshotSrc"
            class="qa-screenshot"
            :alt="$t('qa.browserScreenshot')"
            @click="screenshotDialogVisible = true"
          />
        </div>
        <el-dialog
          v-model="screenshotDialogVisible"
          :title="$t('qa.browserScreenshot')"
          width="80%"
          top="5vh"
          destroy-on-close
        >
          <img :src="screenshotSrc" class="qa-screenshot-full" :alt="$t('qa.browserScreenshot')" />
        </el-dialog>
      </el-card>

      <!-- Console Errors -->
      <el-card class="qa-section" shadow="never" v-if="consoleErrors.length > 0">
        <template #header>
          <span class="qa-header-icon">⚠️</span>
          {{ $t('qa.consoleErrors') }} ({{ consoleErrors.length }})
        </template>
        <el-alert
          v-if="consoleErrors.length > 0"
          :title="t('qa.consoleErrorsDetected', { n: consoleErrors.length })"
          type="warning"
          :closable="false"
          show-icon
          class="qa-console-alert"
        />
        <ul class="qa-console-list">
          <li v-for="(err, i) in consoleErrors" :key="i" class="qa-console-error">
            <code>{{ err }}</code>
          </li>
        </ul>
      </el-card>

      <!-- No data -->
      <el-empty v-if="!hasCommands && !hasScreenshot && consoleErrors.length === 0 && !loading" :description="$t('qa.noQaData')" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getAuthToken } from '@/services/api'

const props = defineProps<{
  taskId: string
  shareToken?: string
}>()

const { t } = useI18n()

const loading = ref(true)
const qaData = ref<any>(null)

// Derived from test_report content + metadata
const testReport = ref('')
const buildLog = ref('')
const testLog = ref('')
const screenshotB64 = ref('')
const consoleErrors = ref<string[]>([])

const screenshotDialogVisible = ref(false)

const isBase64Image = (str: string): boolean => {
  if (!str) return false
  return /^[A-Za-z0-9+/=]+$/.test(str) && str.length > 100
}

const screenshotSrc = computed(() => {
  if (!screenshotB64.value) return ''
  return `data:image/png;base64,${screenshotB64.value}`
})

const buildFailed = computed(() => {
  return qaData.value?.build?.ok === false
})

const testFailed = computed(() => {
  return qaData.value?.test?.ok === false
})

interface CommandRow {
  step: string
  command: string
  exitCode: number
  duration: string
  ok: boolean
}

const commandRows = computed<CommandRow[]>(() => {
  const rows: CommandRow[] = []
  for (const step of ['install', 'build', 'test']) {
    const r = qaData.value?.[step]
    if (!r) continue
    rows.push({
      step,
      command: r.command || '',
      exitCode: r.exit_code ?? r.exitCode ?? -1,
      duration: r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : '-',
      ok: r.ok === true,
    })
  }
  return rows
})

const hasCommands = computed(() => commandRows.value.length > 0)
const hasScreenshot = computed(() => !!screenshotB64.value)

async function loadQaData() {
  loading.value = true
  try {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    let artifacts: any[] = []

    if (props.shareToken) {
      const shareRes = await fetch(`${baseUrl}/share/${props.shareToken}`)
      if (!shareRes.ok) return
      const shareData = await shareRes.json()
      artifacts = shareData.artifacts || []
    } else {
      const token = getAuthToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const artRes = await fetch(
        `${baseUrl}/tasks/${props.taskId}/artifacts`,
        { headers },
      )
      if (!artRes.ok) return
      const artData = await artRes.json()
      artifacts = artData.artifacts || []
    }

    // Find test_report for qaResult metadata
    const testReportArt = artifacts.find((a: any) => (a.type_key || a.artifact_type) === 'test_report')
    if (testReportArt?.metadata_json?.qa_result) {
      qaData.value = testReportArt.metadata_json.qa_result
    }

    // Build log
    const buildLogArt = artifacts.find((a: any) => (a.type_key || a.artifact_type) === 'build_log' && a.stage_id === 'testing')
    if (buildLogArt?.content) {
      buildLog.value = buildLogArt.content
    }

    // Test log
    const testLogArt = artifacts.find((a: any) => (a.type_key || a.artifact_type) === 'test_log')
    if (testLogArt?.content) {
      testLog.value = testLogArt.content
    }

    // Screenshot — QA and deploy both use type "screenshot"; scope to testing stage.
    const screenshotArt = artifacts.find((a: any) => {
      const type = a.type_key || a.artifact_type
      if (type !== 'screenshot') return false
      if (a.stage_id === 'testing') return true
      const path = String(a.storage_path || '')
      return path.includes('browser_screenshot')
    })
    if (screenshotArt?.content) {
      screenshotB64.value = screenshotArt.content
    }

    // Console errors
    const consoleArt = artifacts.find((a: any) => (a.type_key || a.artifact_type) === 'console_errors')
    if (consoleArt?.content) {
      try {
        const parsed = JSON.parse(consoleArt.content)
        if (Array.isArray(parsed.console_errors)) {
          consoleErrors.value = parsed.console_errors
        }
      } catch { /* invalid json */ }
    }

    // Fallback: extract from test_report content
    if (!qaData.value && testReportArt?.content) {
      testReport.value = testReportArt.content
    }
  } catch { /* silent */ }
  loading.value = false
}

onMounted(() => loadQaData())
</script>

<style scoped>
.task-qa-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.qa-loading {
  padding: 40px;
  text-align: center;
  color: #909399;
}

.qa-section {
  border-radius: 8px;
}

.qa-header-icon {
  margin-right: 6px;
}

.qa-collapse {
  margin-top: 12px;
}

.qa-log {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  max-height: 400px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}

.screenshot-wrapper {
  cursor: pointer;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #ebeef5;
}

.qa-screenshot {
  width: 100%;
  max-height: 400px;
  object-fit: contain;
  display: block;
  transition: transform 0.2s;
}

.qa-screenshot:hover {
  transform: scale(1.02);
}

.qa-screenshot-full {
  width: 100%;
  display: block;
}

.qa-console-alert {
  margin-bottom: 8px;
}

.qa-console-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.qa-console-error {
  padding: 6px 10px;
  margin-bottom: 4px;
  background: #fef0f0;
  border-radius: 4px;
  font-size: 12px;
  color: #f56c6c;
}

.qa-console-error code {
  word-break: break-all;
}
</style>
