<template>
  <div class="obs-page dark">
    <header class="obs-header">
      <div>
        <h1>{{ t('insightsObservability.text_1') }}</h1>
        <p class="obs-sub">{{ t('insightsObservability.text_2') }}</p>
      </div>
      <div class="obs-controls">
        <el-radio-group v-model="windowDays" size="small" @change="reload">
          <el-radio-button :value="3">{{ t('insightsObservability.text_3') }}</el-radio-button>
          <el-radio-button :value="7">{{ t('insightsObservability.text_4') }}</el-radio-button>
          <el-radio-button :value="14">{{ t('insightsObservability.text_5') }}</el-radio-button>
          <el-radio-button :value="30">{{ t('insightsObservability.text_6') }}</el-radio-button>
        </el-radio-group>
        <el-button :loading="loading" size="small" @click="reload">
          <el-icon><Refresh /></el-icon> {{ t('insightsObservability.text_refresh') }}
        </el-button>
      </div>
    </header>

    <el-tabs v-model="tab" class="obs-tabs">
      <!-- Overview -->
      <el-tab-pane :label="t('insightsObservability.label_1')" name="overview">
        <div v-if="snap" class="kpi-grid">
          <KpiCard :label="t('insightsObservability.label_2')" :value="snap.totals.tasks" :suffix="t('insightsObservability.suffix_unit')" />
          <KpiCard :label="t('insightsObservability.label_3')" :value="snap.totals.stages_executed" :suffix="t('insightsObservability.suffix_times')" />
          <KpiCard :label="t('insightsObservability.label_4')" :value="snap.totals.llm_calls" :suffix="t('insightsObservability.suffix_times')" />
          <KpiCard
            :label="t('insightsObservability.label_5')"
            :value="snap.totals.cost_usd.toFixed(4)"
            suffix="USD"
            tone="warning"
          />
          <KpiCard
            :label="t('insightsObservability.label_6')"
            :value="formatTokens(snap.totals.tokens)"
            suffix=""
          />
          <KpiCard
            :label="t('insightsObservability.label_7')"
            :value="`${snap.totals.rejects} / ${snap.totals.fails}`"
            tone="danger"
          />
        </div>

        <div v-if="snap" class="chart-row">
          <ChartCard :title="t('insightsObservability.title_1')" :height="180">
            <SparkBars
              :values="snap.trend.map((d) => d.cost_usd)"
              :labels="snap.trend.map((d) => d.day.slice(5))"
              color="#facc15"
            />
          </ChartCard>
          <ChartCard :title="t('insightsObservability.title_2')" :height="180">
            <SparkBars
              :values="snap.trend.map((d) => d.tokens)"
              :labels="snap.trend.map((d) => d.day.slice(5))"
              color="#60a5fa"
              :format-value="formatTokens"
            />
          </ChartCard>
          <ChartCard :title="t('insightsObservability.title_3')" :height="180">
            <SparkBars
              :values="snap.trend.map((d) => d.llm_calls)"
              :labels="snap.trend.map((d) => d.day.slice(5))"
              color="#34d399"
            />
          </ChartCard>
        </div>

        <div v-if="snap" class="chart-row">
          <ChartCard :title="t('insightsObservability.title_4')" :height="160">
            <div class="status-grid">
              <div
                v-for="(c, st) in snap.task_status"
                :key="st"
                class="status-pill"
                :class="`status-${st}`"
              >
                <span class="status-label">{{ st }}</span>
                <span class="status-count">{{ c }}</span>
              </div>
              <div v-if="!Object.keys(snap.task_status).length" class="empty-mini">
                {{ t('insightsObservability.empty_no_tasks') }}
              </div>
            </div>
          </ChartCard>
          <ChartCard :title="t('insightsObservability.title_5')" :height="160">
            <div class="status-grid">
              <div
                v-for="(c, st) in snap.approvals.by_status"
                :key="st"
                class="status-pill"
              >
                <span class="status-label">{{ st }}</span>
                <span class="status-count">{{ c }}</span>
              </div>
              <div v-if="!snap.approvals.total" class="empty-mini">{{ t('insightsObservability.text_7') }}</div>
            </div>
            <div class="risk-line">
              <span>{{ t('insightsObservability.text_8') }}</span>
              <el-tag
                v-for="(c, risk) in snap.approvals.by_risk"
                :key="risk"
                size="small"
                :type="riskTagType(risk)"
              >
                {{ risk }}: {{ c }}
              </el-tag>
            </div>
          </ChartCard>
          <ChartCard :title="t('insightsObservability.title_6')" :height="160">
            <div class="status-grid">
              <div class="status-pill">
                <span class="status-label">block</span>
                <span class="status-count">{{ snap.budget_events['budget.block'] || 0 }}</span>
              </div>
              <div class="status-pill">
                <span class="status-label">downgrade</span>
                <span class="status-count">{{ snap.budget_events['budget.downgrade'] || 0 }}</span>
              </div>
              <div class="status-pill">
                <span class="status-label">raise</span>
                <span class="status-count">{{ snap.budget_events['budget.raise'] || 0 }}</span>
              </div>
            </div>
          </ChartCard>
        </div>
      </el-tab-pane>

      <!-- Stage heatmap -->
      <el-tab-pane :label="t('insightsObservability.label_8')" name="stages">
        <el-table v-if="snap" :data="snap.stage_heatmap" stripe size="small">
          <el-table-column prop="stage_id" :label="t('insightsObservability.label_9')" width="160">
            <template #default="{ row }">
              <span class="mono">{{ row.stage_id }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="role" :label="t('insightsObservability.col_role')" width="130" />
          <el-table-column prop="samples" :label="t('insightsObservability.col_samples')" width="80" align="right" />
          <el-table-column :label="t('insightsObservability.col_avg_dur')" width="120" align="right">
            <template #default="{ row }">
              {{ formatDuration(row.avg_duration_ms) }}
            </template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_gate_pass')" width="160">
            <template #default="{ row }">
              <RateBar :value="row.pass_rate" />
            </template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_peer_approve')" width="160">
            <template #default="{ row }">
              <RateBar :value="row.approve_rate" tone="approve" />
            </template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_avg_score')" width="120" align="right">
            <template #default="{ row }">
              <span :class="scoreClass(row.avg_score)">{{
                row.avg_score === null ? '—' : row.avg_score.toFixed(2)
              }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_retry')" width="100" align="right">
            <template #default="{ row }">
              <span :class="row.retry_rate > 0.3 ? 'danger' : ''">
                {{ (row.retry_rate * 100).toFixed(0) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_reject_fail')" width="110" align="right">
            <template #default="{ row }">
              <span class="muted">{{ row.rejects }} / {{ row.fails }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty
          v-if="snap && !snap.stage_heatmap.length"
          :description="t('insightsObservability.empty_no_stage_heatmap')"
        />
      </el-tab-pane>

      <!-- Agent leaderboard -->
      <el-tab-pane :label="t('insightsObservability.tab_agents')" name="agents">
        <el-table v-if="snap" :data="snap.agent_leaderboard" stripe size="small">
          <el-table-column prop="role" :label="t('insightsObservability.col_role')" width="180" />
          <el-table-column prop="stages" :label="t('insightsObservability.col_stages')" width="100" align="right" />
          <el-table-column prop="llm_calls" :label="t('insightsObservability.col_llm_calls')" width="100" align="right" />
          <el-table-column :label="t('insightsObservability.col_approve_rate')" width="160">
            <template #default="{ row }">
              <RateBar :value="row.approve_rate" tone="approve" />
            </template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_avg_score')" width="120" align="right">
            <template #default="{ row }">
              <span :class="scoreClass(row.avg_score)">
                {{ row.avg_score === null ? '—' : row.avg_score.toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_cost_usd')" width="140" align="right">
            <template #default="{ row }">
              <span class="warning">${{ row.total_cost_usd.toFixed(4) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_token')" width="120" align="right">
            <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_rej_fail_short')" width="100" align="right">
            <template #default="{ row }">
              <span class="muted">{{ row.rejects }} / {{ row.fails }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="snap && !snap.agent_leaderboard.length" :description="t('insightsObservability.empty_no_agent')" />
      </el-tab-pane>

      <!-- Model comparison -->
      <el-tab-pane :label="t('insightsObservability.tab_models')" name="models">
        <el-table v-if="snap" :data="snap.model_leaderboard" stripe size="small">
          <el-table-column prop="model" :label="t('insightsObservability.col_model')" width="240">
            <template #default="{ row }">
              <span class="mono">{{ row.model }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="tier" :label="t('insightsObservability.col_tier')" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="tierTagType(row.tier)">{{ row.tier || '—' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="calls" :label="t('insightsObservability.col_call_count')" width="100" align="right" />
          <el-table-column :label="t('insightsObservability.col_cost_usd')" width="140" align="right">
            <template #default="{ row }">
              <span class="warning">${{ row.total_cost_usd.toFixed(4) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_token')" width="140" align="right">
            <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_avg_lat')" width="120" align="right">
            <template #default="{ row }">{{ formatDuration(row.avg_duration_ms) }}</template>
          </el-table-column>
          <el-table-column :label="t('insightsObservability.col_fail_rate')" width="100" align="right">
            <template #default="{ row }">
              <span :class="row.failure_rate > 0.05 ? 'danger' : ''">
                {{ (row.failure_rate * 100).toFixed(1) }}%
              </span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="snap && !snap.model_leaderboard.length" :description="t('insightsObservability.empty_no_model')" />
      </el-tab-pane>

      <!-- Failures / rejections -->
      <el-tab-pane :label="t('insightsObservability.tab_failures')" name="failures">
        <div v-if="snap && snap.recent_failures.length" class="failure-list">
          <div v-for="f in snap.recent_failures" :key="`${f.task_id}-${f.stage_id}`" class="failure-card">
            <div class="failure-head">
              <span class="failure-stage mono">{{ f.stage_id }}</span>
              <el-tag size="small" type="danger">{{ f.review_status === 'rejected' ? 'REJECT' : f.status }}</el-tag>
              <span class="failure-role">{{ f.role }}</span>
              <span class="failure-task" :title="f.task_id">→ {{ f.task_title || f.task_id.slice(0, 8) }}</span>
              <span class="failure-time">{{ formatTime(f.completed_at) }}</span>
              <el-tag v-if="f.retry_count" size="small" type="warning">retry x{{ f.retry_count }}</el-tag>
            </div>
            <div v-if="f.reviewer_feedback" class="failure-body">
              <span class="failure-label">{{ t('insightsObservability.lbl_reviewer_fb') }}</span>{{ f.reviewer_feedback }}
            </div>
            <div v-if="f.last_error" class="failure-body danger">
              <span class="failure-label">error: </span>{{ f.last_error }}
            </div>
          </div>
        </div>
        <el-empty v-else :description="t('insightsObservability.empty_no_fail')" />
      </el-tab-pane>

      <!-- Learning loop -->
      <el-tab-pane name="learning">
        <template #label>
          <span>{{ t('insightsObservability.tab_learn') }}</span>
          <el-badge v-if="undistilledTotal" :value="undistilledTotal" class="tab-badge" />
        </template>

        <div v-if="learning" class="learning-grid">
          <el-table :data="learning.per_stage" size="small" stripe>
            <el-table-column prop="stage_id" :label="t('insightsObservability.label_9')" width="160">
              <template #default="{ row }">
                <span class="mono">{{ row.stage_id }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('insightsObservability.col_signals')" width="100" align="right">
              <template #default="{ row }">{{ row.signals_total }}</template>
            </el-table-column>
            <el-table-column :label="t('insightsObservability.col_undistilled')" width="100" align="right">
              <template #default="{ row }">
                <el-tag v-if="row.signals_undistilled" size="small" type="warning">
                  {{ row.signals_undistilled }}
                </el-tag>
                <span v-else class="muted">0</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('insightsObservability.col_sig_types')" min-width="220">
              <template #default="{ row }">
                <el-tag
                  v-for="(c, st) in row.by_type"
                  :key="st"
                  size="small"
                  :type="signalTagType(st as string)"
                  style="margin-right: 4px"
                >
                  {{ st }}: {{ c }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('insightsObservability.col_active_patch')" min-width="220">
              <template #default="{ row }">
                <div v-if="row.active_override">
                  <span class="mono">v{{ row.active_override.version }}</span>
                  · {{ row.active_override.title }}
                  <div class="impact-mini">
                    {{ t('insightsObservability.learn_patch_impact', {
                      uses: row.active_override.uses,
                      approves: row.active_override.approves,
                      rejects: row.active_override.rejects,
                    }) }}
                  </div>
                </div>
                <span v-else class="muted">{{ t('insightsObservability.none_short') }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('insightsObservability.col_prop_archive')" width="120" align="right">
              <template #default="{ row }">
                <span class="muted">{{ row.proposed_overrides }} / {{ row.archived_overrides }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('insightsObservability.col_op')" width="220" align="center">
              <template #default="{ row }">
                <el-button
                  :loading="distilling === row.stage_id"
                  size="small"
                  type="primary"
                  plain
                  :disabled="!row.signals_undistilled"
                  @click="distill(row.stage_id, false)"
                >
                  {{ t('insightsObservability.btn_distill_propose') }}
                </el-button>
                <el-button
                  size="small"
                  link
                  type="primary"
                  @click="openStage(row.stage_id)"
                >
                  {{ t('insightsObservability.btnDetail') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-empty
            v-if="!learning.per_stage.length"
            :description="t('insightsObservability.learn_empty')"
          />
        </div>

        <el-drawer
          v-model="drawerOpen"
          :title="t('insightsObservability.drawer_title_stage', { id: selectedStage })"
          size="640px"
          direction="rtl"
        >
          <div v-if="drawerLoading" class="drawer-loading">{{ t('insightsObservability.loading_short') }}</div>
          <div v-else>
            <h3 class="drawer-h">{{ t('insightsObservability.patch_ver') }}</h3>
            <div v-if="!stageOverrides.length" class="muted">{{ t('insightsObservability.none') }}</div>
            <div v-for="ov in stageOverrides" :key="ov.id" class="override-card">
              <div class="override-head">
                <el-tag :type="overrideTagType(ov.status)" size="small">{{ ov.status }}</el-tag>
                <span class="mono">v{{ ov.version }}</span>
                <span class="override-title">{{ ov.title }}</span>
              </div>
              <div v-if="ov.rationale" class="override-rationale">{{ ov.rationale }}</div>
              <pre class="override-body">{{ ov.addendum }}</pre>
              <div class="override-foot">
                <span class="muted">
                  {{ t('insightsObservability.learn_distill_meta', {
                    n: ov.distilled_from_n,
                    u: ov.impact.uses,
                    a: ov.impact.approves,
                    r: ov.impact.rejects,
                  }) }}
                  <template v-if="ov.impact.approve_rate !== null">
                    {{ t('insightsObservability.learn_approve_rate_suffix', { pct: (ov.impact.approve_rate * 100).toFixed(0) }) }}
                  </template>
                </span>
                <span class="actions">
                  <el-button
                    v-if="ov.status === 'proposed' || ov.status === 'disabled' || ov.status === 'archived'"
                    size="small"
                    type="success"
                    plain
                    @click="act(ov.id, 'activate')"
                  >{{ t('insightsObservability.btnEnable') }}</el-button>
                  <el-button
                    v-if="ov.status === 'active'"
                    size="small"
                    type="warning"
                    plain
                    @click="act(ov.id, 'archive')"
                  >{{ t('insightsObservability.btnArchive') }}</el-button>
                  <el-button
                    v-if="ov.status === 'proposed'"
                    size="small"
                    type="primary"
                    plain
                    @click="act(ov.id, 'shadow')"
                  >{{ t('insightsObservability.ab_shadow') }}</el-button>
                  <el-button
                    v-if="ov.status === 'proposed'"
                    size="small"
                    type="info"
                    plain
                    @click="act(ov.id, 'disable')"
                  >{{ t('insightsObservability.btnDisable') }}</el-button>
                </span>
              </div>
            </div>

            <h3 class="drawer-h" style="margin-top: 24px">{{ t('insightsObservability.recent_signals') }}</h3>
            <div v-if="!stageSignals.length" class="muted">{{ t('insightsObservability.none') }}</div>
            <div v-for="sig in stageSignals" :key="sig.id" class="signal-card">
              <div class="signal-head">
                <el-tag :type="signalTagType(sig.signal_type)" size="small">
                  {{ sig.signal_type }}
                </el-tag>
                <span v-if="sig.distilled" class="muted small">{{ t('insightsObservability.tag_distilled') }}</span>
                <span v-else class="warning small">{{ t('insightsObservability.tag_undistilled') }}</span>
                <span class="muted small">{{ formatTime(sig.created_at) }}</span>
              </div>
              <div v-if="sig.reviewer_feedback" class="signal-body">
                <span class="signal-label">reviewer：</span>{{ sig.reviewer_feedback }}
              </div>
              <div v-if="sig.error_excerpt" class="signal-body danger">
                <span class="signal-label">error：</span>{{ sig.error_excerpt }}
              </div>
            </div>
          </div>
        </el-drawer>
      </el-tab-pane>

      <!-- Tool sandbox -->
      <el-tab-pane name="sandbox">
        <template #label>
          <span>{{ t('insightsObservability.tab_sandbox') }}</span>
          <el-badge v-if="recentDenialCount" :value="recentDenialCount" class="tab-badge" type="danger" />
        </template>

        <div v-if="sandboxPolicy" class="sandbox-section">
          <div class="sandbox-legend">
            <span><span class="dot dot-allow" /> {{ t('insightsObservability.legend_allow') }}</span>
            <span><span class="dot dot-deny" /> {{ t('insightsObservability.legend_deny') }}</span>
            <span><span class="dot dot-common" /> {{ t('insightsObservability.legend_common') }}</span>
            <span><span class="dot dot-override" /> {{ t('insightsObservability.legend_ops_override') }}</span>
            <span class="muted">{{
              t('insightsObservability.sandbox_counts', {
                tools: sandboxPolicy.all_tools.length,
                roles: Object.keys(sandboxPolicy.roles).length,
              })
            }}</span>
            <span class="muted">{{ t('insightsObservability.sandbox_admin_hint') }}</span>
          </div>

          <div class="matrix-wrap">
            <table class="sandbox-matrix">
              <thead>
                <tr>
                  <th class="corner">role \ tool</th>
                  <th
                    v-for="toolName in sortedTools"
                    :key="toolName"
                    class="tool-col"
                    :class="{ 'tool-common': sandboxPolicy.common_tools.includes(toolName) }"
                    :title="toolName"
                  >
                    <div class="tool-name">{{ toolName }}</div>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(summary, role) in sandboxPolicy.roles" :key="role">
                  <td class="role-col mono">{{ role }}</td>
                  <td
                    v-for="toolName in sortedTools"
                    :key="toolName"
                    class="cell clickable"
                    :class="cellClass(role as string, toolName)"
                    :title="`${role} · ${toolName}: ${cellTitle(role as string, toolName)}`"
                    @click="openCellEditor(role as string, toolName)"
                  >
                    <span v-if="cellAllowed(role as string, toolName)">●</span>
                    <span v-else>·</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <el-dialog
            v-model="cellEditor.open"
            :title="t('insightsObservability.dialog_sandbox', { role: cellEditor.role, tool: cellEditor.tool })"
            width="480px"
            destroy-on-close
          >
            <div class="cell-edit-body">
              <div class="muted">
                {{ t('insightsObservability.code_default') }}:
                <strong>{{ cellEditor.baselineAllow ? t('insightsObservability.word_allow') : t('insightsObservability.word_deny') }}</strong>
                <span v-if="cellEditor.hasOverride">
                  · {{ t('insightsObservability.current_override') }}:
                  <strong>{{ cellEditor.overrideAllow ? t('insightsObservability.word_allow') : t('insightsObservability.word_deny') }}</strong>
                </span>
              </div>
              <el-radio-group v-model="cellEditor.choice" class="cell-edit-radio">
                <el-radio value="allow">{{ t('insightsObservability.force_allow') }}</el-radio>
                <el-radio value="deny">{{ t('insightsObservability.force_deny') }}</el-radio>
                <el-radio value="default">{{ t('insightsObservability.restore_baseline') }}</el-radio>
              </el-radio-group>
              <el-input
                v-if="cellEditor.choice !== 'default'"
                v-model="cellEditor.note"
                type="textarea"
                :rows="2"
                :placeholder="t('insightsObservability.note_ph')"
              />
            </div>
            <template #footer>
              <el-button @click="cellEditor.open = false">{{ t('common.cancel') }}</el-button>
              <el-button type="primary" :loading="cellEditor.saving" @click="saveCellEdit">
                {{ t('common.save') }}
              </el-button>
            </template>
          </el-dialog>

          <h3 class="drawer-h" style="margin-top: 28px">{{ t('insightsObservability.recent_deny') }}</h3>
          <div v-if="!sandboxDenials.length" class="muted">{{ t('insightsObservability.sandbox_no_deny') }}</div>
          <div v-for="d in sandboxDenials" :key="d.id" class="denial-card">
            <div class="denial-head">
              <el-tag size="small" type="danger">DENIED</el-tag>
              <span class="mono">{{ d.tool }}</span>
              <span class="muted">by {{ d.actor || '?' }}</span>
              <span v-if="d.task_id" class="muted small" :title="d.task_id">
                · task {{ d.task_id.slice(0, 8) }}
              </span>
              <span v-if="d.stage_id" class="muted small">· stage {{ d.stage_id }}</span>
              <span class="muted small denial-time">{{ formatTime(d.created_at) }}</span>
            </div>
            <div v-if="d.details" class="denial-body">{{ d.details }}</div>
          </div>
        </div>
        <el-empty v-else :description="t('insightsObservability.loading_sandbox')" />
      </el-tab-pane>

      <!-- Scheduler -->
      <el-tab-pane name="scheduler">
        <template #label>
          <span>{{ t('insightsObservability.tab_sched') }}</span>
          <el-badge
            v-if="scheduler && (scheduler.runningCount + scheduler.queueDepth) > 0"
            :value="scheduler.runningCount + scheduler.queueDepth"
            class="tab-badge"
            type="primary"
          />
        </template>

        <div v-if="scheduler" class="kpi-grid">
          <KpiCard :label="t('insightsObservability.sched_max_conc')" :value="scheduler.maxConcurrent" :suffix="t('insightsObservability.suffix_parallel')" />
          <KpiCard :label="t('insightsObservability.sched_running')" :value="scheduler.runningCount" :suffix="t('insightsObservability.suffix_unit')" tone="warning" />
          <KpiCard :label="t('insightsObservability.sched_queued')" :value="scheduler.queueDepth" :suffix="t('insightsObservability.suffix_unit')" />
          <KpiCard :label="t('insightsObservability.sched_submitted')" :value="scheduler.lifetime.submitted" />
          <KpiCard :label="t('insightsObservability.sched_finished')" :value="scheduler.lifetime.finished" />
          <KpiCard
            :label="t('insightsObservability.sched_failed')"
            :value="scheduler.lifetime.failed"
            :tone="scheduler.lifetime.failed > 0 ? 'danger' : ''"
          />
        </div>

        <div v-if="scheduler" class="chart-row">
          <ChartCard :title="t('insightsObservability.sched_chart_run')" :height="220">
            <div v-if="!scheduler.running.length" class="empty-mini">{{ t('insightsObservability.sched_idle') }}</div>
            <div v-else class="sched-list">
              <div v-for="r in scheduler.running" :key="r.submission_id" class="sched-row running">
                <el-tag size="small" type="warning">running</el-tag>
                <span class="mono">{{ r.label }}</span>
                <span class="muted small">since {{ formatTime(r.started_at) }}</span>
              </div>
            </div>
          </ChartCard>
          <ChartCard :title="t('insightsObservability.sched_queue_fifo')" :height="220">
            <div v-if="!scheduler.queued.length" class="empty-mini">{{ t('insightsObservability.sched_backlog_free') }}</div>
            <div v-else class="sched-list">
              <div
                v-for="(r, idx) in scheduler.queued"
                :key="r.submission_id"
                class="sched-row queued"
              >
                <el-tag size="small">#{{ idx + 1 }}</el-tag>
                <span class="mono">{{ r.label }}</span>
                <span class="muted small">queued {{ formatTime(r.queued_at) }}</span>
              </div>
            </div>
          </ChartCard>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  fetchDashboard,
  fetchLearningSummary,
  fetchOverrides,
  fetchSignals,
  distillStage,
  activateOverride,
  archiveOverride,
  disableOverride,
  shadowOverride,
  fetchSandboxPolicy,
  fetchSandboxDenials,
  fetchSchedulerStatus,
  setSandboxRule,
  deleteSandboxRule,
  type DashboardSnapshot,
  type LearningSummary,
  type PromptOverride,
  type LearningSignal as LSignal,
  type SandboxPolicy,
  type SandboxDenial,
  type SchedulerStatus,
} from '@/services/insightsApi'
import { useI18n } from 'vue-i18n'
import { appLocaleToBcp47 } from '@/i18n'

const { t, locale } = useI18n()

// ─── inline mini components ───
const KpiCard = (props: { label: string; value: string | number; suffix?: string; tone?: string }) =>
  h('div', { class: ['kpi-card', props.tone ? `tone-${props.tone}` : ''] }, [
    h('div', { class: 'kpi-label' }, props.label),
    h('div', { class: 'kpi-value' }, [
      String(props.value),
      props.suffix ? h('span', { class: 'kpi-suffix' }, props.suffix) : null,
    ]),
  ])

const ChartCard = (
  props: { title: string; height: number },
  { slots }: { slots: { default?: () => unknown } },
) =>
  h('div', { class: 'chart-card', style: { minHeight: `${props.height + 60}px` } }, [
    h('div', { class: 'chart-title' }, props.title),
    h('div', { class: 'chart-body', style: { height: `${props.height}px` } }, slots.default?.()),
  ])

const SparkBars = (props: {
  values: number[]
  labels: string[]
  color: string
  formatValue?: (v: number) => string
}) => {
  if (!props.values.length) {
    return h('div', { class: 'empty-mini' }, t('insightsObservability.no_chart_data'))
  }
  const max = Math.max(1, ...props.values)
  const W = 600
  const H = 140
  const barW = W / props.values.length
  const barGap = Math.min(4, barW * 0.15)
  const bars = props.values.map((v, i) => {
    const h_ = (v / max) * (H - 24)
    return h('g', { key: i }, [
      h('rect', {
        x: i * barW + barGap / 2,
        y: H - h_ - 18,
        width: barW - barGap,
        height: h_,
        fill: props.color,
        opacity: 0.85,
        rx: 2,
      }),
      h(
        'title',
        {},
        `${props.labels[i]}: ${props.formatValue ? props.formatValue(v) : v}`,
      ),
    ])
  })
  const labels = props.labels.map((l, i) =>
    h(
      'text',
      {
        x: i * barW + barW / 2,
        y: H - 4,
        'text-anchor': 'middle',
        'font-size': '10',
        fill: '#94a3b8',
      },
      l,
    ),
  )
  const maxLabel = props.formatValue ? props.formatValue(max) : String(max)
  return h(
    'svg',
    {
      viewBox: `0 0 ${W} ${H}`,
      preserveAspectRatio: 'none',
      style: { width: '100%', height: '100%' },
    },
    [
      h(
        'text',
        { x: 6, y: 12, 'font-size': '10', fill: '#64748b' },
        `peak ${maxLabel}`,
      ),
      ...bars,
      ...labels,
    ],
  )
}

const RateBar = (props: { value: number | null; tone?: string }) => {
  if (props.value === null) {
    return h('span', { class: 'muted' }, '—')
  }
  const pct = Math.round(props.value * 100)
  const danger = props.value < 0.6
  const warn = props.value < 0.85
  const color = danger
    ? '#f87171'
    : warn
    ? '#facc15'
    : props.tone === 'approve'
    ? '#34d399'
    : '#60a5fa'
  return h('div', { class: 'rate-bar' }, [
    h('div', { class: 'rate-bar-track' }, [
      h('div', {
        class: 'rate-bar-fill',
        style: { width: `${pct}%`, background: color },
      }),
    ]),
    h('span', { class: 'rate-bar-text' }, `${pct}%`),
  ])
}

// ─── state ───
const tab = ref<string>('overview')
const windowDays = ref(14)
const loading = ref(false)
const snap = ref<DashboardSnapshot | null>(null)
const learning = ref<LearningSummary | null>(null)

const distilling = ref<string>('')
const drawerOpen = ref(false)
const drawerLoading = ref(false)
const selectedStage = ref<string>('')
const stageOverrides = ref<PromptOverride[]>([])
const stageSignals = ref<LSignal[]>([])

const undistilledTotal = computed(() =>
  learning.value?.per_stage.reduce((acc, s) => acc + s.signals_undistilled, 0) ?? 0,
)

// ─── sandbox + scheduler state ───
const sandboxPolicy = ref<SandboxPolicy | null>(null)
const sandboxDenials = ref<SandboxDenial[]>([])
const scheduler = ref<SchedulerStatus | null>(null)
let schedulerTimer: ReturnType<typeof setInterval> | null = null

const sortedTools = computed<string[]>(() => {
  if (!sandboxPolicy.value) return []
  // Common tools first (cheap to scan), then the rest alphabetically.
  const common = new Set(sandboxPolicy.value.common_tools)
  const rest = sandboxPolicy.value.all_tools.filter((t) => !common.has(t)).sort()
  return [...sandboxPolicy.value.common_tools, ...rest]
})

const recentDenialCount = computed(() => sandboxDenials.value.length)

function cellAllowed(role: string, tool: string): boolean {
  const summary = sandboxPolicy.value?.roles[role]
  if (!summary) return true
  if (sandboxPolicy.value?.common_tools.includes(tool)) return true
  return summary.allowed.includes(tool)
}
function cellHasOverride(role: string, tool: string): 'allow' | 'deny' | null {
  const summary = sandboxPolicy.value?.roles[role]
  const ov = summary?.overrides
  if (!ov) return null
  if (ov.allow.includes(tool)) return 'allow'
  if (ov.deny.includes(tool)) return 'deny'
  return null
}
function cellClass(role: string, tool: string): string {
  const isCommon = sandboxPolicy.value?.common_tools.includes(tool)
  if (isCommon) return 'cell-common'
  const base = cellAllowed(role, tool) ? 'cell-allow' : 'cell-deny'
  const ov = cellHasOverride(role, tool)
  return ov ? `${base} cell-override` : base
}
function cellTitle(role: string, tool: string): string {
  if (sandboxPolicy.value?.common_tools.includes(tool)) return t('insightsObservability.cellTitleCommon')
  const allowed = cellAllowed(role, tool)
    ? t('insightsObservability.word_allow')
    : t('insightsObservability.word_deny')
  const ov = cellHasOverride(role, tool)
  return ov
    ? t('insightsObservability.cellTitleOverride', {
        base: allowed,
        ov: ov === 'allow' ? t('insightsObservability.word_allow') : t('insightsObservability.word_deny'),
      })
    : allowed
}

// ─── Per-cell editor state ─────────────────────────────────────────────────
// One dialog instance, opened by clicking a cell. ``baselineAllow``
// captures what the in-code whitelist would say so the user can see
// what they'd be diverging from before clicking save.
const cellEditor = reactive({
  open: false,
  saving: false,
  role: '',
  tool: '',
  baselineAllow: false,
  hasOverride: false,
  overrideAllow: false,
  choice: 'default' as 'allow' | 'deny' | 'default',
  note: '',
})

function openCellEditor(role: string, tool: string) {
  if (sandboxPolicy.value?.common_tools.includes(tool)) {
    ElMessage.info(t('insightsObservability.elMessage_1'))
    return
  }
  const summary = sandboxPolicy.value?.roles[role]
  const ov = cellHasOverride(role, tool)
  // Compute the BASELINE (in-code) allow by stripping the override
  // effect from the summary: if there's an override, baseline is the
  // opposite of the current effective state; otherwise baseline = effective.
  const effective = cellAllowed(role, tool)
  const baseline = ov ? !effective : effective
  cellEditor.role = role
  cellEditor.tool = tool
  cellEditor.baselineAllow = baseline
  cellEditor.hasOverride = !!ov
  cellEditor.overrideAllow = ov === 'allow'
  cellEditor.choice = ov ? (ov === 'allow' ? 'allow' : 'deny') : 'default'
  cellEditor.note = ''
  cellEditor.open = true
  void summary // unused — kept for future role-level metadata
}

async function saveCellEdit() {
  cellEditor.saving = true
  try {
    if (cellEditor.choice === 'default') {
      // Only call DELETE if there's actually an override to remove,
      // otherwise the API returns 404.
      if (cellEditor.hasOverride) {
        await deleteSandboxRule(cellEditor.role, cellEditor.tool)
      }
    } else {
      await setSandboxRule(
        cellEditor.role,
        cellEditor.tool,
        cellEditor.choice === 'allow',
        cellEditor.note || undefined,
      )
    }
    ElMessage.success(t('insightsObservability.elMessage_2'))
    cellEditor.open = false
    // Refresh the policy snapshot so the matrix reflects the change.
    const p = await fetchSandboxPolicy().catch(() => null)
    if (p) sandboxPolicy.value = p
  } catch (err: any) {
    ElMessage.error(err?.message || t('insightsObservability.elMessage_saveFail'))
  } finally {
    cellEditor.saving = false
  }
}

async function reload() {
  loading.value = true
  try {
    const [d, l, p, dn, s] = await Promise.all([
      fetchDashboard(windowDays.value),
      fetchLearningSummary(),
      fetchSandboxPolicy().catch(() => null),
      fetchSandboxDenials({ limit: 100 }).catch(() => ({ denials: [] })),
      fetchSchedulerStatus().catch(() => null),
    ])
    snap.value = d
    learning.value = l
    if (p) sandboxPolicy.value = p
    sandboxDenials.value = dn.denials
    if (s) scheduler.value = s
  } catch (err: any) {
    ElMessage.error(`${t('insightsObservability.elMessage_loadFail')}: ${err?.message || err}`)
  } finally {
    loading.value = false
  }
}

async function distill(stageId: string, autoApply: boolean) {
  distilling.value = stageId
  try {
    const res = await distillStage(stageId, autoApply)
    ElMessage.success(
      t('insightsObservability.elMessage_proposalOk', { title: res.override.title, ver: res.override.version }),
    )
    await reload()
    if (drawerOpen.value && selectedStage.value === stageId) {
      await openStage(stageId)
    }
  } catch (err: any) {
    ElMessage.warning(err?.message || t('insightsObservability.elMessage_distillFail'))
  } finally {
    distilling.value = ''
  }
}

async function openStage(stageId: string) {
  selectedStage.value = stageId
  drawerOpen.value = true
  drawerLoading.value = true
  try {
    const [ovs, sigs] = await Promise.all([
      fetchOverrides({ stageId }),
      fetchSignals({ stageId, limit: 30 }),
    ])
    stageOverrides.value = ovs.overrides
    stageSignals.value = sigs.signals
  } catch (err: any) {
    ElMessage.error(`${t('insightsObservability.elMessage_stageLoadFail')}: ${err?.message || err}`)
  } finally {
    drawerLoading.value = false
  }
}

async function act(id: string, action: 'activate' | 'archive' | 'disable' | 'shadow') {
  try {
    if (action === 'activate') await activateOverride(id)
    else if (action === 'archive') await archiveOverride(id)
    else if (action === 'shadow') await shadowOverride(id)
    else await disableOverride(id)
    ElMessage.success(action === 'shadow' ? t('insightsObservability.elMessage_shadowOk') : t('insightsObservability.elMessage_updated'))
    await openStage(selectedStage.value)
    await reload()
  } catch (err: any) {
    ElMessage.error(err?.message || t('insightsObservability.elMessage_actFail'))
  }
}

// ─── helpers ───
function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}
function formatDuration(ms: number): string {
  if (!ms) return '—'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60_000).toFixed(1)}m`
}
function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocaleToBcp47(locale.value), { hour12: false })
}
function scoreClass(s: number | null) {
  if (s === null) return 'muted'
  if (s >= 0.85) return 'success'
  if (s >= 0.6) return 'warning'
  return 'danger'
}
function riskTagType(risk: string) {
  return risk === 'critical' ? 'danger' : risk === 'high' ? 'warning' : 'info'
}
function tierTagType(tier: string) {
  if (tier === 'PLANNING') return 'danger'
  if (tier === 'EXECUTION') return 'warning'
  if (tier === 'downgraded') return 'info'
  return ''
}
function signalTagType(t: string) {
  if (t === 'REJECT') return 'danger'
  if (t === 'GATE_FAIL') return 'danger'
  if (t === 'RETRY') return 'warning'
  if (t === 'APPROVE_AFTER_RETRY') return 'success'
  if (t === 'BLOCKED') return 'info'
  return ''
}
function overrideTagType(s: string) {
  if (s === 'active') return 'success'
  if (s === 'shadow') return 'primary'
  if (s === 'proposed') return 'warning'
  if (s === 'disabled') return 'info'
  return ''
}

onMounted(() => {
  reload()
  // The scheduler view needs a faster pulse than the rest of the page —
  // poll just that endpoint every 5s while the page is mounted. Cheap
  // (in-memory snapshot, no DB).
  schedulerTimer = setInterval(async () => {
    try { scheduler.value = await fetchSchedulerStatus() } catch {}
  }, 5000)
})
onUnmounted(() => {
  if (schedulerTimer) clearInterval(schedulerTimer)
})
</script>

<style scoped>
.obs-page {
  padding: 20px 28px;
  color: var(--text-primary, #e2e8f0);
  min-height: 100vh;
}
.obs-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 16px;
}
.obs-header h1 {
  font-size: 22px;
  margin: 0;
  font-weight: 700;
}
.obs-sub {
  margin: 4px 0 0;
  color: var(--text-muted, #94a3b8);
  font-size: 13px;
}
.obs-controls {
  display: flex;
  gap: 8px;
  align-items: center;
}
.obs-tabs {
  --el-tabs-header-height: 38px;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.kpi-card {
  background: var(--bg-secondary, #1e293b);
  border: 1px solid var(--border-color, #334155);
  border-radius: 10px;
  padding: 14px 16px;
}
.kpi-label {
  color: var(--text-muted, #94a3b8);
  font-size: 12px;
  margin-bottom: 6px;
}
.kpi-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary, #e2e8f0);
}
.kpi-suffix {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted, #94a3b8);
  margin-left: 4px;
}
.tone-warning .kpi-value {
  color: #facc15;
}
.tone-danger .kpi-value {
  color: #f87171;
}

.chart-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.chart-card {
  background: var(--bg-secondary, #1e293b);
  border: 1px solid var(--border-color, #334155);
  border-radius: 10px;
  padding: 12px 14px 10px;
}
.chart-title {
  color: var(--text-muted, #94a3b8);
  font-size: 12px;
  margin-bottom: 8px;
  font-weight: 500;
}
.chart-body {
  width: 100%;
}

.status-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.status-pill {
  background: var(--bg-tertiary, #0f172a);
  border-radius: 6px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  min-width: 60px;
}
.status-label {
  font-size: 10px;
  color: var(--text-muted, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.status-count {
  font-size: 18px;
  font-weight: 700;
}
.status-pill.status-done .status-count {
  color: #34d399;
}
.status-pill.status-active .status-count {
  color: #60a5fa;
}
.status-pill.status-failed .status-count {
  color: #f87171;
}
.status-pill.status-paused .status-count {
  color: #facc15;
}
.empty-mini {
  color: var(--text-muted, #94a3b8);
  font-size: 12px;
  padding: 8px;
}
.risk-line {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-top: 12px;
  font-size: 12px;
  color: var(--text-muted, #94a3b8);
}

.rate-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}
.rate-bar-track {
  flex: 1;
  height: 8px;
  background: var(--bg-tertiary, #0f172a);
  border-radius: 4px;
  overflow: hidden;
}
.rate-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}
.rate-bar-text {
  font-size: 11px;
  color: var(--text-muted, #94a3b8);
  min-width: 36px;
  text-align: right;
}

.failure-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.failure-card {
  background: var(--bg-secondary, #1e293b);
  border-left: 3px solid #f87171;
  border-radius: 6px;
  padding: 10px 14px;
}
.failure-head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  font-size: 12px;
}
.failure-stage {
  font-weight: 600;
}
.failure-role {
  color: #94a3b8;
}
.failure-task {
  color: #60a5fa;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.failure-time {
  color: #64748b;
  font-size: 11px;
}
.failure-body {
  margin-top: 6px;
  font-size: 12px;
  color: #cbd5e1;
  white-space: pre-wrap;
  word-break: break-word;
}
.failure-body.danger {
  color: #fca5a5;
}
.failure-label {
  color: #94a3b8;
  font-weight: 600;
  margin-right: 4px;
}

.tab-badge {
  margin-left: 6px;
}

.learning-grid {
  margin-top: 4px;
}
.impact-mini {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}

.drawer-loading {
  padding: 20px;
  color: #94a3b8;
}
.drawer-h {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 10px;
  color: #e2e8f0;
}
.override-card {
  background: var(--bg-tertiary, #0f172a);
  border: 1px solid var(--border-color, #334155);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 10px;
}
.override-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.override-title {
  font-weight: 600;
  font-size: 13px;
}
.override-rationale {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 6px;
}
.override-body {
  background: #020617;
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  color: #cbd5e1;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
  margin: 0;
}
.override-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  flex-wrap: wrap;
  gap: 8px;
}
.actions {
  display: flex;
  gap: 6px;
}

.signal-card {
  background: var(--bg-tertiary, #0f172a);
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 6px;
  border-left: 2px solid #475569;
}
.signal-head {
  display: flex;
  gap: 8px;
  align-items: center;
}
.signal-body {
  margin-top: 4px;
  font-size: 12px;
  color: #cbd5e1;
  white-space: pre-wrap;
}
.signal-body.danger {
  color: #fca5a5;
}
.signal-label {
  color: #94a3b8;
  margin-right: 4px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}
.muted {
  color: #94a3b8;
}
.muted.small,
.warning.small {
  font-size: 11px;
}
.warning {
  color: #facc15;
}
.danger {
  color: #f87171;
}
.success {
  color: #34d399;
}

/* ─── Sandbox matrix ─── */
.sandbox-section {
  padding-top: 4px;
}
.sandbox-legend {
  display: flex;
  gap: 18px;
  align-items: center;
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 12px;
}
.sandbox-legend .dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.dot-allow {
  background: #34d399;
}
.dot-deny {
  background: #475569;
}
.dot-common {
  background: #60a5fa;
}
.matrix-wrap {
  overflow-x: auto;
  border: 1px solid #334155;
  border-radius: 8px;
  background: #0f172a;
}
.sandbox-matrix {
  border-collapse: separate;
  border-spacing: 0;
  font-size: 11px;
  color: #cbd5e1;
}
.sandbox-matrix th,
.sandbox-matrix td {
  padding: 4px 6px;
  border-bottom: 1px solid #1e293b;
  border-right: 1px solid #1e293b;
}
.sandbox-matrix .corner {
  position: sticky;
  left: 0;
  background: #1e293b;
  text-align: left;
  font-weight: 600;
  z-index: 2;
  min-width: 140px;
}
.sandbox-matrix thead th {
  position: sticky;
  top: 0;
  background: #1e293b;
  z-index: 1;
}
.sandbox-matrix .tool-col {
  min-width: 18px;
  text-align: center;
  white-space: nowrap;
}
.sandbox-matrix .tool-col .tool-name {
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-weight: 500;
  font-size: 10px;
  color: #cbd5e1;
  padding: 2px 0;
}
.sandbox-matrix .tool-col.tool-common .tool-name {
  color: #60a5fa;
}
.sandbox-matrix .role-col {
  position: sticky;
  left: 0;
  background: #0f172a;
  font-weight: 600;
  color: #e2e8f0;
}
.sandbox-matrix .cell {
  text-align: center;
  width: 22px;
  height: 22px;
  font-size: 14px;
  cursor: default;
}
.sandbox-matrix .cell.clickable {
  cursor: pointer;
  transition: outline-color 0.15s;
}
.sandbox-matrix .cell.clickable:hover {
  outline: 2px solid rgba(96, 165, 250, 0.7);
  outline-offset: -2px;
}
.cell-allow {
  background: rgba(52, 211, 153, 0.18);
  color: #34d399;
}
.cell-deny {
  background: transparent;
  color: #475569;
}
.cell-common {
  background: rgba(96, 165, 250, 0.16);
  color: #60a5fa;
}
/* When an admin override is in effect, draw a small purple ring around
   the cell so it's distinguishable from a baseline allow/deny. */
.cell-override {
  box-shadow: inset 0 0 0 2px #c084fc;
}
.dot-override {
  background: #c084fc;
}
.cell-edit-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cell-edit-radio {
  display: flex;
  gap: 14px;
}
.denial-card {
  background: var(--bg-tertiary, #0f172a);
  border: 1px solid #4b5563;
  border-left: 3px solid #f87171;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 8px;
}
.denial-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  flex-wrap: wrap;
}
.denial-time {
  margin-left: auto;
}
.denial-body {
  font-size: 12px;
  color: #cbd5e1;
  margin-top: 6px;
}

/* ─── Scheduler ─── */
.sched-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
}
.sched-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #0f172a;
  border-left: 2px solid #475569;
  font-size: 12px;
}
.sched-row.running {
  border-left-color: #facc15;
}
.sched-row.queued {
  border-left-color: #60a5fa;
}
</style>
