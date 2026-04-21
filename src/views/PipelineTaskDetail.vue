<template>
  <div class="task-detail" v-if="task">
    <header class="detail-header">
      <div class="header-breadcrumb">
        <router-link to="/pipeline" class="back-link">
          <el-icon><ArrowLeft /></el-icon>
          流水线
        </router-link>
        <span class="separator">/</span>
        <span class="task-id">{{ task.id.slice(0, 8) }}</span>
      </div>
      <div class="header-main">
        <h1>{{ task.title }}</h1>
        <div class="header-tags">
          <el-tag :type="statusTagType" size="default">{{ statusLabel }}</el-tag>
          <el-tag :type="sourceTagType(task.source)" size="small">{{ task.source }}</el-tag>
        </div>
      </div>
      <p v-if="task.description" class="task-description">{{ task.description }}</p>
      <div v-if="task.template || task.repoUrl || task.projectPath" class="task-meta-row">
        <el-tag v-if="task.template" size="small" type="info">模板: {{ task.template }}</el-tag>
        <el-tag v-if="task.repoUrl" size="small" type="success">Git: {{ task.repoUrl }}</el-tag>
        <el-tag v-if="task.projectPath" size="small" type="warning">本地: {{ task.projectPath }}</el-tag>
      </div>
    </header>

    <section v-if="qualitySummary.total > 0" class="quality-summary">
      <div class="quality-bar">
        <span class="quality-label">质量门禁</span>
        <div class="quality-pills">
          <span class="quality-pill pass" v-if="qualitySummary.pass">✅ {{ qualitySummary.pass }}</span>
          <span class="quality-pill warn" v-if="qualitySummary.warn">⚠️ {{ qualitySummary.warn }}</span>
          <span class="quality-pill fail" v-if="qualitySummary.fail">❌ {{ qualitySummary.fail }}</span>
        </div>
        <span class="quality-avg" v-if="qualitySummary.avgScore > 0">
          平均评分: ⭐ {{ qualitySummary.avgScore.toFixed(1) }}
        </span>
      </div>
    </section>

    <PipelineDagCanvas
      v-if="task.stages.length"
      :task="task"
      :processing-stage-id="processingStage"
      @node-click="scrollToStage"
    />

    <section class="stage-progress">
      <h2 class="section-title">阶段进度</h2>
      <div class="stage-timeline">
        <div
          v-for="(stage, idx) in task.stages"
          :key="stage.id"
          :ref="(el) => registerStageRef(stage.id, el as Element | null)"
          class="timeline-item"
          :class="[
            `status-${stage.status}`,
            { current: stage.id === task.currentStageId },
            { processing: processingStage === stage.id },
          ]"
        >
          <div class="timeline-dot">
            <el-icon v-if="processingStage === stage.id" :size="14" class="spin-icon"><Loading /></el-icon>
            <el-icon v-else-if="stage.status === 'done'" :size="14"><Check /></el-icon>
            <el-icon v-else-if="stage.status === 'reviewing'" :size="14" class="spin-icon"><View /></el-icon>
            <el-icon v-else-if="stage.status === 'rejected'" :size="14"><CloseBold /></el-icon>
            <el-icon v-else-if="stage.status === 'awaiting_approval'" :size="14"><Bell /></el-icon>
            <el-icon v-else-if="stage.status === 'active'" :size="14"><Loading /></el-icon>
            <span v-else class="dot-number">{{ idx + 1 }}</span>
          </div>
          <div class="timeline-connector" v-if="idx < task.stages.length - 1"></div>
          <div class="timeline-content">
            <div class="stage-label-row">
              <span class="stage-label">{{ stage.label }}</span>
              <el-tag v-if="processingStage === stage.id" size="small" type="warning" class="processing-tag">
                AI 处理中...
              </el-tag>
              <el-tag v-if="stage.status === 'reviewing'" size="small" type="warning">
                审阅中
              </el-tag>
              <el-tag v-if="stage.reviewStatus === 'approved'" size="small" type="success" effect="plain">
                ✓ 审阅通过
              </el-tag>
              <el-tag v-if="stage.reviewStatus === 'rejected'" size="small" type="danger" effect="plain">
                ✗ 审阅未通过
              </el-tag>
              <el-tag v-if="stage.status === 'awaiting_approval'" size="small" type="danger">
                等待审批
              </el-tag>
              <span v-if="stage.verifyStatus" class="verify-badge" :class="stage.verifyStatus">
                {{ stage.verifyStatus === 'pass' ? '✅' : stage.verifyStatus === 'warn' ? '⚠️' : '❌' }}
                {{ stage.verifyStatus.toUpperCase() }}
              </span>
              <span v-if="stage.gateStatus" class="gate-badge" :class="'gate-' + stage.gateStatus">
                {{ gateIcon(stage.gateStatus) }} {{ gateLabel(stage.gateStatus) }}
              </span>
              <span v-if="stage.gateScore != null" class="gate-score">
                {{ (stage.gateScore * 100).toFixed(0) }}%
              </span>
              <span v-if="stage.qualityScore != null" class="quality-score">
                ⭐ {{ stage.qualityScore.toFixed(1) }}
              </span>
            </div>
            <div class="stage-role">
              {{ stage.ownerRole }}
              <span v-if="stage.reviewerAgent" class="reviewer-info">
                · 审阅者: {{ stage.reviewerAgent }}
                <span v-if="stage.reviewAttempts && stage.reviewAttempts > 1" class="attempt-badge">
                  第 {{ stage.reviewAttempts }} 轮
                </span>
              </span>
            </div>
            <div v-if="stage.startedAt" class="stage-time">
              开始: {{ formatDate(stage.startedAt) }}
            </div>
            <div v-if="stage.completedAt" class="stage-time">
              完成: {{ formatDate(stage.completedAt) }}
              <span class="duration" v-if="stage.startedAt">
                ({{ formatDuration(stage.completedAt - stage.startedAt) }})
              </span>
            </div>

            <!-- Review feedback -->
            <div v-if="stage.reviewerFeedback" class="review-feedback">
              <div class="feedback-header" @click="toggleFeedback(stage.id)">
                <el-icon><ChatDotSquare /></el-icon>
                <span>审阅反馈</span>
                <el-icon class="toggle-icon" :class="{ expanded: expandedFeedback.has(stage.id) }">
                  <ArrowDown />
                </el-icon>
              </div>
              <div v-if="expandedFeedback.has(stage.id)" class="feedback-body">
                <div class="output-content-md" v-html="renderMarkdown(stage.reviewerFeedback)"></div>
              </div>
            </div>

            <!-- Quality gate details -->
            <div v-if="stage.gateDetails && (stage.gateStatus === 'failed' || stage.gateStatus === 'warning')" class="gate-detail-panel">
              <div class="gate-detail-header" @click="toggleGateDetail(stage.id)">
                <el-icon><Warning /></el-icon>
                <span>质量门禁详情</span>
                <el-icon class="toggle-icon" :class="{ expanded: expandedGateDetails.has(stage.id) }">
                  <ArrowDown />
                </el-icon>
              </div>
              <div v-if="expandedGateDetails.has(stage.id)" class="gate-detail-body">
                <div v-if="stage.gateDetails.block_reason" class="gate-block-reason">
                  <strong>阻断原因:</strong> {{ stage.gateDetails.block_reason }}
                </div>
                <div v-if="stage.gateDetails.checks?.length" class="gate-checks">
                  <div v-for="check in stage.gateDetails.checks" :key="check.name" class="gate-check-item">
                    <span class="gate-check-icon">{{ gateIcon(check.status) }}</span>
                    <span class="gate-check-name">{{ check.name }}</span>
                    <span class="gate-check-score">{{ (check.score * 100).toFixed(0) }}%</span>
                    <span class="gate-check-msg">{{ check.message }}</span>
                  </div>
                </div>
                <div v-if="stage.gateDetails.suggestions?.length" class="gate-suggestions">
                  <p v-for="(s, i) in stage.gateDetails.suggestions" :key="i" class="gate-suggestion">{{ s }}</p>
                </div>
                <div v-if="stage.gateStatus === 'failed'" class="gate-override-action">
                  <el-button type="warning" size="small" @click="handleGateOverride(stage.id)" :loading="overridingGate === stage.id">
                    <el-icon><Unlock /></el-icon> 人工放行
                  </el-button>
                </div>
              </div>
            </div>

            <div v-if="stage.gateDetails?.override" class="gate-override-info">
              <span class="override-badge">🔓 已人工放行</span>
              <span class="override-by">{{ stage.gateDetails.override.by }}</span>
              <span v-if="stage.gateDetails.override.reason" class="override-reason">: {{ stage.gateDetails.override.reason }}</span>
            </div>

            <!-- Human approval buttons -->
            <div v-if="stage.status === 'awaiting_approval'" class="approval-actions">
              <p class="approval-hint">此阶段需要人工审批确认后才能继续</p>
              <div class="approval-btns">
                <el-button type="success" size="small" @click="handleApproveStage(stage.id, true)" :loading="approvingStage === stage.id">
                  <el-icon><Check /></el-icon> 批准
                </el-button>
                <el-button type="danger" size="small" @click="handleApproveStage(stage.id, false)" :loading="approvingStage === stage.id">
                  <el-icon><Close /></el-icon> 驳回
                </el-button>
              </div>
            </div>

            <div v-if="stage.output" class="stage-output-preview">
              <div class="output-header" @click="toggleOutput(stage.id)">
                <el-icon><Document /></el-icon>
                <span>查看产出</span>
                <el-icon class="toggle-icon" :class="{ expanded: expandedOutputs.has(stage.id) }">
                  <ArrowDown />
                </el-icon>
              </div>
              <div v-if="expandedOutputs.has(stage.id)" class="output-body">
                <div class="output-content-md" v-html="renderMarkdown(stage.output)"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 子任务追踪面板 (deer-flow 风格) -->
    <section class="subtask-tracking" v-if="subtasks.length">
      <h2 class="section-title">
        <span class="icon-brain">🧠</span>
        Lead Agent 子任务
        <el-tag size="small" type="info" style="margin-left: 8px">
          {{ completedSubtasks }}/{{ subtasks.length }}
        </el-tag>
      </h2>
      <div class="subtask-list">
        <SubtaskCard
          v-for="st in subtasks"
          :key="st.id"
          :subtask="st"
        />
      </div>
    </section>

    <section class="task-actions" v-if="task.status === 'paused'">
      <h2 class="section-title">Pipeline 已暂停</h2>
      <div class="paused-info">
        <p>Pipeline 在阶段「{{ task.currentStageId }}」暂停，可能需要人工审批或审阅反馈已达上限。</p>
        <div class="action-buttons">
          <el-button type="success" size="large" @click="handleResume(false)" :loading="resuming">
            <el-icon><CaretRight /></el-icon> 恢复执行（线性）
          </el-button>
          <el-button type="primary" size="large" @click="handleResumeDag" :loading="resumingDag">
            <el-icon><Refresh /></el-icon> 续跑 DAG（断点续传）
          </el-button>
          <el-button size="large" @click="handleResume(true)" :loading="resuming">
            <el-icon><RefreshRight /></el-icon> 强制继续（跳过审阅）
          </el-button>
        </div>
      </div>
    </section>

    <section class="task-actions" v-else-if="task.status === 'failed'">
      <h2 class="section-title">Pipeline 已失败</h2>
      <div class="paused-info">
        <p>
          上次执行在阶段「{{ task.currentStageId }}」失败。可以从最近的检查点续跑，
          已完成的阶段会被跳过。
        </p>
        <div class="action-buttons">
          <el-button type="primary" size="large" @click="handleResumeDag" :loading="resumingDag">
            <el-icon><Refresh /></el-icon> 从检查点续跑
          </el-button>
          <el-button size="large" @click="openRcaDialog" :loading="rcaLoading">
            <el-icon><WarningFilled /></el-icon> 生成 RCA 报告
          </el-button>
        </div>
      </div>
    </section>

    <section class="task-actions" v-if="task.status === 'active'">
      <h2 class="section-title">操作</h2>
      <div class="action-buttons">
        <el-button
          type="success"
          size="large"
          @click="handleSmartRun"
          :loading="smartRunning"
          :disabled="task.currentStageId === 'done' || (anyExecutionRunning && !smartRunning)"
        >
          <span style="margin-right:4px">🧠</span>
          Lead Agent 智能执行
        </el-button>
        <el-button
          @click="handleAutoRun"
          :loading="autoRunning"
          :disabled="task.currentStageId === 'done' || (anyExecutionRunning && !autoRunning)"
        >
          <el-icon><VideoPlay /></el-icon>
          经典全自动执行
        </el-button>
        <el-button
          type="primary"
          @click="handleRunCurrentStage"
          :loading="stageRunning"
          :disabled="task.currentStageId === 'done' || (anyExecutionRunning && !stageRunning)"
        >
          <el-icon><CaretRight /></el-icon>
          AI 执行当前阶段
        </el-button>
        <el-button
          @click="handleAdvance"
          :disabled="task.currentStageId === 'done' || anyExecutionRunning"
        >
          <el-icon><Right /></el-icon>
          手动跳过
        </el-button>
        <el-button
          type="warning"
          @click="showRejectDialog = true"
          :disabled="task.currentStageId === 'planning' || anyExecutionRunning"
        >
          <el-icon><Back /></el-icon>
          打回
        </el-button>
        <el-button
          v-if="task.currentStageId === 'development'"
          @click="handleResume(false)"
          :loading="resuming"
          :disabled="anyExecutionRunning && !resuming"
        >
          <el-icon><RefreshRight /></el-icon>
          确认构建完成 & 继续
        </el-button>
        <el-button
          @click="goToAgent"
        >
          <el-icon><ChatDotSquare /></el-icon>
          进入 Agent 对话
        </el-button>
      </div>
    </section>

    <section class="live-log" v-if="stageLogs.length">
      <h2 class="section-title">
        实时日志
        <el-tag size="small" type="info" style="margin-left: 8px">{{ stageLogs.length }}</el-tag>
      </h2>
      <div class="log-container" ref="logContainer">
        <div
          v-for="(log, i) in stageLogs"
          :key="i"
          class="log-entry"
          :class="log.event"
        >
          <span class="log-time">{{ formatLogTime(log.timestamp) }}</span>
          <span class="log-event">{{ formatEventName(log.event) }}</span>
          <span class="log-detail" v-if="log.detail">{{ log.detail }}</span>
        </div>
      </div>
    </section>

    <!-- Quality Report Section -->
    <section v-if="qualityReport" class="quality-report-section">
      <h2 class="section-title">
        质量门禁报告
        <el-tag
          :type="qualityReport.summary.overall_verdict === 'PASSED' ? 'success' : qualityReport.summary.overall_verdict === 'FAILED' ? 'danger' : 'warning'"
          size="small"
          style="margin-left: 8px"
        >
          {{ qualityReport.summary.overall_verdict }}
        </el-tag>
      </h2>
      <div class="qr-summary">
        <div class="qr-stat">
          <span class="qr-stat-value">{{ qualityReport.summary.gates_evaluated }}</span>
          <span class="qr-stat-label">已评估</span>
        </div>
        <div class="qr-stat">
          <span class="qr-stat-value">{{ (qualityReport.summary.average_score * 100).toFixed(0) }}%</span>
          <span class="qr-stat-label">平均分</span>
        </div>
        <div class="qr-stat" v-if="task.overallQualityScore != null">
          <span class="qr-stat-value">{{ (task.overallQualityScore * 100).toFixed(0) }}%</span>
          <span class="qr-stat-label">总评分</span>
        </div>
      </div>
      <div class="qr-stages">
        <div v-for="sr in qualityReport.stages" :key="sr.stage_id" class="qr-stage-row">
          <span class="qr-stage-label">{{ sr.label }}</span>
          <span class="qr-gate-icon">{{ gateIcon(sr.gate_status) }}</span>
          <div class="qr-score-bar">
            <div
              class="qr-score-fill"
              :class="sr.gate_status"
              :style="{ width: `${(sr.gate_score ?? 0) * 100}%` }"
            ></div>
          </div>
          <span class="qr-score-text">{{ sr.gate_score != null ? `${(sr.gate_score * 100).toFixed(0)}%` : '—' }}</span>
          <span class="qr-threshold">门禁: {{ (sr.pass_threshold * 100).toFixed(0) }}%</span>
        </div>
      </div>
    </section>

    <section class="deliverable-section" v-if="task.status === 'done'">
      <div class="deliverable-bar">
        <h2 class="section-title">项目交付汇总</h2>
        <div class="deliverable-actions">
          <el-button type="primary" size="small" @click="handleCompile" :loading="compiling">
            <el-icon><Document /></el-icon>
            生成交付文档
          </el-button>
          <el-button
            v-if="compiledContent"
            size="small"
            @click="handleDownload"
          >
            <el-icon><Download /></el-icon>
            下载 Markdown
          </el-button>
        </div>
      </div>
      <div v-if="compiledContent" class="compiled-preview" v-html="renderMarkdown(compiledContent)"></div>
    </section>

    <section class="task-artifacts">
      <div class="artifacts-header-row">
        <h2 class="section-title">
          交付产物
          <el-tag v-if="task.artifacts?.length" size="small" type="info" style="margin-left: 8px">{{ task.artifacts.length }}</el-tag>
        </h2>
        <el-upload
          class="artifact-upload-inline"
          :show-file-list="false"
          :http-request="handleArtifactUpload"
          multiple
        >
          <el-button size="small" type="primary" :loading="uploadingArtifacts">上传附件</el-button>
        </el-upload>
      </div>
      <p v-if="!task.artifacts?.length" class="artifact-empty-hint">
        暂无产物。可上传参考图、需求说明、接口文档等；各阶段会随模型能力发送多模态或文本上下文。
      </p>
      <div v-else class="artifact-list">
        <div
          v-for="artifact in task.artifacts"
          :key="artifact.id"
          class="artifact-card"
        >
          <div class="artifact-header">
            <div class="artifact-name">
              <el-tag size="small" :type="artifactTagType(artifact.type)">{{ artifact.type }}</el-tag>
              {{ artifact.name }}
            </div>
            <el-tag size="small" type="info">{{ artifact.stageId }}</el-tag>
          </div>
          <div class="artifact-body">
            <template v-if="artifactHasBinary(artifact)">
              <p class="artifact-file-meta">
                {{ artifactMimeLabel(artifact) }}
                <span v-if="artifact.type === 'upload_image'" class="text-muted-inline"> · 图片</span>
              </p>
              <el-button size="small" @click="downloadArtifactFile(artifact)">下载原文件</el-button>
            </template>
            <template v-else-if="artifact.content">
              <div
                v-if="expandedArtifacts.has(artifact.id)"
                class="artifact-content-full"
                v-html="renderMarkdown(artifact.content)"
              ></div>
              <pre v-else class="artifact-content-preview">{{ (artifact.content || '').slice(0, 300) }}{{ (artifact.content || '').length > 300 ? '...' : '' }}</pre>
            </template>
            <p v-else class="text-muted-inline">无文本预览</p>
          </div>
          <el-button
            v-if="artifact.content && !artifactHasBinary(artifact)"
            text
            size="small"
            @click="toggleArtifact(artifact.id)"
            class="artifact-toggle"
          >
            {{ expandedArtifacts.has(artifact.id) ? '收起' : '展开全部' }}
          </el-button>
        </div>
      </div>
    </section>

    <el-dialog v-model="rcaDialog" title="RCA 根因分析报告" width="780px" :close-on-click-modal="false">
      <div v-if="rcaLoading" class="rca-loading">
        <el-icon class="loading-icon" :size="32"><Loading /></el-icon>
        <p>正在收集 stage 错误 + span + audit + bus 消息，并请求 LLM 综合分析…</p>
      </div>
      <div v-else-if="!rcaReport" class="rca-empty">未生成报告</div>
      <div v-else class="rca-report">
        <div class="rca-header">
          <el-tag :type="rcaSeverityType(rcaReport.severity)">{{ rcaReport.severity || 'medium' }}</el-tag>
          <span class="rca-radius" v-if="rcaReport.blast_radius">影响面：{{ rcaReport.blast_radius }}</span>
          <span class="rca-time">生成于 {{ rcaReport.generated_at }}</span>
        </div>
        <h3>摘要</h3>
        <p class="rca-summary">{{ rcaReport.summary || '（无）' }}</p>
        <h3>根本原因</h3>
        <pre class="rca-block">{{ rcaReport.root_cause || '（未确定）' }}</pre>
        <h3 v-if="(rcaReport.contributing_factors || []).length">关联因素</h3>
        <ul v-if="(rcaReport.contributing_factors || []).length">
          <li v-for="(f, i) in rcaReport.contributing_factors" :key="i">{{ f }}</li>
        </ul>
        <h3 v-if="(rcaReport.recommended_actions || []).length">建议行动</h3>
        <ol v-if="(rcaReport.recommended_actions || []).length">
          <li v-for="(a, i) in rcaReport.recommended_actions" :key="i">{{ a }}</li>
        </ol>
        <details class="rca-details">
          <summary>失败 Stage（{{ rcaReport.failed_stages?.length || 0 }}）</summary>
          <div v-for="(s, idx) in rcaReport.failed_stages" :key="idx" class="rca-stage">
            <strong>{{ s.stage_id }}</strong> · {{ s.owner_role }} · {{ s.status }}
            （重试 {{ s.retry_count }}/{{ s.max_retries }}）
            <pre v-if="s.last_error">{{ s.last_error }}</pre>
          </div>
        </details>
        <details class="rca-details" v-if="rcaReport.evidence">
          <summary>原始证据（{{ rcaReport.spans_examined }} spans · {{ rcaReport.audits_examined }} audits · {{ rcaReport.bus_msgs_examined }} bus msgs）</summary>
          <pre class="rca-evidence">{{ rcaReport.evidence }}</pre>
        </details>
        <p v-if="rcaReport.llm_error" class="rca-warn">⚠ LLM 调用未成功：{{ rcaReport.llm_error }}</p>
      </div>
      <template #footer>
        <el-button @click="rcaDialog = false">关闭</el-button>
        <el-button type="primary" @click="openRcaDialog" :loading="rcaLoading">重新生成</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showRejectDialog" title="打回任务" width="400px">
      <el-form label-position="top">
        <el-form-item label="打回到哪个阶段">
          <el-select v-model="rejectTarget" style="width: 100%">
            <el-option
              v-for="stage in previousStages"
              :key="stage.id"
              :label="stage.label"
              :value="stage.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="打回原因">
          <el-input v-model="rejectReason" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRejectDialog = false">取消</el-button>
        <el-button type="warning" @click="handleReject">确认打回</el-button>
      </template>
    </el-dialog>
  </div>

  <div v-else-if="loadError" class="task-loading">
    <p class="error-text">{{ loadError }}</p>
    <el-button type="primary" @click="loadTask" style="margin-top: 12px">重试</el-button>
    <el-button @click="router.push('/pipeline')" style="margin-top: 12px">返回列表</el-button>
  </div>

  <div v-else class="task-loading">
    <el-icon class="loading-icon" :size="32"><Loading /></el-icon>
    <p>加载中...</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowDown, ArrowLeft, Back, Bell, CaretRight, Check, Close, CloseBold,
  ChatDotSquare, Document, Download, Loading, Refresh, RefreshRight, Right, Unlock,
  VideoPlay, View, Warning, WarningFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { usePipelineStore } from '@/stores/pipeline'
import {
  fetchTask, runStage as apiRunStage, autoRunPipeline, resumeAfterBuild,
  smartRunPipeline, subscribePipelineEvents,
  approveStage as apiApproveStage, resumePipeline, resumeDagPipeline,
  compileDeliverables, fetchQualityReport, overrideQualityGate,
  uploadTaskAttachment, downloadTaskAttachment,
  getTaskRca,
} from '@/services/pipelineApi'
import type { RcaReport } from '@/services/pipelineApi'
import type { TaskArtifact } from '@/agents/types'
import type { UploadRequestOptions } from 'element-plus'
import type { QualityReport } from '@/services/pipelineApi'
import type { PipelineTask, PipelineEvent, SubtaskInfo } from '@/agents/types'
import { renderMarkdown } from '@/services/markdown'
import SubtaskCard from '@/components/SubtaskCard.vue'
import PipelineDagCanvas from '@/components/pipeline/PipelineDagCanvas.vue'

const route = useRoute()
const router = useRouter()
const pipelineStore = usePipelineStore()

const task = ref<PipelineTask | null>(null)
const loadError = ref('')
const autoRunning = ref(false)
const smartRunning = ref(false)
const stageRunning = ref(false)
const resuming = ref(false)
const resumingDag = ref(false)
const rcaDialog = ref(false)
const rcaLoading = ref(false)
const rcaReport = ref<RcaReport | null>(null)
const anyExecutionRunning = computed(() =>
  autoRunning.value || smartRunning.value || stageRunning.value || resuming.value || resumingDag.value
)
const subtasks = ref<SubtaskInfo[]>([])
const processingStage = ref<string | null>(null)
const showRejectDialog = ref(false)
const rejectTarget = ref('')
const rejectReason = ref('')
const expandedOutputs = reactive(new Set<string>())
const expandedArtifacts = reactive(new Set<string>())
const expandedFeedback = reactive(new Set<string>())
const approvingStage = ref<string | null>(null)
const compiling = ref(false)
const compiledContent = ref('')
const logContainer = ref<HTMLElement | null>(null)
const expandedGateDetails = reactive(new Set<string>())
const overridingGate = ref<string | null>(null)
const qualityReport = ref<QualityReport | null>(null)

interface LogEntry {
  event: string
  timestamp: number
  detail?: string
}
const stageLogs = ref<LogEntry[]>([])

// Map stageId → DOM element, populated via :ref callback on each timeline-item.
// Used by the DAG canvas to scroll the matching stage card into view when a
// node is clicked, so the canvas + stepper feel like one coherent view.
const stageRefs = new Map<string, Element>()
function registerStageRef(stageId: string, el: Element | null) {
  if (el) stageRefs.set(stageId, el)
  else stageRefs.delete(stageId)
}
function scrollToStage(stageId: string) {
  const el = stageRefs.get(stageId)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  // Brief highlight flash so the user knows where they landed.
  el.classList.add('flash-highlight')
  setTimeout(() => el.classList.remove('flash-highlight'), 1200)
}

const STAGE_IDS = ['planning', 'architecture', 'development', 'testing', 'reviewing', 'deployment', 'done']

const stageToAgent: Record<string, string> = {
  planning: 'ceo-agent',
  architecture: 'architect-agent',
  development: 'developer-agent',
  testing: 'qa-agent',
  reviewing: 'ceo-agent',
  deployment: 'devops-agent',
}

const completedSubtasks = computed(() =>
  subtasks.value.filter(s => s.status === 'completed').length
)

const statusLabel = computed(() => {
  const labels: Record<string, string> = {
    active: '进行中',
    paused: '已暂停',
    done: '已完成',
    cancelled: '已取消',
  }
  return labels[task.value?.status || ''] || task.value?.status
})

const statusTagType = computed(() => {
  const map: Record<string, string> = {
    active: 'primary',
    paused: 'warning',
    done: 'success',
    cancelled: 'danger',
  }
  return (map[task.value?.status || ''] || 'info') as '' | 'success' | 'warning' | 'info' | 'danger'
})

function sourceTagType(source: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  const map: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    feishu: 'warning', qq: 'success', web: 'info', api: 'primary', 'api-e2e': 'danger',
  }
  return map[source] ?? 'info'
}

function artifactTagType(type: string) {
  const map: Record<string, string> = {
    document: 'primary',
    code: 'success',
    test: 'warning',
    upload_image: 'success',
    upload_file: 'warning',
    codegen: 'info',
  }
  return (map[type] || 'info') as '' | 'success' | 'warning' | 'info' | 'danger'
}

const uploadingArtifacts = ref(false)

function artifactHasBinary(a: TaskArtifact) {
  return a.type === 'upload_image' || a.type === 'upload_file'
}

function artifactMimeLabel(a: TaskArtifact) {
  return String(a.metadata?.mime ?? '未知类型')
}

async function handleArtifactUpload(options: UploadRequestOptions) {
  if (!task.value) return
  uploadingArtifacts.value = true
  try {
    await uploadTaskAttachment(task.value.id, options.file as File)
    await loadTask()
    ElMessage.success(`已上传 ${options.file.name}`)
    options.onSuccess?.({} as never)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
    options.onError?.(e as Error)
  } finally {
    uploadingArtifacts.value = false
  }
}

async function downloadArtifactFile(a: TaskArtifact) {
  if (!task.value) return
  try {
    await downloadTaskAttachment(task.value.id, a.id, a.name)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

async function handleCompile() {
  if (!task.value) return
  compiling.value = true
  try {
    const result = await compileDeliverables(task.value.id)
    compiledContent.value = result.content
    ElMessage.success('交付文档已生成')
  } catch (e: unknown) {
    ElMessage.error(`生成失败: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    compiling.value = false
  }
}

function handleDownload() {
  if (!compiledContent.value) return
  const blob = new Blob([compiledContent.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `project-summary-${task.value?.id?.slice(0, 8) ?? 'task'}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

const qualitySummary = computed(() => {
  const stages = task.value?.stages ?? []
  const withVerify = stages.filter(s => s.verifyStatus)
  const pass = withVerify.filter(s => s.verifyStatus === 'pass').length
  const warn = withVerify.filter(s => s.verifyStatus === 'warn').length
  const fail = withVerify.filter(s => s.verifyStatus === 'fail').length
  const scores = stages.map(s => s.qualityScore).filter((v): v is number => v != null)
  const avgScore = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0
  return { total: withVerify.length, pass, warn, fail, avgScore }
})

const previousStages = computed(() => {
  if (!task.value) return []
  const currentIdx = STAGE_IDS.indexOf(task.value.currentStageId)
  if (currentIdx <= 0) return []
  return task.value.stages
    .filter(s => {
      const sIdx = STAGE_IDS.indexOf(s.id)
      return sIdx >= 0 && sIdx < currentIdx
    })
})

function formatDate(ts: number) {
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function formatDuration(ms: number) {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}

function formatLogTime(ts: number) {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatEventName(event: string) {
  const map: Record<string, string> = {
    'stage:queued': '⏳ 排队',
    'stage:processing': '🔄 处理中',
    'stage:completed': '✅ 完成',
    'stage:error': '❌ 错误',
    'task:stage-advanced': '➡️ 推进',
    'task:created': '📝 创建',
    'task:updated': '📝 更新',
    'pipeline:auto-start': '🚀 自动启动',
    'pipeline:auto-completed': '🎉 全流程完成',
    'pipeline:auto-paused': '⏸️ 暂停',
    'pipeline:auto-error': '💥 流程错误',
    'pipeline:smart-start': '🧠 Lead Agent 启动',
    'pipeline:smart-completed': '🧠 智能流水线完成',
    'pipeline:smart-error': '🧠 智能流水线错误',
    'lead-agent:analyzing': '🔍 Lead Agent 分析中',
    'lead-agent:plan-ready': '📋 任务分解完成',
    'lead-agent:error': '❌ Lead Agent 错误',
    'subtask:start': '▶️ 子任务启动',
    'subtask:completed': '✅ 子任务完成',
    'subtask:failed': '❌ 子任务失败',
    'subtasks:batch-start': '⚡ 并行批次启动',
    'middleware:blocked': '🛡️ 中间件拦截',
    'middleware:token-usage': '📊 Token 用量',
    'executor:started': '⚡ Claude Code 启动',
    'executor:launched': '🚀 Claude Code 运行中',
    'executor:log': '📋 Claude Code 日志',
    'executor:completed': '✅ Claude Code 完成',
    'executor:error': '❌ Claude Code 错误',
    'executor:timeout': '⏰ Claude Code 超时',
    'executor:killed': '🛑 Claude Code 已终止',
    'stage:quality-gate': '🚦 质量门禁评估',
    'stage:gate-overridden': '🔓 门禁人工放行',
    'stage:peer-reviewing': '🔍 Peer Review 审阅中',
    'stage:peer-review-approved': '✅ Peer Review 通过',
    'stage:peer-review-rejected': '❌ Peer Review 驳回',
    'stage:peer-review-error': '⚠️ Peer Review 出错',
    'stage:rework': '🔄 根据反馈修改中',
    'stage:awaiting-approval': '🔔 等待人工审批',
    'stage:approval-granted': '✅ 人工审批通过',
    'stage:approval-denied': '❌ 人工审批驳回',
    'pipeline:resumed': '▶️ Pipeline 恢复执行',
    'pipeline:dag-resumed': '▶️ DAG 续跑',
    'pipeline:dag-start': '🚀 DAG 启动',
    'pipeline:dag-batch': '⚡ DAG 批次',
    'pipeline:dag-completed': '🎉 DAG 完成',
    'pipeline:dag-branch': '🔀 DAG 分支重置',
    'pipeline:rollback': '⏪ 阶段回滚',
    'stage:retry': '🔁 阶段重试',
    'stage:skipped': '⏭️ 阶段跳过',
    'agent:bus-message': '📨 Agent 消息',
    'pipeline:rca-generated': '🩺 RCA 报告',
  }
  return map[event] || event
}

function gateIcon(status: string | null | undefined) {
  const icons: Record<string, string> = {
    passed: '🟢', warning: '🟡', failed: '🔴', bypassed: '🔓', pending: '⚪',
  }
  return icons[status || ''] || '⚪'
}

function gateLabel(status: string | null | undefined) {
  const labels: Record<string, string> = {
    passed: '门禁通过', warning: '门禁警告', failed: '门禁失败', bypassed: '已放行', pending: '待评估',
  }
  return labels[status || ''] || ''
}

function toggleGateDetail(stageId: string) {
  if (expandedGateDetails.has(stageId)) expandedGateDetails.delete(stageId)
  else expandedGateDetails.add(stageId)
}

async function handleGateOverride(stageId: string) {
  if (!task.value) return
  overridingGate.value = stageId
  try {
    await overrideQualityGate(String(task.value.id), stageId, '人工审查后放行')
    ElMessage.success('质量门禁已放行')
    await loadTask()
    await resumePipeline(String(task.value.id), undefined, false)
  } catch (e: any) {
    ElMessage.error(e?.message || '放行失败')
  } finally {
    overridingGate.value = null
  }
}

async function loadQualityReport() {
  if (!task.value) return
  try {
    qualityReport.value = await fetchQualityReport(task.value.id)
  } catch { /* optional */ }
}

function toggleOutput(stageId: string) {
  if (expandedOutputs.has(stageId)) expandedOutputs.delete(stageId)
  else expandedOutputs.add(stageId)
}

function toggleFeedback(stageId: string) {
  if (expandedFeedback.has(stageId)) expandedFeedback.delete(stageId)
  else expandedFeedback.add(stageId)
}

async function handleApproveStage(stageId: string, approved: boolean) {
  if (!task.value) return
  approvingStage.value = stageId
  try {
    await apiApproveStage(String(task.value.id), stageId, approved)
    ElMessage.success(approved ? '已批准，Pipeline 将继续执行' : '已驳回')
    await loadTask()
    if (approved) {
      await resumePipeline(String(task.value.id), undefined, false)
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  } finally {
    approvingStage.value = null
  }
}

function toggleArtifact(id: string) {
  if (expandedArtifacts.has(id)) expandedArtifacts.delete(id)
  else expandedArtifacts.add(id)
}

function addLog(event: string, data?: Record<string, unknown>) {
  const detail = data?.error
    ? String(data.error)
    : data?.stageId
      ? `阶段: ${data.stageId}${data.label ? ` (${data.label})` : ''}`
      : data?.from && data?.to
        ? `${data.from} → ${data.to}`
        : undefined

  stageLogs.value.push({
    event,
    timestamp: Date.now(),
    detail: detail as string | undefined,
  })

  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

let unsubSSE: (() => void) | null = null

function setupSSE() {
  unsubSSE = subscribePipelineEvents((evt: PipelineEvent) => {
    const taskId = route.params.id as string
    const data = evt.data as Record<string, unknown> | undefined

    const eventTaskId = data?.taskId || (data?.task as Record<string, unknown>)?.id
    if (eventTaskId && eventTaskId !== taskId) return

    addLog(evt.event, data)

    if (evt.event === 'stage:processing') {
      processingStage.value = (data?.stageId as string) || null
    }

    if (evt.event === 'stage:completed') {
      processingStage.value = null
      stageRunning.value = false
      loadTask()
    }
    if (evt.event === 'stage:error') {
      processingStage.value = null
      stageRunning.value = false
    }

    if (evt.event === 'stage:peer-reviewing' || evt.event === 'stage:rework') {
      processingStage.value = null
      loadTask()
    }
    if (evt.event === 'stage:quality-gate' || evt.event === 'stage:gate-overridden') {
      processingStage.value = null
      loadTask()
      loadQualityReport()
    }

    if (
      evt.event === 'stage:peer-review-approved' ||
      evt.event === 'stage:peer-review-rejected' ||
      evt.event === 'stage:peer-review-error' ||
      evt.event === 'stage:awaiting-approval' ||
      evt.event === 'stage:approval-granted' ||
      evt.event === 'stage:approval-denied' ||
      evt.event === 'pipeline:resumed'
    ) {
      processingStage.value = null
      autoRunning.value = false
      smartRunning.value = false
      loadTask()
    }

    // Lead Agent 子任务追踪 (deer-flow 风格)
    if (evt.event === 'subtask:start') {
      subtasks.value.push({
        id: (data?.subtaskId as string) || '',
        title: (data?.title as string) || '',
        role: (data?.role as string) || '',
        status: 'running',
        startTime: Date.now(),
      })
    }
    if (evt.event === 'subtask:completed') {
      const st = subtasks.value.find(s => s.id === data?.subtaskId)
      if (st) {
        st.status = 'completed'
        st.endTime = Date.now()
      }
    }
    if (evt.event === 'subtask:failed') {
      const st = subtasks.value.find(s => s.id === data?.subtaskId)
      if (st) {
        st.status = 'failed'
        st.error = (data?.error as string) || '执行失败'
        st.endTime = Date.now()
      }
    }
    if (evt.event === 'lead-agent:plan-ready') {
      const plan = data?.plan as Record<string, unknown>
      if (plan?.subtaskCount) {
        addLog('lead-agent:plan-ready', {
          analysis: `分解为 ${plan.subtaskCount} 个子任务，策略: ${plan.strategy}，复杂度: ${plan.complexity}`,
        })
      }
    }

    if (
      evt.event === 'task:stage-advanced' ||
      evt.event === 'task:updated' ||
      evt.event === 'stage:completed' ||
      evt.event === 'pipeline:auto-completed' ||
      evt.event === 'pipeline:smart-completed'
    ) {
      const updatedTask = (data?.task as PipelineTask) || null
      if (updatedTask) {
        task.value = updatedTask
      } else {
        loadTask()
      }
    }

    if (evt.event === 'pipeline:auto-completed') {
      autoRunning.value = false
      stageRunning.value = false
      ElMessage.success('全自动流水线已完成！')
      loadQualityReport()
    }

    if (evt.event === 'pipeline:smart-completed') {
      smartRunning.value = false
      autoRunning.value = false
      stageRunning.value = false
      const completed = (data?.completedSubtasks as number) || 0
      const total = (data?.subtaskCount as number) || 0
      ElMessage.success(`Lead Agent 智能执行完成！${completed}/${total} 子任务成功`)
    }

    if (evt.event === 'pipeline:auto-paused') {
      autoRunning.value = false
      ElMessage.info('流水线在 building 阶段暂停，请确认 Claude Code 执行完成后继续。')
    }

    if (evt.event === 'pipeline:auto-error' || evt.event === 'stage:error' || evt.event === 'pipeline:smart-error') {
      autoRunning.value = false
      smartRunning.value = false
      stageRunning.value = false
      ElMessage.error(`执行失败: ${data?.error || '未知错误'}`)
    }
  })
}

async function handleSmartRun() {
  if (!task.value) return
  smartRunning.value = true
  stageLogs.value = []
  subtasks.value = []
  try {
    await smartRunPipeline(task.value.id)
    addLog('pipeline:smart-start', { taskId: task.value.id })
    ElMessage.success('Lead Agent 已启动后台执行，可自由切换页面')
  } catch (e: unknown) {
    smartRunning.value = false
    ElMessage.error(`智能执行启动失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

async function handleResume(forceContinue = false) {
  if (!task.value) return
  resuming.value = true
  try {
    const res = await resumePipeline(String(task.value.id), undefined, forceContinue)
    addLog('pipeline:resumed', { fromStage: res.resumed_from })
    ElMessage.success(`Pipeline 已从「${res.resumed_from}」恢复执行`)
    await loadTask()
  } catch (e: unknown) {
    ElMessage.error(`恢复失败: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    resuming.value = false
  }
}

function rcaSeverityType(severity?: string): 'success' | 'info' | 'warning' | 'danger' {
  switch ((severity || '').toLowerCase()) {
    case 'low': return 'success'
    case 'medium': return 'warning'
    case 'high': return 'danger'
    case 'critical': return 'danger'
    default: return 'info'
  }
}

async function openRcaDialog() {
  if (!task.value) return
  rcaDialog.value = true
  rcaLoading.value = true
  try {
    const r = await getTaskRca(String(task.value.id), true)
    rcaReport.value = r
    addLog('pipeline:rca-generated', {
      severity: r.severity,
      stages_failed: r.failed_stages?.length || 0,
    })
  } catch (e: unknown) {
    ElMessage.error(`RCA 生成失败: ${e instanceof Error ? e.message : String(e)}`)
    rcaDialog.value = false
  } finally {
    rcaLoading.value = false
  }
}

async function handleResumeDag() {
  if (!task.value) return
  resumingDag.value = true
  try {
    const res = await resumeDagPipeline(String(task.value.id))
    addLog('pipeline:dag-queued', {
      fromCheckpoint: res.resumedFromCheckpoint,
      template: res.template,
      submissionId: res.submissionId,
    })
    ElMessage({
      type: 'info',
      duration: 4000,
      message:
        res.message ||
        `已加入续跑队列（template=${res.template}${
          res.resumedFromCheckpoint ? '，从检查点恢复' : '，无检查点'
        }），请关注下方实时日志`,
    })
    await loadTask()
  } catch (e: unknown) {
    ElMessage.error(`DAG 续跑提交失败: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    resumingDag.value = false
  }
}

async function handleAutoRun() {
  if (!task.value) return
  autoRunning.value = true
  stageLogs.value = []
  try {
    await autoRunPipeline(task.value.id)
    addLog('pipeline:auto-start', { taskId: task.value.id })
    ElMessage.success('全自动流水线已启动后台执行，可自由切换页面')
  } catch (e: unknown) {
    autoRunning.value = false
    ElMessage.error(`启动失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

async function handleRunCurrentStage() {
  if (!task.value) return
  stageRunning.value = true
  try {
    await apiRunStage(task.value.id)
    addLog('stage:queued', { stageId: task.value.currentStageId })
    ElMessage.success('AI 已开始执行当前阶段，可自由切换页面')
  } catch (e: unknown) {
    stageRunning.value = false
    ElMessage.error(`执行失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

async function handleAdvance() {
  if (!task.value) return
  try {
    task.value = await pipelineStore.advanceTask(task.value.id)
    addLog('task:stage-advanced', { from: '(手动)', to: task.value.currentStageId })
  } catch (e: unknown) {
    ElMessage.error(`推进失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

async function handleReject() {
  if (!task.value || !rejectTarget.value) return
  try {
    task.value = await pipelineStore.rejectTask(
      task.value.id,
      rejectTarget.value,
      rejectReason.value,
    )
    showRejectDialog.value = false
    rejectTarget.value = ''
    rejectReason.value = ''
    ElMessage.success('任务已打回')
  } catch (e: unknown) {
    ElMessage.error(`打回失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

function goToAgent() {
  if (!task.value) return
  const agentId = stageToAgent[task.value.currentStageId] || 'wayne-orchestrator'
  router.push({
    path: `/agent/${agentId}`,
    query: { pipelineTask: task.value.id },
  })
}

async function loadTask() {
  const id = route.params.id as string
  if (!id) return
  loadError.value = ''
  try {
    task.value = await fetchTask(id)
    // Detect if a background run is in progress (stage is active but has no output yet)
    if (task.value && task.value.status === 'active') {
      const activeStage = task.value.stages.find(s => s.status === 'active')
      if (activeStage && !activeStage.output) {
        processingStage.value = activeStage.id
      }
    }
    if (task.value?.status === 'done' || task.value?.currentStageId === 'done') {
      autoRunning.value = false
      smartRunning.value = false
      stageRunning.value = false
    }
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '加载任务失败'
    console.error('加载任务失败:', e)
  }
}

onMounted(() => {
  loadTask().then(() => loadQualityReport())
  setupSSE()
})

onUnmounted(() => {
  unsubSSE?.()
})

watch(() => route.params.id, () => {
  loadTask()
  stageLogs.value = []
  processingStage.value = null
})
</script>

<style scoped>
.task-detail {
  padding: 32px;
  max-width: 960px;
  margin: 0 auto;
}

.detail-header { margin-bottom: 32px; }

.header-breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.back-link {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--accent);
  text-decoration: none;
}
.back-link:hover { text-decoration: underline; }

.separator { color: var(--border-color); }
.task-id { font-family: monospace; }

.header-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.header-main h1 {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}

.header-tags { display: flex; gap: 8px; }

.task-description {
  color: var(--text-secondary);
  margin-top: 8px;
  line-height: 1.6;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
  display: flex;
  align-items: center;
}

.stage-progress { margin-bottom: 32px; }

.stage-timeline {
  display: flex;
  flex-direction: column;
  position: relative;
}

.timeline-item {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 12px 0;
  position: relative;
  border-radius: 8px;
  transition: background-color 0.4s ease;
}
/* Triggered by scrollToStage() when the user clicks a node on the DAG canvas.
 * 1.2s soft flash so they can see exactly where the canvas landed them. */
.timeline-item.flash-highlight {
  background-color: rgba(56, 189, 248, 0.12);
  box-shadow: inset 3px 0 0 #38bdf8;
}

.timeline-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  background: var(--bg-tertiary);
  border: 2px solid var(--border-color);
  color: var(--text-muted);
  z-index: 1;
}

.timeline-item.status-done .timeline-dot {
  background: #22c55e;
  border-color: #22c55e;
  color: #fff;
}

.timeline-item.status-active .timeline-dot {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  animation: pulse 2s infinite;
}

.timeline-item.processing .timeline-dot {
  background: #f59e0b;
  border-color: #f59e0b;
  color: #fff;
  animation: none;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.3);
}

.timeline-item.current .timeline-dot {
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.2);
}

.timeline-connector {
  position: absolute;
  left: 13px;
  top: 40px;
  bottom: -12px;
  width: 2px;
  background: var(--border-color);
}

.timeline-item.status-reviewing .timeline-dot {
  background: #f59e0b;
  border-color: #f59e0b;
  color: #fff;
  animation: pulse 2s infinite;
}
.timeline-item.status-rejected .timeline-dot {
  background: #ef4444;
  border-color: #ef4444;
  color: #fff;
}
.timeline-item.status-awaiting_approval .timeline-dot {
  background: #f97316;
  border-color: #f97316;
  color: #fff;
  animation: pulse 2s infinite;
}

.reviewer-info {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 400;
}
.attempt-badge {
  font-size: 10px;
  color: #f59e0b;
  margin-left: 4px;
}

.review-feedback {
  margin-top: 8px;
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 8px;
  overflow: hidden;
}
.feedback-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.08);
}
.feedback-header:hover {
  background: rgba(245, 158, 11, 0.15);
}
.feedback-body {
  padding: 12px;
  font-size: 13px;
  border-top: 1px solid rgba(245, 158, 11, 0.2);
  max-height: 400px;
  overflow-y: auto;
}

.approval-actions {
  margin-top: 10px;
  padding: 12px;
  background: rgba(249, 115, 22, 0.08);
  border: 1px solid rgba(249, 115, 22, 0.3);
  border-radius: 8px;
}
.approval-hint {
  font-size: 12px;
  color: #f97316;
  margin: 0 0 8px;
}
.approval-btns {
  display: flex;
  gap: 8px;
}

.timeline-item.status-done .timeline-connector {
  background: #22c55e;
}

.timeline-content { flex: 1; }

.stage-label-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stage-label {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 14px;
}

.processing-tag {
  animation: blink 1.5s infinite;
}

.stage-role {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.stage-time {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.duration {
  color: var(--accent);
  font-weight: 500;
}

.stage-output-preview {
  margin-top: 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.output-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  color: var(--accent);
  background: var(--bg-secondary);
  transition: background 0.2s;
}
.output-header:hover {
  background: var(--bg-tertiary);
}

.toggle-icon {
  margin-left: auto;
  transition: transform 0.2s;
}
.toggle-icon.expanded {
  transform: rotate(180deg);
}

.output-body {
  padding: 12px 16px;
  background: var(--bg-tertiary);
  max-height: 400px;
  overflow-y: auto;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.output-content-md :deep(h2) { font-size: 16px; font-weight: 700; margin: 12px 0 8px; color: var(--text-primary); }
.output-content-md :deep(h3) { font-size: 14px; font-weight: 600; margin: 10px 0 6px; color: var(--text-primary); }
.output-content-md :deep(h4) { font-size: 13px; font-weight: 600; margin: 8px 0 4px; color: var(--text-primary); }
.output-content-md :deep(strong) { color: var(--text-primary); }
.output-content-md :deep(code) {
  background: rgba(99, 102, 241, 0.15);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
}
.output-content-md :deep(li) {
  margin-left: 16px;
  margin-bottom: 2px;
  list-style: disc;
}

.task-actions { margin-bottom: 32px; }

.paused-info {
  padding: 16px;
  background: rgba(249, 115, 22, 0.08);
  border: 1px solid rgba(249, 115, 22, 0.3);
  border-radius: 10px;
}
.paused-info p {
  font-size: 13px;
  color: #f97316;
  margin: 0 0 12px;
}

.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.live-log { margin-bottom: 32px; }

.log-container {
  background: #0d1117;
  border-radius: 10px;
  padding: 12px;
  max-height: 300px;
  overflow-y: auto;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
}

.log-entry {
  display: flex;
  gap: 10px;
  padding: 3px 0;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}

.log-time {
  color: #6b7280;
  flex-shrink: 0;
  width: 70px;
}

.log-event {
  color: #a5b4fc;
  flex-shrink: 0;
  min-width: 100px;
}

.log-detail {
  color: #9ca3af;
  word-break: break-all;
}

.log-entry.stage\:error .log-event,
.log-entry.pipeline\:auto-error .log-event {
  color: #ef4444;
}

.log-entry.stage\:completed .log-event,
.log-entry.pipeline\:auto-completed .log-event {
  color: #22c55e;
}

.subtask-tracking {
  margin-bottom: 24px;
  padding: 16px;
  background: linear-gradient(135deg, #f8f9ff 0%, #f0f7ff 100%);
  border-radius: 12px;
  border: 1px solid #d9ecff;
}
.subtask-tracking .section-title {
  display: flex;
  align-items: center;
  gap: 4px;
}
.subtask-tracking .icon-brain { font-size: 20px; }
.subtask-list { margin-top: 12px; }

.task-artifacts { margin-bottom: 32px; }

.artifacts-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.artifact-upload-inline {
  flex-shrink: 0;
}

.artifact-empty-hint {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.5;
  margin-bottom: 8px;
}

.artifact-file-meta {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.text-muted-inline {
  font-size: 12px;
  color: var(--text-muted);
}

.artifact-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.artifact-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  overflow: hidden;
}

.artifact-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-color);
}

.artifact-name {
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.artifact-body {
  padding: 12px 14px;
}

.artifact-content-preview {
  background: var(--bg-tertiary);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  color: var(--text-secondary);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 120px;
  overflow-y: auto;
}

.artifact-content-full {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
  max-height: 500px;
  overflow-y: auto;
}

.artifact-content-full :deep(h2) { font-size: 16px; font-weight: 700; margin: 12px 0 8px; color: var(--text-primary); }
.artifact-content-full :deep(h3) { font-size: 14px; font-weight: 600; margin: 10px 0 6px; color: var(--text-primary); }
.artifact-content-full :deep(h4) { font-size: 13px; font-weight: 600; margin: 8px 0 4px; color: var(--text-primary); }
.artifact-content-full :deep(strong) { color: var(--text-primary); }
.artifact-content-full :deep(code) {
  background: rgba(99, 102, 241, 0.15);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
}
.artifact-content-full :deep(li) {
  margin-left: 16px;
  margin-bottom: 2px;
  list-style: disc;
}

.artifact-toggle {
  width: 100%;
  border-top: 1px solid var(--border-color);
  border-radius: 0;
}

.task-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 60vh;
  color: var(--text-muted);
}

.loading-icon { animation: spin 1s linear infinite; }
.spin-icon { animation: spin 1s linear infinite; }

@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

/* Deliverable section */
.deliverable-section {
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
}
.deliverable-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.deliverable-actions { display: flex; gap: 8px; }
.compiled-preview {
  background: var(--bg-primary, #fff);
  border-radius: 8px;
  padding: 16px 20px;
  max-height: 600px;
  overflow-y: auto;
  line-height: 1.7;
  font-size: 14px;
}
.compiled-preview h1 { font-size: 20px; margin-bottom: 12px; }
.compiled-preview h2 { font-size: 16px; margin-top: 16px; margin-bottom: 8px; }
.compiled-preview table { width: 100%; border-collapse: collapse; margin: 12px 0; }
.compiled-preview th, .compiled-preview td {
  border: 1px solid var(--border-color, #e4e7ed);
  padding: 6px 10px;
  text-align: left;
  font-size: 13px;
}
.compiled-preview th { background: var(--bg-tertiary, #eef1f6); font-weight: 600; }

/* Quality badge per stage */
.verify-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}
.verify-badge.pass { background: #dcfce7; color: #166534; }
.verify-badge.warn { background: #fef3c7; color: #92400e; }
.verify-badge.fail { background: #fecaca; color: #991b1b; }

.quality-score {
  font-size: 11px;
  color: var(--text-muted, #909399);
  margin-left: 6px;
}

/* Quality summary bar */
.quality-summary {
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 20px;
}
.quality-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.quality-label { font-weight: 600; font-size: 14px; }
.quality-pills { display: flex; gap: 8px; }
.quality-pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}
.quality-pill.pass { background: #dcfce7; color: #166534; }
.quality-pill.warn { background: #fef3c7; color: #92400e; }
.quality-pill.fail { background: #fecaca; color: #991b1b; }
.quality-avg { font-size: 13px; color: var(--text-muted, #909399); margin-left: auto; }

.task-meta-row { margin-top: 6px; }

/* Quality Gate badges */
.gate-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}
.gate-passed { background: #dcfce7; color: #166534; }
.gate-warning { background: #fef3c7; color: #92400e; }
.gate-failed { background: #fecaca; color: #991b1b; }
.gate-bypassed { background: #e0e7ff; color: #3730a3; }
.gate-pending { background: #f3f4f6; color: #6b7280; }

.gate-score {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  margin-left: 4px;
}

/* Gate detail panel */
.gate-detail-panel {
  margin-top: 8px;
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  overflow: hidden;
}
.gate-detail-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.06);
}
.gate-detail-header:hover { background: rgba(239, 68, 68, 0.12); }
.gate-detail-body {
  padding: 12px;
  font-size: 13px;
  border-top: 1px solid rgba(239, 68, 68, 0.15);
}
.gate-block-reason {
  color: #991b1b;
  margin-bottom: 10px;
  padding: 6px 10px;
  background: rgba(239, 68, 68, 0.05);
  border-radius: 6px;
  font-size: 12px;
}
.gate-checks {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}
.gate-check-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
  background: var(--bg-tertiary);
}
.gate-check-icon { font-size: 14px; flex-shrink: 0; }
.gate-check-name { font-weight: 600; color: var(--text-secondary); min-width: 100px; }
.gate-check-score { font-weight: 600; color: var(--accent); min-width: 40px; }
.gate-check-msg { color: var(--text-muted); flex: 1; }
.gate-suggestions {
  margin-bottom: 10px;
}
.gate-suggestion {
  font-size: 12px;
  color: #92400e;
  margin: 2px 0;
  padding-left: 12px;
  border-left: 2px solid #f59e0b;
}
.gate-override-action {
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

/* Gate override info */
.gate-override-info {
  margin-top: 6px;
  font-size: 11px;
  color: #3730a3;
  display: flex;
  align-items: center;
  gap: 6px;
}
.override-badge {
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
  background: #e0e7ff;
}
.override-by { color: var(--text-muted); }
.override-reason { color: var(--text-secondary); font-style: italic; }

/* Quality Report Section */
.quality-report-section {
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
}
.qr-summary {
  display: flex;
  gap: 24px;
  margin-bottom: 16px;
}
.qr-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.qr-stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--accent);
}
.qr-stat-label {
  font-size: 12px;
  color: var(--text-muted);
}
.qr-stages {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.qr-stage-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 6px;
  background: var(--bg-tertiary);
}
.qr-stage-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  min-width: 100px;
}
.qr-gate-icon { font-size: 14px; }
.qr-score-bar {
  flex: 1;
  height: 6px;
  background: var(--border-color, #e4e7ed);
  border-radius: 3px;
  overflow: hidden;
}
.qr-score-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}
.qr-score-fill.passed { background: #22c55e; }
.qr-score-fill.warning { background: #f59e0b; }
.qr-score-fill.failed { background: #ef4444; }
.qr-score-fill.bypassed { background: #6366f1; }
.qr-score-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  min-width: 40px;
  text-align: right;
}
.qr-threshold {
  font-size: 11px;
  color: var(--text-muted);
  min-width: 70px;
}
.rca-loading,
.rca-empty {
  text-align: center;
  padding: 32px 12px;
  color: var(--text-muted);
}
.rca-report h3 {
  margin: 14px 0 6px;
  font-size: 14px;
  color: var(--text-secondary);
}
.rca-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-muted);
}
.rca-summary {
  font-size: 14px;
  line-height: 1.6;
  margin: 0;
}
.rca-block,
.rca-evidence {
  background: var(--card-bg, #1c1c20);
  color: var(--text-primary);
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow: auto;
}
.rca-stage {
  margin: 6px 0;
  padding: 6px 8px;
  background: var(--card-bg, #1c1c20);
  border-radius: 4px;
  font-size: 12px;
}
.rca-stage pre {
  margin: 4px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #ff7875;
}
.rca-details {
  margin-top: 14px;
}
.rca-details > summary {
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  color: var(--text-secondary);
}
.rca-warn {
  margin-top: 12px;
  padding: 8px 10px;
  background: rgba(255, 196, 0, 0.08);
  color: #ffd666;
  border-radius: 4px;
  font-size: 12px;
}
</style>
