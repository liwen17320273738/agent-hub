<template>
  <div class="digest-view">
    <header class="digest-header">
      <h1>Agent 周报 · 退化检测</h1>
      <p class="digest-sub">
        对比最近窗口与上一窗口的 Eval 通过率、平均得分、span p95 延迟与 stage
        失败率，自动列出"在退化"的 agent。
      </p>
    </header>

    <section class="digest-controls">
      <el-form inline :model="form" size="small">
        <el-form-item label="近 N 天">
          <el-input-number v-model="form.since_days" :min="1" :max="60" />
        </el-form-item>
        <el-form-item label="对比窗 N 天">
          <el-input-number v-model="form.prev_days" :min="1" :max="120" />
        </el-form-item>
        <el-form-item label="通过率回落阈值">
          <el-input-number v-model="form.pass_rate_drop" :step="0.05" :min="0" :max="1" :precision="2" />
        </el-form-item>
        <el-form-item label="得分回落阈值">
          <el-input-number v-model="form.score_drop" :step="0.05" :min="0" :max="1" :precision="2" />
        </el-form-item>
        <el-form-item label="p95 增幅阈值">
          <el-input-number v-model="form.latency_increase" :step="0.1" :min="0" :max="10" :precision="2" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="loadDigest" :loading="loading">
            <el-icon><Refresh /></el-icon> 重新计算
          </el-button>
        </el-form-item>
      </el-form>
    </section>

    <section v-if="digest" class="digest-summary">
      <el-card>
        <div class="summary-row">
          <div>
            <strong>当前窗口：</strong>{{ digest.current_window.since.slice(0, 10) }} ～
            {{ digest.current_window.until.slice(0, 10) }}（{{ digest.current_window.days }} 天）
          </div>
          <div>
            <strong>对比窗口：</strong>{{ digest.previous_window.since.slice(0, 10) }} ～
            {{ digest.previous_window.until.slice(0, 10) }}（{{ digest.previous_window.days }} 天）
          </div>
          <div>
            <strong>退化角色：</strong>
            <el-tag :type="digest.regressions_count ? 'danger' : 'success'">
              {{ digest.regressions_count }}
            </el-tag>
          </div>
        </div>
      </el-card>
    </section>

    <section v-if="digest && digest.regressions.length" class="digest-regressions">
      <h2>⚠ 退化的 agent</h2>
      <el-card v-for="r in digest.regressions" :key="r.role" class="reg-card">
        <div class="reg-head">
          <span class="reg-role">{{ r.role }}</span>
          <el-button size="small" type="primary" @click="openOptimize(r.role)">
            🔧 AI 优化提示词
          </el-button>
        </div>
        <ul>
          <li v-for="(reason, i) in r.reasons" :key="i">{{ reason }}</li>
        </ul>
      </el-card>
    </section>

    <el-dialog v-model="optDialog" :title="`AI 优化提示词 · ${optAgentId}`" width="780px" :close-on-click-modal="false">
      <div v-if="optLoading" class="opt-loading">
        <el-icon class="loading-icon" :size="32"><Loading /></el-icon>
        <p>正在分析最近的 Eval 失败用例并请求 LLM 改写系统提示…</p>
      </div>
      <div v-else-if="!optResult" class="opt-empty">未生成提案</div>
      <div v-else-if="optResult.skipped">
        <el-alert type="success" :closable="false">
          {{ optResult.reason || '当前提示词在最近 eval 中无失败用例，无需修改。' }}
        </el-alert>
      </div>
      <div v-else class="opt-result">
        <h3>改写理由</h3>
        <p class="opt-rationale">{{ optResult.rationale }}</p>
        <h3 v-if="(optResult.diff_summary || []).length">改动要点</h3>
        <ul v-if="(optResult.diff_summary || []).length">
          <li v-for="(d, i) in optResult.diff_summary" :key="i">{{ d }}</li>
        </ul>
        <h3>新提示词预览</h3>
        <el-input v-model="optResult.new_prompt" type="textarea" :rows="14" />
        <details class="opt-old">
          <summary>查看原提示词</summary>
          <pre>{{ optResult.old_prompt }}</pre>
        </details>
      </div>
      <template #footer>
        <el-button @click="optDialog = false">关闭</el-button>
        <el-button v-if="optResult && !optResult.skipped" type="primary" @click="applyOptimization" :loading="optApplying">
          ✅ 应用此提示词
        </el-button>
      </template>
    </el-dialog>

    <section v-if="digest" class="digest-table">
      <h2>各角色指标对比</h2>
      <el-table :data="digest.roles" stripe>
        <el-table-column prop="role" label="角色" min-width="160" />
        <el-table-column label="通过率（当前 / 上期）" min-width="220">
          <template #default="{ row }">
            <span :class="diffClass(row.deltas.eval_pass_rate.delta)">
              {{ pct(row.deltas.eval_pass_rate.current) }}
              <small>← {{ pct(row.deltas.eval_pass_rate.previous) }}</small>
              <em>Δ {{ pctSigned(row.deltas.eval_pass_rate.delta) }}</em>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="平均得分" min-width="200">
          <template #default="{ row }">
            <span :class="diffClass(row.deltas.eval_avg_score.delta)">
              {{ row.deltas.eval_avg_score.current.toFixed(2) }}
              <small>← {{ row.deltas.eval_avg_score.previous.toFixed(2) }}</small>
              <em>Δ {{ signed(row.deltas.eval_avg_score.delta, 2) }}</em>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="p95 延迟 (ms)" min-width="220">
          <template #default="{ row }">
            <span :class="diffClass(-row.deltas.span_p95_ms.delta)">
              {{ row.deltas.span_p95_ms.current.toFixed(0) }}
              <small>← {{ row.deltas.span_p95_ms.previous.toFixed(0) }}</small>
              <em>Δ {{ signed(row.deltas.span_p95_ms.delta, 0) }}</em>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="Stage 失败率" min-width="220">
          <template #default="{ row }">
            <span :class="diffClass(-row.deltas.stage_failure_rate.delta)">
              {{ pct(row.deltas.stage_failure_rate.current) }}
              <small>← {{ pct(row.deltas.stage_failure_rate.previous) }}</small>
              <em>Δ {{ pctSigned(row.deltas.stage_failure_rate.delta) }}</em>
            </span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-else-if="!loading" class="digest-empty">
      <el-empty description="点击「重新计算」开始" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Loading, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getWeeklyDigest } from '@/services/observabilityApi'
import type { WeeklyDigest } from '@/services/observabilityApi'
import { applyPromptRevision, optimizePrompt } from '@/services/agentApi'
import type { PromptRevision } from '@/services/agentApi'

const ROLE_TO_AGENT_ID: Record<string, string> = {
  ceo: 'wayne-ceo',
  cto: 'wayne-cto',
  pm: 'wayne-pm',
  developer: 'wayne-developer',
  qa: 'wayne-qa',
  designer: 'wayne-designer',
  security: 'wayne-security',
  devops: 'wayne-devops',
  acceptance: 'wayne-acceptance',
  data: 'wayne-data',
}

const form = reactive({
  since_days: 7,
  prev_days: 7,
  pass_rate_drop: 0.1,
  score_drop: 0.1,
  latency_increase: 0.5,
})

const digest = ref<WeeklyDigest | null>(null)
const loading = ref(false)

async function loadDigest() {
  loading.value = true
  try {
    digest.value = await getWeeklyDigest({ ...form })
  } catch (e: unknown) {
    ElMessage.error(`加载失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    loading.value = false
  }
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`
}

function pctSigned(v: number) {
  const s = (v * 100).toFixed(1)
  return v >= 0 ? `+${s}%` : `${s}%`
}

function signed(v: number, digits: number) {
  return v >= 0 ? `+${v.toFixed(digits)}` : v.toFixed(digits)
}

function diffClass(delta: number): string {
  if (delta > 0.001) return 'diff-up'
  if (delta < -0.001) return 'diff-down'
  return 'diff-flat'
}

const optDialog = ref(false)
const optLoading = ref(false)
const optApplying = ref(false)
const optAgentId = ref('')
const optResult = ref<PromptRevision | null>(null)

function resolveAgentId(role: string): string {
  return ROLE_TO_AGENT_ID[role.toLowerCase()] || (role.startsWith('wayne-') ? role : `wayne-${role}`)
}

async function openOptimize(role: string) {
  optAgentId.value = resolveAgentId(role)
  optDialog.value = true
  optLoading.value = true
  optResult.value = null
  try {
    const r = await optimizePrompt(optAgentId.value, { score_threshold: 0.7 })
    optResult.value = r
  } catch (e: unknown) {
    ElMessage.error(`生成提案失败：${e instanceof Error ? e.message : String(e)}`)
    optDialog.value = false
  } finally {
    optLoading.value = false
  }
}

async function applyOptimization() {
  if (!optResult.value || !optResult.value.new_prompt) return
  optApplying.value = true
  try {
    await applyPromptRevision(optAgentId.value, {
      new_prompt: optResult.value.new_prompt,
      note: `weekly digest auto-revision (${new Date().toISOString().slice(0, 10)})`,
    })
    ElMessage.success(`已更新 ${optAgentId.value} 系统提示词，原版本已存入 prompt_history（可回滚）`)
    optDialog.value = false
  } catch (e: unknown) {
    ElMessage.error(`应用失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    optApplying.value = false
  }
}

onMounted(loadDigest)
</script>

<style scoped>
.digest-view {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}
.digest-header h1 {
  margin: 0 0 6px;
  font-size: 22px;
}
.digest-sub {
  color: var(--text-muted);
  margin: 0 0 18px;
}
.digest-controls {
  margin-bottom: 16px;
}
.digest-summary,
.digest-regressions,
.digest-table {
  margin-bottom: 20px;
}
.summary-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(160px, 1fr));
  gap: 14px;
  font-size: 13px;
}
.digest-regressions h2,
.digest-table h2 {
  font-size: 16px;
  margin: 16px 0 10px;
}
.reg-card {
  margin-bottom: 10px;
}
.reg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.reg-role {
  font-weight: 600;
}
.opt-loading,
.opt-empty {
  text-align: center;
  padding: 32px 12px;
  color: var(--text-muted);
}
.opt-rationale {
  font-size: 13px;
  line-height: 1.6;
  margin: 0 0 10px;
}
.opt-result h3 {
  margin: 14px 0 6px;
  font-size: 14px;
}
.opt-old {
  margin-top: 12px;
}
.opt-old > summary {
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
}
.opt-old pre {
  margin: 6px 0 0;
  white-space: pre-wrap;
  background: var(--card-bg, #1c1c20);
  padding: 8px 10px;
  border-radius: 4px;
  font-size: 12px;
  max-height: 220px;
  overflow: auto;
}
.reg-card ul {
  margin: 0;
  padding-left: 20px;
  color: #ff7875;
}
.diff-up {
  color: #67c23a;
}
.diff-down {
  color: #ff7875;
}
.diff-flat {
  color: var(--text-secondary);
}
.diff-up small,
.diff-down small,
.diff-flat small {
  color: var(--text-muted);
  margin-left: 4px;
  font-size: 11px;
}
.diff-up em,
.diff-down em,
.diff-flat em {
  display: block;
  font-style: normal;
  font-size: 11px;
  margin-top: 2px;
}
.digest-empty {
  text-align: center;
  padding: 40px;
}
</style>
