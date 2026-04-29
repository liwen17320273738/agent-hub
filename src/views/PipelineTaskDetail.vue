<template>
  <div class="task-detail" v-if="task">
    <header class="detail-header">
      <div class="header-breadcrumb">
        <router-link to="/pipeline" class="back-link">
          <el-icon><ArrowLeft /></el-icon>
          {{ t('pipelineTaskDetail.breadCrumb') }}
        </router-link>
        <span class="separator">/</span>
        <span class="task-id">{{ task.id.slice(0, 8) }}</span>
      </div>
      <div class="header-main">
        <h1><AutoTranslated :text="task.title" /></h1>
        <div class="header-tags">
          <el-tag :type="statusTagType" size="default">{{ statusLabel }}</el-tag>
          <el-tag :type="sourceTagType(task.source)" size="small">{{ task.source }}</el-tag>
        </div>
      </div>
      <p v-if="task.description" class="task-description">{{ task.description }}</p>
      <div v-if="task.template || task.repoUrl || task.projectPath" class="task-meta-row">
        <el-tag v-if="task.template" size="small" type="info">{{ t('pipelineTaskDetail.tagTemplate') }}: {{ task.template }}</el-tag>
        <el-tag v-if="task.repoUrl" size="small" type="success">{{ t('pipelineTaskDetail.tagGit') }}: {{ task.repoUrl }}</el-tag>
        <el-tag v-if="task.projectPath" size="small" type="warning">{{ t('pipelineTaskDetail.tagLocal') }}: {{ task.projectPath }}</el-tag>
      </div>
      <div class="header-share">
        <el-button size="small" @click="downloadDeliverables">
          <el-icon><Download /></el-icon> {{ $t('task.download') }}
        </el-button>
        <el-dropdown @command="generateShareLink" trigger="click">
          <el-button size="small">
            <el-icon><Share /></el-icon> {{ $t('task.share') }}
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item :command="7">{{ t('pipelineTaskDetail.text_1') }}</el-dropdown-item>
              <el-dropdown-item :command="30">{{ t('pipelineTaskDetail.text_2') }}</el-dropdown-item>
              <el-dropdown-item :command="365">{{ t('pipelineTaskDetail.text_3') }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <section v-if="task.status === 'plan_pending'" class="plan-pending-banner">
      <div class="plan-pending-inner">
        <div class="plan-pending-text">
          <strong>{{ t('pipelineTaskDetail.planGateTitle') }}</strong>
          <p>{{ t('pipelineTaskDetail.planGateBody') }}</p>
          <p v-if="!task.sourceUserId" class="plan-pending-warn">{{ t('pipelineTaskDetail.planGateNoUserHint') }}</p>
        </div>
        <div class="plan-pending-actions">
          <el-button
            type="success"
            size="large"
            :loading="planGateLoading === 'approve'"
            @click="handlePlanGateApprove"
          >
            <el-icon><Check /></el-icon> {{ t('pipelineTaskDetail.planGateApprove') }}
          </el-button>
          <el-button
            type="danger"
            size="large"
            plain
            :loading="planGateLoading === 'reject'"
            @click="handlePlanGateReject"
          >
            <el-icon><Close /></el-icon> {{ t('pipelineTaskDetail.planGateReject') }}
          </el-button>
        </div>
      </div>
    </section>

    <el-tabs v-model="activeMainTab" class="task-main-tabs">
      <el-tab-pane :label="t('pipelineTaskDetail.tabArtifacts')" name="artifacts">
        <TaskArtifactTabs :task-id="task.id" />
      </el-tab-pane>
      <el-tab-pane :label="t('pipelineTaskDetail.tabOverview')" name="overview" lazy>
    <section v-if="qualitySummary.total > 0" class="quality-summary">
      <div class="quality-bar">
        <span class="quality-label">{{ t('pipelineTaskDetail.qualityLabel') }}</span>
        <div class="quality-pills">
          <span class="quality-pill pass" v-if="qualitySummary.pass">✅ {{ qualitySummary.pass }}</span>
          <span class="quality-pill warn" v-if="qualitySummary.warn">⚠️ {{ qualitySummary.warn }}</span>
          <span class="quality-pill fail" v-if="qualitySummary.fail">❌ {{ qualitySummary.fail }}</span>
        </div>
        <span class="quality-avg" v-if="qualitySummary.avgScore > 0">
          {{ t('pipelineTaskDetail.avgScore') }}: ⭐ {{ qualitySummary.avgScore.toFixed(1) }}
        </span>
      </div>
    </section>

    <!-- Vue Flow must not mount while the tab pane is display:none — zero-size
         viewport causes "Viewport not initialized" and patch DOM errors. -->
    <PipelineDagCanvas
      v-if="task.stages.length && activeMainTab === 'overview'"
      :task="task"
      :processing-stage-id="processingStage"
      @node-click="scrollToStage"
    />

    <section class="stage-progress">
      <h2 class="section-title">{{ t('pipelineTaskDetail.sectionStageProgress') }}</h2>
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
                {{ t('pipelineTaskDetail.tagAiRunning') }}
              </el-tag>
              <el-tag v-if="stage.status === 'reviewing'" size="small" type="warning">
                {{ t('pipelineTaskDetail.tagReviewing') }}
              </el-tag>
              <el-tag v-if="stage.reviewStatus === 'approved'" size="small" type="success" effect="plain">
                {{ t('pipelineTaskDetail.reviewApproved') }}
              </el-tag>
              <el-tag v-if="stage.reviewStatus === 'rejected'" size="small" type="danger" effect="plain">
                {{ t('pipelineTaskDetail.reviewRejected') }}
              </el-tag>
              <el-tag v-if="stage.status === 'awaiting_approval'" size="small" type="danger">
                {{ t('pipelineTaskDetail.tagAwaitingApproval') }}
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
                {{ t('pipelineTaskDetail.reviewerPrefix') }} {{ stage.reviewerAgent }}
                <span v-if="stage.reviewAttempts && stage.reviewAttempts > 1" class="attempt-badge">
                  {{ t('pipelineTaskDetail.reviewRound', { n: stage.reviewAttempts }) }}
                </span>
              </span>
            </div>
            <div v-if="stage.startedAt" class="stage-time">
              {{ t('pipelineTaskDetail.startedAt') }} {{ formatDate(stage.startedAt) }}
            </div>
            <div v-if="stage.completedAt" class="stage-time">
              {{ t('pipelineTaskDetail.completedAt') }} {{ formatDate(stage.completedAt) }}
              <span class="duration" v-if="stage.startedAt">
                ({{ formatDuration(stage.completedAt - stage.startedAt) }})
              </span>
            </div>

            <!-- Review feedback -->
            <div v-if="stage.reviewerFeedback" class="review-feedback">
              <div class="feedback-header" @click="toggleFeedback(stage.id)">
                <el-icon><ChatDotSquare /></el-icon>
                <span>{{ t('pipelineTaskDetail.reviewFeedback') }}</span>
                <el-icon class="toggle-icon" :class="{ expanded: expandedFeedback.has(stage.id) }">
                  <ArrowDown />
                </el-icon>
              </div>
              <div v-if="expandedFeedback.has(stage.id)" class="feedback-body">
                <div class="output-content-md" v-html="renderMarkdown(stage.reviewerFeedback)"></div>
              </div>
            </div>

            <!-- Quality gate panel (rich) -->
            <div
              v-if="stage.gateStatus && stage.gateStatus !== 'pending'"
              class="gate-panel-wrap"
            >
              <div class="gate-panel-header" @click="toggleGateDetail(stage.id)">
                <el-icon><Warning /></el-icon>
                <span>{{ t('pipelineTaskDetail.qualityGateHeader') }}</span>
                <el-tag
                  size="small"
                  :type="gateTagType(stage.gateStatus)"
                  effect="dark"
                >
                  {{ gateLabel(stage.gateStatus) }} · {{ ((stage.gateScore ?? 0) * 100).toFixed(0) }}%
                </el-tag>
                <el-icon class="toggle-icon" :class="{ expanded: expandedGateDetails.has(stage.id) }">
                  <ArrowDown />
                </el-icon>
              </div>
              <QualityGatePanel
                v-if="expandedGateDetails.has(stage.id)"
                :gate-status="stage.gateStatus"
                :gate-score="stage.gateScore"
                :gate-details="stage.gateDetails"
                :overriding="overridingGate === stage.id"
                @override="handleGateOverride(stage.id)"
              />
            </div>

            <!-- Human approval buttons -->
            <div
              v-if="stage.status === 'awaiting_approval' && task.status !== 'plan_pending'"
              class="approval-actions"
              :class="['sla-' + (approvalSLA.get(stage.id)?.level || 'normal')]"
            >
              <p class="approval-hint">
                {{ t('pipelineTaskDetail.approvalHint') }}
                <span
                  v-if="approvalSLA.get(stage.id)"
                  class="sla-pill"
                  :class="'sla-pill-' + approvalSLA.get(stage.id)!.level"
                >
                  {{ approvalSLA.get(stage.id)!.level === 'critical' ? t('pipelineTaskDetail.slaSevere') :
                     approvalSLA.get(stage.id)!.level === 'warn' ? t('pipelineTaskDetail.slaNear') : t('pipelineTaskDetail.slaNormal') }}
                  {{ t('pipelineTaskDetail.elapsedWait', { waited: formatSLAElapsed(approvalSLA.get(stage.id)!.elapsedMs) }) }}
                </span>
              </p>
              <div class="approval-btns">
                <el-button type="success" size="small" @click="handleApproveStage(stage.id, true)" :loading="approvingStage === stage.id">
                  <el-icon><Check /></el-icon> {{ t('pipelineTaskDetail.btnApprove') }}
                </el-button>
                <el-button type="danger" size="small" @click="handleApproveStage(stage.id, false)" :loading="approvingStage === stage.id">
                  <el-icon><Close /></el-icon> {{ t('pipelineTaskDetail.btnReject') }}
                </el-button>
              </div>
            </div>

            <div v-if="stage.output" class="stage-output-preview">
              <div class="output-header" @click="toggleOutput(stage.id)">
                <el-icon><Document /></el-icon>
                <span>{{ t('pipelineTaskDetail.viewOutput') }}</span>
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

    <!-- Subtask tracking (Lead Agent) -->
    <section class="subtask-tracking" v-if="subtasks.length">
      <h2 class="section-title">
        <span class="icon-brain">🧠</span>
        {{ t('pipelineTaskDetail.subtasksTitle') }}
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

    <!--
      Final-acceptance terminus banner.

      Renders at the very top of the action area when the engine has parked
      the task at the human acceptance gate (status="awaiting_final_acceptance"
      from migration c2d3e4f5a6b7). Outranks the paused/failed banners
      because this is the *expected* parking state for a successful run.
    -->
    <section
      class="task-actions final-acceptance-banner"
      v-if="task.status === 'awaiting_final_acceptance'"
    >
      <div class="fab-pulse-bg"></div>
      <h2 class="section-title fab-title">
        <span class="fab-icon">🏁</span>
        {{ t('pipelineTaskDetail.fabTitle') }}
      </h2>
      <div class="fab-info">
        <p class="fab-summary">
          <span>{{ t('pipelineTaskDetail.fabAllDone', { n: task.stages.length }) }}</span>
          <span v-if="task.overallQualityScore != null">
            {{ t('pipelineTaskDetail.fabQuality', { pct: ((task.overallQualityScore ?? 0) * 100).toFixed(0) }) }}
          </span>
          <span>{{ t('pipelineTaskDetail.fabDecide') }}</span>
        </p>
        <div class="action-buttons">
          <el-button type="success" size="large" @click="openFinalAcceptance('accept')">
            <el-icon><Check /></el-icon> {{ t('pipelineTaskDetail.acceptDelivery') }}
          </el-button>
          <el-button type="warning" size="large" @click="openFinalAcceptance('reject')">
            <el-icon><Close /></el-icon> {{ t('pipelineTaskDetail.rejectRedo') }}
          </el-button>
          <el-dropdown @command="generateShareLink" trigger="click">
            <el-button size="large">
              <el-icon><Share /></el-icon> {{ t('pipelineTaskDetail.genShareLink') }}
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :command="7">{{ t('pipelineTaskDetail.text_1') }}</el-dropdown-item>
                <el-dropdown-item :command="30">{{ t('pipelineTaskDetail.text_2') }}</el-dropdown-item>
                <el-dropdown-item :command="365">{{ t('pipelineTaskDetail.text_3') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </section>

    <section class="task-actions" v-else-if="task.status === 'paused'">
      <h2 class="section-title">{{ t('pipelineTaskDetail.pausedTitle') }}</h2>
      <div class="paused-info">
        <p>{{ t('pipelineTaskDetail.pausedBody', { stage: String(task.currentStageId) }) }}</p>
        <div class="action-buttons">
          <el-button type="success" size="large" @click="handleResume(false)" :loading="resuming">
            <el-icon><CaretRight /></el-icon> {{ t('pipelineTaskDetail.btnResumeLinear') }}
          </el-button>
          <el-button type="primary" size="large" @click="handleResumeDag" :loading="resumingDag">
            <el-icon><Refresh /></el-icon> {{ t('pipelineTaskDetail.btnResumeDag') }}
          </el-button>
          <el-button size="large" @click="handleResume(true)" :loading="resuming">
            <el-icon><RefreshRight /></el-icon> {{ t('pipelineTaskDetail.btnForceSkipReview') }}
          </el-button>
        </div>
      </div>
    </section>

    <section class="task-actions" v-else-if="task.status === 'failed'">
      <FailureCard
        :stages="failureStages"
        :rca-summary="rcaSummaryText"
        @retry="handleRetryStage"
        @retry-with-downgrade="handleRetryDowngrade"
        @rollback="handleRollback"
        @escalate="handleEscalate"
      />
      <div class="action-buttons" style="margin-top: 12px;">
        <el-button type="primary" size="large" @click="handleResumeDag" :loading="resumingDag">
          <el-icon><Refresh /></el-icon> {{ t('pipelineTaskDetail.btnFromCheckpoint') }}
        </el-button>
        <el-button size="large" @click="openRcaDialog" :loading="rcaLoading">
          <el-icon><WarningFilled /></el-icon> {{ t('pipelineTaskDetail.btnGenRca') }}
        </el-button>
      </div>
    </section>

    <!--
      Operations area — collapsed from 8 ad-hoc buttons into one
      command-line: a state banner that always tells the user what is
      happening right now, a single primary action that is the right
      thing to click 90% of the time, and a "side actions" dropdown
      that hides power-user escape hatches without removing them.
    -->
    <section class="task-actions" v-if="task.status === 'active'">
      <h2 class="section-title">{{ t('pipelineTaskDetail.sectionOps') }}</h2>

      <div class="exec-banner" :class="execBannerClass">
        <div class="exec-banner-icon">
          <el-icon v-if="isRunningNow" class="spin-icon" :size="22"><Loading /></el-icon>
          <el-icon v-else-if="task.currentStageId === 'done'" :size="22"><Check /></el-icon>
          <el-icon v-else-if="currentStage?.status === 'awaiting_approval'" :size="22"><Bell /></el-icon>
          <el-icon v-else-if="currentStageGateFailed" :size="22"><WarningFilled /></el-icon>
          <el-icon v-else :size="22"><CaretRight /></el-icon>
        </div>
        <div class="exec-banner-text">
          <div class="exec-banner-title">{{ execBannerTitle }}</div>
          <div class="exec-banner-sub">{{ execBannerSub }}</div>
        </div>
        <div class="exec-banner-action">
          <el-button
            v-if="!isRunningNow && task.currentStageId !== 'done' && currentStage?.status !== 'awaiting_approval'"
            :type="currentStageGateFailed ? 'warning' : 'primary'"
            size="large"
            @click="handlePrimaryRun"
            :loading="primaryRunLoading"
          >
            <el-icon><CaretRight /></el-icon>
            {{ primaryRunLabel }}
          </el-button>
          <el-button
            v-else-if="isRunningNow"
            size="large"
            disabled
          >
            {{ t('pipelineTaskDetail.runningCanLeave') }}
          </el-button>
        </div>
      </div>

      <!--
        Inline failure-cause panel: when the current stage's quality gate
        is failing, surface the *exact* reason right under the banner so
        users no longer have to scroll up, find the right stage card,
        and click to expand. Reuses QualityGatePanel — same component,
        same data, just a more useful place to show it.
      -->
      <div v-if="currentStageGateFailed && currentStage" class="exec-gate-detail">
        <div class="exec-gate-header" @click="toggleBannerGate">
          <el-icon><WarningFilled /></el-icon>
          <span>{{ t('pipelineTaskDetail.whyGateNotPass') }}</span>
          <el-tag v-if="currentStage.gateScore != null" size="small" type="danger" effect="plain">
            {{ (currentStage.gateScore * 100).toFixed(0) }}%
          </el-tag>
          <span class="exec-gate-spacer"></span>
          <el-icon class="toggle-icon" :class="{ expanded: bannerGateExpanded }"><ArrowDown /></el-icon>
        </div>
        <div v-if="bannerGateExpanded" class="exec-gate-body">
          <QualityGatePanel
            :gate-status="currentStage.gateStatus"
            :gate-score="currentStage.gateScore"
            :gate-details="currentStage.gateDetails"
            :overriding="overridingGate === currentStage.id"
            @override="handleGateOverride(currentStage.id)"
          />
        </div>
      </div>

      <div class="side-actions">
        <el-dropdown trigger="click" @command="handleSideAction" :disabled="isRunningNow">
          <el-button size="small" plain :disabled="isRunningNow">
            {{ t('pipelineTaskDetail.sideActions') }} <el-icon style="margin-left:4px"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                command="skip"
                :disabled="task.currentStageId === 'done'"
              >
                <el-icon><Right /></el-icon>
                <span style="margin-left:6px">{{ t('pipelineTaskDetail.sideSkip') }}</span>
              </el-dropdown-item>
              <el-dropdown-item
                command="reject"
                :disabled="task.currentStageId === 'planning'"
              >
                <el-icon><Back /></el-icon>
                <span style="margin-left:6px">{{ t('pipelineTaskDetail.sideRollback') }}</span>
              </el-dropdown-item>
              <el-dropdown-item
                command="confirm-build"
                v-if="task.currentStageId === 'development'"
              >
                <el-icon><RefreshRight /></el-icon>
                <span style="margin-left:6px">{{ t('pipelineTaskDetail.sideConfirmBuild') }}</span>
              </el-dropdown-item>
              <el-dropdown-item command="open-agent" divided>
                <el-icon><ChatDotSquare /></el-icon>
                <span style="margin-left:6px">{{ t('pipelineTaskDetail.sideOpenChat') }}</span>
              </el-dropdown-item>
              <el-dropdown-item command="auto-run">
                <el-icon><VideoPlay /></el-icon>
                <span style="margin-left:6px">{{ t('pipelineTaskDetail.sideAutoAll') }}</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <el-button size="small" plain @click="showQualityGateConfig = true">
          <el-icon><Setting /></el-icon>
          <span style="margin-left:4px">{{ t('pipelineTaskDetail.gateThresholdBtn') }}</span>
        </el-button>
      </div>
    </section>

    <section class="live-log" v-if="stageLogs.length">
      <h2 class="section-title">
        {{ t('pipelineTaskDetail.liveLog') }}
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
        {{ t('pipelineTaskDetail.qgReport') }}
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
          <span class="qr-stat-label">{{ t('pipelineTaskDetail.qrEvaluated') }}</span>
        </div>
        <div class="qr-stat">
          <span class="qr-stat-value">{{ (qualityReport.summary.average_score * 100).toFixed(0) }}%</span>
          <span class="qr-stat-label">{{ t('pipelineTaskDetail.qrAverage') }}</span>
        </div>
        <div class="qr-stat" v-if="task.overallQualityScore != null">
          <span class="qr-stat-value">{{ (task.overallQualityScore * 100).toFixed(0) }}%</span>
          <span class="qr-stat-label">{{ t('pipelineTaskDetail.qrTotal') }}</span>
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
          <span class="qr-threshold">{{ t('pipelineTaskDetail.qrThreshold', { pct: (sr.pass_threshold * 100).toFixed(0) }) }}</span>
        </div>
      </div>
    </section>

    <section class="deliverable-section" v-if="task.status === 'done'">
      <div class="deliverable-bar">
        <h2 class="section-title">{{ t('pipelineTaskDetail.projectDelivery') }}</h2>
        <div class="deliverable-actions">
          <el-button type="primary" size="small" @click="handleCompile" :loading="compiling">
            <el-icon><Document /></el-icon>
            {{ t('pipelineTaskDetail.genDoc') }}
          </el-button>
          <el-button
            v-if="compiledContent"
            size="small"
            @click="handleDownload"
          >
            <el-icon><Download /></el-icon>
            {{ t('pipelineTaskDetail.downloadMd') }}
          </el-button>
        </div>
      </div>
      <div v-if="compiledContent" class="compiled-preview" v-html="renderMarkdown(compiledContent)"></div>
    </section>

    <section class="task-artifacts">
      <div class="artifacts-header-row">
        <h2 class="section-title">
          {{ t('pipelineTaskDetail.deliverables') }}
          <el-tag v-if="task.artifacts?.length" size="small" type="info" style="margin-left: 8px">{{ task.artifacts.length }}</el-tag>
        </h2>
        <el-upload
          class="artifact-upload-inline"
          :show-file-list="false"
          :http-request="handleArtifactUpload"
          multiple
        >
          <el-button size="small" type="primary" :loading="uploadingArtifacts">{{ t('pipelineTaskDetail.uploadArtifact') }}</el-button>
        </el-upload>
      </div>
      <p v-if="!task.artifacts?.length" class="artifact-empty-hint">
        {{ t('pipelineTaskDetail.artifactEmpty') }}
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
                <span v-if="artifact.type === 'upload_image'" class="text-muted-inline">{{ t('pipelineTaskDetail.imageSuffix') }}</span>
              </p>
              <el-button size="small" @click="downloadArtifactFile(artifact)">{{ t('pipelineTaskDetail.downloadOriginal') }}</el-button>
            </template>
            <template v-else-if="artifact.content">
              <div
                v-if="expandedArtifacts.has(artifact.id)"
                class="artifact-content-full"
                v-html="renderMarkdown(artifact.content)"
              ></div>
              <pre v-else class="artifact-content-preview">{{ (artifact.content || '').slice(0, 300) }}{{ (artifact.content || '').length > 300 ? '...' : '' }}</pre>
            </template>
            <p v-else class="text-muted-inline">{{ t('pipelineTaskDetail.noTextPreview') }}</p>
          </div>
          <el-button
            v-if="artifact.content && !artifactHasBinary(artifact)"
            text
            size="small"
            @click="toggleArtifact(artifact.id)"
            class="artifact-toggle"
          >
            {{ expandedArtifacts.has(artifact.id) ? t('pipelineTaskDetail.collapse') : t('pipelineTaskDetail.expand') }}
          </el-button>
        </div>
      </div>
    </section>
      </el-tab-pane>

      <el-tab-pane :label="t('pipelineTaskDetail.tabDeliverables')" name="deliverables">
        <DeliverableCards :task-id="task.id" />
      </el-tab-pane>

      <el-tab-pane :label="t('pipelineTaskDetail.tabSwimlane')" name="swimlane">
        <RoleSwimlane :stages="task.stages" />
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="rcaDialog" :title="t('pipelineTaskDetail.rcaDialogTitle')" width="780px" :close-on-click-modal="false">
      <div v-if="rcaLoading" class="rca-loading">
        <el-icon class="loading-icon" :size="32"><Loading /></el-icon>
        <p>{{ t('pipelineTaskDetail.rcaLoading') }}</p>
      </div>
      <div v-else-if="!rcaReport" class="rca-empty">{{ t('pipelineTaskDetail.rcaNoReport') }}</div>
      <div v-else class="rca-report">
        <div class="rca-header">
          <el-tag :type="rcaSeverityType(rcaReport.severity)">{{ rcaReport.severity || 'medium' }}</el-tag>
          <span class="rca-radius" v-if="rcaReport.blast_radius">{{ t('pipelineTaskDetail.rcaBlast') }}{{ rcaReport.blast_radius }}</span>
          <span class="rca-time">{{ t('pipelineTaskDetail.rcaAt', { at: rcaReport.generated_at }) }}</span>
        </div>
        <h3>{{ t('pipelineTaskDetail.rcaHSummary') }}</h3>
        <p class="rca-summary">{{ rcaReport.summary || t('pipelineTaskDetail.rcaNone') }}</p>
        <h3>{{ t('pipelineTaskDetail.rcaHRoot') }}</h3>
        <pre class="rca-block">{{ rcaReport.root_cause || t('pipelineTaskDetail.rcaTbd') }}</pre>
        <h3 v-if="(rcaReport.contributing_factors || []).length">{{ t('pipelineTaskDetail.rcaHFactors') }}</h3>
        <ul v-if="(rcaReport.contributing_factors || []).length">
          <li v-for="(f, i) in rcaReport.contributing_factors" :key="i">{{ f }}</li>
        </ul>
        <h3 v-if="(rcaReport.recommended_actions || []).length">{{ t('pipelineTaskDetail.rcaHActions') }}</h3>
        <ol v-if="(rcaReport.recommended_actions || []).length">
          <li v-for="(a, i) in rcaReport.recommended_actions" :key="i">{{ a }}</li>
        </ol>
        <details class="rca-details">
          <summary>{{ t('pipelineTaskDetail.rcaFailedStages', { n: rcaReport.failed_stages?.length || 0 }) }}</summary>
          <div v-for="(s, idx) in rcaReport.failed_stages" :key="idx" class="rca-stage">
            <strong>{{ s.stage_id }}</strong> · {{ s.owner_role }} · {{ s.status }}
            {{ t('pipelineTaskDetail.rcaRetry', { a: s.retry_count, b: s.max_retries }) }}
            <pre v-if="s.last_error">{{ s.last_error }}</pre>
          </div>
        </details>
        <details class="rca-details" v-if="rcaReport.evidence">
          <summary>{{ t('pipelineTaskDetail.rcaEvidence', { s: rcaReport.spans_examined, a: rcaReport.audits_examined, b: rcaReport.bus_msgs_examined }) }}</summary>
          <pre class="rca-evidence">{{ rcaReport.evidence }}</pre>
        </details>
        <p v-if="rcaReport.llm_error" class="rca-warn">{{ t('pipelineTaskDetail.rcaLlmError') }}{{ rcaReport.llm_error }}</p>
      </div>
      <template #footer>
        <el-button @click="rcaDialog = false">{{ t('pipelineTaskDetail.close') }}</el-button>
        <el-button type="primary" @click="openRcaDialog" :loading="rcaLoading">{{ t('pipelineTaskDetail.rcaRegen') }}</el-button>
      </template>
    </el-dialog>

    <QualityGateConfigDrawer
      v-if="task"
      v-model="showQualityGateConfig"
      :task-id="task.id"
      @saved="loadTask"
    />

    <FinalAcceptanceModal
      v-if="task"
      v-model="showFinalAcceptance"
      :task="task"
      @accepted="loadTask"
      @rejected="loadTask"
    />

    <el-dialog v-model="showRejectDialog" :title="t('pipelineTaskDetail.dialogReject')" width="400px">
      <el-form label-position="top">
        <el-form-item :label="t('pipelineTaskDetail.rejectToStage')">
          <el-select v-model="rejectTarget" style="width: 100%">
            <el-option
              v-for="stage in previousStages"
              :key="stage.id"
              :label="stage.label"
              :value="stage.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('pipelineTaskDetail.rejectReason')">
          <el-input v-model="rejectReason" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRejectDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="warning" @click="handleReject">{{ t('pipelineTaskDetail.confirmReject') }}</el-button>
      </template>
    </el-dialog>
  </div>

  <div v-else-if="loadError" class="task-loading">
    <p class="error-text">{{ loadError }}</p>
    <el-button type="primary" @click="loadTask" style="margin-top: 12px">{{ t('pipelineTaskDetail.btnRetry') }}</el-button>
    <el-button @click="router.push('/pipeline')" style="margin-top: 12px">{{ t('pipelineTaskDetail.backToList') }}</el-button>
  </div>

  <div v-else class="task-loading">
    <el-icon class="loading-icon" :size="32"><Loading /></el-icon>
    <p>{{ t('pipelineTaskDetail.loading') }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AutoTranslated from '@/components/AutoTranslated.vue'
import {
  ArrowDown, ArrowLeft, Back, Bell, CaretRight, Check, Close, CloseBold,
  ChatDotSquare, Document, Download, Loading, Refresh, RefreshRight, Right, Setting, Share, Unlock,
  VideoPlay, View, Warning, WarningFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { usePipelineStore } from '@/stores/pipeline'
import {
  fetchTask, runStage as apiRunStage, autoRunPipeline, resumeAfterBuild,
  smartRunPipeline, subscribePipelineEvents,
  approveStage as apiApproveStage, resumePipeline, resumeDagPipeline, resolvePlanPending,
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
import ArtifactCompletionBar from '@/components/task/ArtifactCompletionBar.vue'
import TaskArtifactTabs from '@/components/task/TaskArtifactTabs.vue'
import FailureCard from '@/components/task/FailureCard.vue'
import DeliverableCards from '@/components/task/DeliverableCards.vue'
import RoleSwimlane from '@/components/task/RoleSwimlane.vue'
import PipelineDagCanvas from '@/components/pipeline/PipelineDagCanvas.vue'
import QualityGateConfigDrawer from '@/components/pipeline/QualityGateConfigDrawer.vue'
import QualityGatePanel from '@/components/pipeline/QualityGatePanel.vue'
import FinalAcceptanceModal from '@/components/pipeline/FinalAcceptanceModal.vue'
import { useApprovalSLA } from '@/composables/useApprovalSLA'
import { useI18n } from 'vue-i18n'
import { appLocaleToBcp47 } from '@/i18n'

const { t, locale } = useI18n()

const route = useRoute()
const router = useRouter()
const pipelineStore = usePipelineStore()

const task = ref<PipelineTask | null>(null)
const loadError = ref('')
const activeMainTab = ref('artifacts')
const planGateLoading = ref<'approve' | 'reject' | null>(null)

async function handlePlanGateApprove() {
  if (!task.value?.id) return
  planGateLoading.value = 'approve'
  try {
    await resolvePlanPending(String(task.value.id), true)
    await loadTask()
    await nextTick()
    ElMessage.success(t('pipelineTaskDetail.planGateApprovedMsg'))
  } catch (e: unknown) {
    await nextTick()
    const msg = e instanceof Error ? e.message : String(e)
    ElMessage.error(msg || t('pipelineTaskDetail.planGateErr'))
  } finally {
    planGateLoading.value = null
  }
}

async function handlePlanGateReject() {
  if (!task.value?.id) return
  planGateLoading.value = 'reject'
  try {
    await resolvePlanPending(String(task.value.id), false)
    await loadTask()
    await nextTick()
    ElMessage.success(t('pipelineTaskDetail.planGateRejectedMsg'))
  } catch (e: unknown) {
    await nextTick()
    const msg = e instanceof Error ? e.message : String(e)
    ElMessage.error(msg || t('pipelineTaskDetail.planGateErr'))
  } finally {
    planGateLoading.value = null
  }
}

// Approval SLA — drives the "stuck for N min" pill and overdue toast.
// onCritical fires once per stage per page session — the user gets one
// loud reminder and we stop being noisy after that.
const { byStage: approvalSLA, formatElapsed: formatSLAElapsed } = useApprovalSLA(
  task,
  {
    warnAfter: 5 * 60 * 1000,
    critAfter: 15 * 60 * 1000,
    onCritical: (stageId, elapsedMs) => {
      const stg = task.value?.stages.find((s) => s.id === stageId)
      const label = stg?.label || stageId
      ElMessage.warning({
        message: t('pipelineTaskDetail.slaMsg', {
          label,
          elapsed: formatSLAElapsed(elapsedMs),
        }),
        duration: 8000,
        showClose: true,
      })
    },
  },
)
const autoRunning = ref(false)
const smartRunning = ref(false)
const stageRunning = ref(false)
const resuming = ref(false)
const resumingDag = ref(false)
const showQualityGateConfig = ref(false)
const showFinalAcceptance = ref(false)
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
  const s = task.value?.status || ''
  if (s === 'active') return t('pipelineTaskDetail.taskStatusActive')
  if (s === 'paused') return t('pipelineTaskDetail.taskStatusPaused')
  if (s === 'done') return t('pipelineTaskDetail.taskStatusDone')
  if (s === 'cancelled') return t('pipelineTaskDetail.taskStatusCancelled')
  return task.value?.status || ''
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
  return String(a.metadata?.mime ?? t('pipelineTaskDetail.unknownMime'))
}

async function handleArtifactUpload(options: UploadRequestOptions) {
  if (!task.value) return
  uploadingArtifacts.value = true
  try {
    await uploadTaskAttachment(task.value.id, options.file as File)
    await loadTask()
    ElMessage.success(t('pipelineTaskDetail.elMessage_32', { name: options.file.name }))
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
    ElMessage.success(t('pipelineTaskDetail.elMessage_1'))
  } catch (e: unknown) {
    ElMessage.error(
      t('pipelineTaskDetail.elMessage_33', { err: e instanceof Error ? e.message : String(e) }),
    )
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

// ──────────────────────────────────────────────────────────────────────────
// Operations area helpers
//
// The page used to expose 8 buttons of equal weight; users had no idea
// which to click first or what would happen. We collapse that into:
//   1. a banner that always describes the live state in plain language,
//   2. a single primary action that auto-picks the right runner, and
//   3. a "side actions" dropdown for the rare escape-hatch flows.
// The computeds below feed that banner and primary button.
// ──────────────────────────────────────────────────────────────────────────
const currentStage = computed(() =>
  task.value?.stages.find(s => s.id === task.value?.currentStageId) ?? null,
)

const primaryRunLoading = computed(() =>
  smartRunning.value || stageRunning.value,
)

// "Is something actually running right now?"
//
// `anyExecutionRunning` only knows about flags WE set when YOU click a
// button in this tab. After a route change / refresh those flags reset
// to false even if the backend is still mid-stage — that is the bug
// that made users think "switching back killed the run".
//
// `processingStage` is set by `loadTask()` whenever a stage is `active`
// without an output yet (heuristic: the engine is mid-flight) and by
// the SSE `stage:processing` event. So OR-ing the two gives us a
// best-effort "is the server busy on this task" that survives nav.
const isRunningNow = computed(() =>
  anyExecutionRunning.value || !!processingStage.value,
)

// Surface a "your last run failed the gate" hint so the banner stops
// looking like the page just stopped for no reason. We only count it
// as "blocked by gate" when the stage isn't currently running anymore.
const currentStageGateFailed = computed(() => {
  const stg = currentStage.value
  if (!stg) return false
  if (isRunningNow.value) return false
  return stg.gateStatus === 'failed'
})

const execBannerClass = computed(() => {
  if (isRunningNow.value) return 'exec-banner-running'
  if (currentStage.value?.status === 'awaiting_approval') return 'exec-banner-warn'
  if (currentStageGateFailed.value) return 'exec-banner-warn'
  if (task.value?.currentStageId === 'done') return 'exec-banner-done'
  return 'exec-banner-idle'
})

const execBannerTitle = computed(() => {
  if (!task.value) return ''
  if (isRunningNow.value) {
    const stg = currentStage.value
    return t('pipelineTaskDetail.execBannerRunning', {
      label: stg?.label ?? task.value.currentStageId,
    })
  }
  if (task.value.currentStageId === 'done') return t('pipelineTaskDetail.execBannerAllDone')
  const stg = currentStage.value
  if (stg?.status === 'awaiting_approval') {
    return t('pipelineTaskDetail.execBannerWaitYou', { label: stg.label })
  }
  if (currentStageGateFailed.value) {
    return t('pipelineTaskDetail.execBannerGateFail', {
      label: stg?.label ?? task.value.currentStageId,
    })
  }
  return t('pipelineTaskDetail.execBannerCurrent', {
    label: stg?.label ?? task.value.currentStageId,
  })
})

const execBannerSub = computed(() => {
  if (anyExecutionRunning.value) {
    return t('pipelineTaskDetail.execSubRunBg')
  }
  if (processingStage.value && !anyExecutionRunning.value) {
    return t('pipelineTaskDetail.execSubMaybeBg')
  }
  if (task.value?.currentStageId === 'done') {
    return t('pipelineTaskDetail.execSubDoneDocs')
  }
  const stg = currentStage.value
  if (!stg) return ''
  if (stg.status === 'awaiting_approval') {
    return t('pipelineTaskDetail.execSubScrollApproval')
  }
  if (currentStageGateFailed.value) {
    const score =
      stg.gateScore != null
        ? `${(stg.gateScore * 100).toFixed(0)}%`
        : t('pipelineTaskDetail.belowThreshold')
    return t('pipelineTaskDetail.execSubGate', { score })
  }
  if (task.value?.currentStageId === 'planning') {
    return t('pipelineTaskDetail.execSubPlan')
  }
  return t('pipelineTaskDetail.execSubOwner', { role: stg.ownerRole })
})

const primaryRunLabel = computed(() => {
  if (!task.value) return t('pipelineTaskDetail.runAi')
  if (task.value.currentStageId === 'planning') return t('pipelineTaskDetail.runSmartLead')
  if (currentStageGateFailed.value) return t('pipelineTaskDetail.runAiRerun')
  return t('pipelineTaskDetail.runThisStage')
})

// Banner-embedded gate-detail panel starts expanded so the user
// immediately sees *why* a stage failed without an extra click. They
// can collapse it manually if they want a cleaner view.
const bannerGateExpanded = ref(true)
function toggleBannerGate() {
  bannerGateExpanded.value = !bannerGateExpanded.value
}

async function handlePrimaryRun() {
  // At planning we have no concrete stage to execute yet, so we route to
  // the smart pipeline runner (Lead Agent decomposes + executes). Once
  // we're inside a real stage, "primary" means "run *this* stage" — the
  // user can still trigger a full auto-run from the side menu.
  if (!task.value) return
  if (task.value.currentStageId === 'planning') {
    await handleSmartRun()
  } else {
    await handleRunCurrentStage()
  }
}

function handleSideAction(cmd: string | number | object) {
  switch (cmd) {
    case 'skip':
      handleAdvance()
      break
    case 'reject':
      showRejectDialog.value = true
      break
    case 'confirm-build':
      handleResume(false)
      break
    case 'open-agent':
      goToAgent()
      break
    case 'auto-run':
      handleAutoRun()
      break
  }
}

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
  return new Date(ts).toLocaleString(appLocaleToBcp47(locale.value), {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatDuration(ms: number) {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}

function formatLogTime(ts: number) {
  return new Date(ts).toLocaleTimeString(appLocaleToBcp47(locale.value), {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatEventName(event: string) {
  switch (event) {
    case 'stage:queued': return t('pipelineTaskDetail.evStageQueued')
    case 'stage:processing': return t('pipelineTaskDetail.evStageProcessing')
    case 'stage:completed': return t('pipelineTaskDetail.evStageCompleted')
    case 'stage:error': return t('pipelineTaskDetail.evStageError')
    case 'task:stage-advanced': return t('pipelineTaskDetail.evTaskStageAdvanced')
    case 'task:created': return t('pipelineTaskDetail.evTaskCreated')
    case 'task:updated': return t('pipelineTaskDetail.evTaskUpdated')
    case 'pipeline:auto-start': return t('pipelineTaskDetail.evPipelineAutoStart')
    case 'pipeline:auto-completed': return t('pipelineTaskDetail.evPipelineAutoCompleted')
    case 'pipeline:awaiting-final-acceptance': return t('pipelineTaskDetail.evPipelineAwaitingFinal')
    case 'pipeline:auto-paused': return t('pipelineTaskDetail.evPipelineAutoPaused')
    case 'pipeline:auto-error': return t('pipelineTaskDetail.evPipelineAutoError')
    case 'pipeline:smart-start': return t('pipelineTaskDetail.evPipelineSmartStart')
    case 'pipeline:smart-completed': return t('pipelineTaskDetail.evPipelineSmartCompleted')
    case 'pipeline:smart-error': return t('pipelineTaskDetail.evPipelineSmartError')
    case 'lead-agent:analyzing': return t('pipelineTaskDetail.evLeadAgentAnalyzing')
    case 'lead-agent:plan-ready': return t('pipelineTaskDetail.evLeadAgentPlanReady')
    case 'lead-agent:error': return t('pipelineTaskDetail.evLeadAgentError')
    case 'subtask:start': return t('pipelineTaskDetail.evSubtaskStart')
    case 'subtask:completed': return t('pipelineTaskDetail.evSubtaskCompleted')
    case 'subtask:failed': return t('pipelineTaskDetail.evSubtaskFailed')
    case 'subtasks:batch-start': return t('pipelineTaskDetail.evSubtasksBatchStart')
    case 'middleware:blocked': return t('pipelineTaskDetail.evMiddlewareBlocked')
    case 'middleware:token-usage': return t('pipelineTaskDetail.evMiddlewareToken')
    case 'executor:started': return t('pipelineTaskDetail.evExecutorStarted')
    case 'executor:launched': return t('pipelineTaskDetail.evExecutorLaunched')
    case 'executor:log': return t('pipelineTaskDetail.evExecutorLog')
    case 'executor:completed': return t('pipelineTaskDetail.evExecutorCompleted')
    case 'executor:error': return t('pipelineTaskDetail.evExecutorError')
    case 'executor:timeout': return t('pipelineTaskDetail.evExecutorTimeout')
    case 'executor:killed': return t('pipelineTaskDetail.evExecutorKilled')
    case 'stage:quality-gate': return t('pipelineTaskDetail.evStageQualityGate')
    case 'stage:gate-overridden': return t('pipelineTaskDetail.evStageGateOverridden')
    case 'stage:peer-reviewing': return t('pipelineTaskDetail.evStagePeerReviewing')
    case 'stage:peer-review-approved': return t('pipelineTaskDetail.evStagePeerApproved')
    case 'stage:peer-review-rejected': return t('pipelineTaskDetail.evStagePeerRejected')
    case 'stage:peer-review-error': return t('pipelineTaskDetail.evStagePeerError')
    case 'stage:rework': return t('pipelineTaskDetail.evStageRework')
    case 'stage:awaiting-approval': return t('pipelineTaskDetail.evStageAwaitingApproval')
    case 'stage:approval-granted': return t('pipelineTaskDetail.evStageApprovalGranted')
    case 'stage:approval-denied': return t('pipelineTaskDetail.evStageApprovalDenied')
    case 'pipeline:resumed': return t('pipelineTaskDetail.evPipelineResumed')
    case 'pipeline:dag-resumed': return t('pipelineTaskDetail.evPipelineDagResumed')
    case 'pipeline:dag-start': return t('pipelineTaskDetail.evPipelineDagStart')
    case 'pipeline:dag-batch': return t('pipelineTaskDetail.evPipelineDagBatch')
    case 'pipeline:dag-completed': return t('pipelineTaskDetail.evPipelineDagCompleted')
    case 'pipeline:dag-branch': return t('pipelineTaskDetail.evPipelineDagBranch')
    case 'pipeline:rollback': return t('pipelineTaskDetail.evPipelineRollback')
    case 'stage:retry': return t('pipelineTaskDetail.evStageRetry')
    case 'stage:skipped': return t('pipelineTaskDetail.evStageSkipped')
    case 'agent:bus-message': return t('pipelineTaskDetail.evAgentBusMessage')
    case 'pipeline:rca-generated': return t('pipelineTaskDetail.evPipelineRcaGenerated')
    case 'learning:override-injected': return t('pipelineTaskDetail.evLearningOverride')
    case 'learning:self-heal-injected': return t('pipelineTaskDetail.evLearningSelfHeal')
    case 'learning:gate-self-heal-injected': return t('pipelineTaskDetail.evLearningGateSelfHeal')
    default: return event
  }
}

function gateIcon(status: string | null | undefined) {
  const icons: Record<string, string> = {
    passed: '🟢', warning: '🟡', failed: '🔴', bypassed: '🔓', pending: '⚪',
  }
  return icons[status || ''] || '⚪'
}

function gateLabel(status: string | null | undefined) {
  switch (status) {
    case 'passed': return t('pipelineTaskDetail.gatePass')
    case 'warning': return t('pipelineTaskDetail.gateWarn')
    case 'failed': return t('pipelineTaskDetail.gateFail')
    case 'bypassed': return t('pipelineTaskDetail.gateBypass')
    case 'pending': return t('pipelineTaskDetail.gatePending')
    default: return ''
  }
}

function gateTagType(status: string | null | undefined): 'success' | 'warning' | 'danger' | 'info' {
  switch (status) {
    case 'passed': return 'success'
    case 'warning': return 'warning'
    case 'failed': return 'danger'
    default: return 'info'
  }
}

function toggleGateDetail(stageId: string) {
  if (expandedGateDetails.has(stageId)) expandedGateDetails.delete(stageId)
  else expandedGateDetails.add(stageId)
}

async function handleGateOverride(stageId: string) {
  if (!task.value) return
  overridingGate.value = stageId
  try {
    await overrideQualityGate(String(task.value.id), stageId, t('pipelineTaskDetail.overrideReason'))
    ElMessage.success(t('pipelineTaskDetail.elMessage_2'))
    await loadTask()
    await resumePipeline(String(task.value.id), undefined, false)
  } catch (e: any) {
    ElMessage.error(e?.message || t('pipelineTaskDetail.elMessage_15'))
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

function toastAfterPaint(kind: 'success' | 'error', text: string) {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (kind === 'success') ElMessage.success(text)
      else ElMessage.error(text)
    })
  })
}

/** Leave overview before heavy DOM refresh — avoids ElTabs + lazy pane + Vue Flow patch races (insertBefore null). */
async function leaveOverviewForStablePatch() {
  if (activeMainTab.value !== 'overview') return
  activeMainTab.value = 'artifacts'
  await nextTick()
}

async function handleApproveStage(stageId: string, approved: boolean) {
  if (!task.value) return
  approvingStage.value = stageId
  const tid = String(task.value.id)
  const wasPlanPending = task.value.status === 'plan_pending'
  try {
    await apiApproveStage(tid, stageId, approved)
    await leaveOverviewForStablePatch()
    await loadTask()
    if (approved && !(wasPlanPending && stageId === 'planning')) {
      await resumePipeline(tid, undefined, false)
    }
    toastAfterPaint(
      'success',
      approved ? t('pipelineTaskDetail.elMessage_12') : t('pipelineTaskDetail.elMessage_13'),
    )
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    const noApproval = /no pending approval|not found|404|http 404/i.test(msg)
    if (noApproval && stageId === 'planning' && wasPlanPending) {
      try {
        await resolvePlanPending(tid, approved)
        await leaveOverviewForStablePatch()
        await loadTask()
        toastAfterPaint(
          'success',
          approved ? t('pipelineTaskDetail.elMessage_12') : t('pipelineTaskDetail.elMessage_13'),
        )
        return
      } catch (e2: unknown) {
        await leaveOverviewForStablePatch()
        toastAfterPaint('error', e2 instanceof Error ? e2.message : String(e2))
        return
      }
    }
    await leaveOverviewForStablePatch()
    toastAfterPaint('error', msg || t('pipelineTaskDetail.elMessage_14'))
  } finally {
    approvingStage.value = null
  }
}

function toggleArtifact(id: string) {
  if (expandedArtifacts.has(id)) expandedArtifacts.delete(id)
  else expandedArtifacts.add(id)
}

function addLog(event: string, data?: Record<string, unknown>) {
  let detail: string | undefined
  if (data?.error) {
    detail = String(data.error)
  } else if (event === 'learning:gate-self-heal-injected') {
    // Make the prompt-injection traceable: tell the user *what* the
    // backend actually fed back into the LLM so they can verify the
    // self-heal loop instead of taking it on faith.
    const attempt = data?.attempt
      ? t('pipelineTaskDetail.addLogRerun', { n: data.attempt as number })
      : ''
    const failing = data?.failingCount
      ? t('pipelineTaskDetail.addLogFailing', { n: data.failingCount as number })
      : ''
    const score = typeof data?.score === 'number'
      ? t('pipelineTaskDetail.addLogLastScore', { pct: String(Math.round((data.score as number) * 100)) })
      : ''
    detail = [attempt, failing, score].filter(Boolean).join(' · ')
  } else if (event === 'learning:self-heal-injected') {
    const attempt = data?.rejectCount
      ? t('pipelineTaskDetail.addLogRework', { n: data.rejectCount as number })
      : ''
    detail = attempt || undefined
  } else if (data?.stageId) {
    detail = t('pipelineTaskDetail.addLogStage', {
      id: String(data.stageId),
      parenthetical: data.label ? ` (${String(data.label)})` : '',
    })
  } else if (data?.from && data?.to) {
    detail = `${data.from} → ${data.to}`
  }

  stageLogs.value.push({
    event,
    timestamp: Date.now(),
    detail,
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

    // Lead Agent subtask tracking (deer-flow style)
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
        st.error = (data?.error as string) || t('pipelineTaskDetail.subtaskExecFail')
        st.endTime = Date.now()
      }
    }
    if (evt.event === 'lead-agent:plan-ready') {
      const plan = data?.plan as Record<string, unknown>
      if (plan?.subtaskCount) {
        addLog('lead-agent:plan-ready', {
          analysis: t('pipelineTaskDetail.leadPlanDecomp', {
            n: plan.subtaskCount as number,
            s: String(plan.strategy ?? ''),
            c: String(plan.complexity ?? ''),
          }),
        })
      }
    }

    if (
      evt.event === 'task:stage-advanced' ||
      evt.event === 'task:updated' ||
      evt.event === 'stage:completed' ||
      evt.event === 'pipeline:auto-completed' ||
      evt.event === 'pipeline:smart-completed' ||
      // Refresh on terminus transitions so the banner appears the moment
      // the engine parks at the human acceptance gate (migration c2d3e4f5a6b7).
      evt.event === 'pipeline:awaiting-final-acceptance'
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
      ElMessage.success(t('pipelineTaskDetail.elMessage_3'))
      loadQualityReport()
    }

    if (evt.event === 'pipeline:awaiting-final-acceptance') {
      // Engine parked at terminus — flip to terminal UX immediately.
      autoRunning.value = false
      stageRunning.value = false
      ElMessage.warning({
        message: t('pipelineTaskDetail.elMessage_16'),
        duration: 6000,
      })
      loadQualityReport()
    }

    if (evt.event === 'pipeline:smart-completed') {
      smartRunning.value = false
      autoRunning.value = false
      stageRunning.value = false
      const completed = (data?.completedSubtasks as number) || 0
      const total = (data?.subtaskCount as number) || 0
      ElMessage.success(t('pipelineTaskDetail.elMessage_17', { ok: completed, total }))
    }

    if (evt.event === 'pipeline:auto-paused') {
      autoRunning.value = false
      ElMessage.info(t('pipelineTaskDetail.elMessage_4'))
    }

    if (evt.event === 'pipeline:auto-error' || evt.event === 'stage:error' || evt.event === 'pipeline:smart-error') {
      autoRunning.value = false
      smartRunning.value = false
      stageRunning.value = false
      ElMessage.error(
        t('pipelineTaskDetail.elMessage_18', { err: String(data?.error || t('pipelineTaskDetail.unknownError')) }),
      )
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
    ElMessage.success(t('pipelineTaskDetail.elMessage_5'))
  } catch (e: unknown) {
    smartRunning.value = false
    ElMessage.error(
      t('pipelineTaskDetail.elMessage_19', { err: e instanceof Error ? e.message : String(e) }),
    )
  }
}

async function handleResume(forceContinue = false) {
  if (!task.value) return
  resuming.value = true
  try {
    const res = await resumePipeline(String(task.value.id), undefined, forceContinue)
    addLog('pipeline:resumed', { fromStage: res.resumed_from })
    ElMessage.success(t('pipelineTaskDetail.elMessage_20', { from: res.resumed_from }))
    await loadTask()
  } catch (e: unknown) {
    ElMessage.error(
      t('pipelineTaskDetail.elMessage_21', { err: e instanceof Error ? e.message : String(e) }),
    )
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

function openFinalAcceptance(initialMode: 'accept' | 'reject') {
  // The modal owns mode reset on open; we set the flag after a microtask
  // so its watcher sees the v-model flip from false → true and reinitialises.
  showFinalAcceptance.value = true
  // Stash desired mode on a global so the modal picks it up. Simple ref
  // would be cleaner but we want zero refactor of the modal's API; it
  // already defaults to 'accept' so the reject case just nudges via DOM.
  if (initialMode === 'reject') {
    void Promise.resolve().then(() => {
      const el = document.querySelector<HTMLElement>('.tab-reject')
      el?.click()
    })
  }
}

async function generateShareLink(ttlDays: number = 7) {
  if (!task.value) return
  try {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    const { getAuthToken } = await import('@/services/api')
    const token = getAuthToken()
    const res = await fetch(`${baseUrl}/share/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ task_id: task.value.id, ttl_days: ttlDays }),
    })
    const data = await res.json()
    if (!res.ok) {
      ElMessage.error(data.detail || t('pipelineTaskDetail.elMessage_shareApi'))
      return
    }
    const fullUrl = `${window.location.origin}/#${data.url}`
    await navigator.clipboard.writeText(fullUrl)
    const ttl =
      ttlDays >= 365
        ? t('pipelineTaskDetail.shareTtlPerm')
        : t('pipelineTaskDetail.shareTtlDays', { n: ttlDays })
    ElMessage.success(t('pipelineTaskDetail.elMessage_22', { ttl }))
  } catch (e: any) {
    ElMessage.error(e.message || t('pipelineTaskDetail.elMessage_23'))
  }
}

const failureStages = computed(() => {
  if (!task.value) return []
  return task.value.stages.map((s: any) => ({
    id: s.id || s.stage_id,
    label: s.label || s.id,
    status: s.status,
    ownerRole: s.ownerRole || s.owner_role || 'agent',
    lastError: s.lastError || s.last_error || '',
    output: s.output || '',
  }))
})
const rcaSummaryText = ref('')

function handleRetryStage(stageId: string) {
  handleResumeDag()
}
function handleRetryDowngrade(stageId: string) {
  ElMessage.info(t('pipelineTaskDetail.elMessage_6'))
  handleResumeDag()
}
function handleRollback(_stageId: string) {
  ElMessage.info(t('pipelineTaskDetail.elMessage_7'))
}
function handleEscalate(_stageId: string) {
  ElMessage.info(t('pipelineTaskDetail.elMessage_8'))
}

function downloadDeliverables() {
  if (!task.value) return
  const baseUrl = import.meta.env.VITE_API_BASE || '/api'
  const token = localStorage.getItem('auth_token') || ''
  window.open(`${baseUrl.replace('/api', '')}/api/tasks/${task.value.id}/deliverables.zip?token=${token}`, '_blank')
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
    ElMessage.error(
      t('pipelineTaskDetail.elMessage_24', { err: e instanceof Error ? e.message : String(e) }),
    )
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
        t('pipelineTaskDetail.dagQueueFull', {
          tmpl: res.template,
          part: res.resumedFromCheckpoint ? t('pipelineTaskDetail.resDagCp') : t('pipelineTaskDetail.resDagNoCp'),
          tail: t('pipelineTaskDetail.resDagTail'),
        }),
    })
    await loadTask()
  } catch (e: unknown) {
    ElMessage.error(
      t('pipelineTaskDetail.elMessage_26', { err: e instanceof Error ? e.message : String(e) }),
    )
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
    ElMessage.success(t('pipelineTaskDetail.elMessage_9'))
  } catch (e: unknown) {
    autoRunning.value = false
    ElMessage.error(
      t('pipelineTaskDetail.elMessage_27', { err: e instanceof Error ? e.message : String(e) }),
    )
  }
}

async function handleRunCurrentStage() {
  if (!task.value) return
  stageRunning.value = true
  try {
    await apiRunStage(task.value.id)
    addLog('stage:queued', { stageId: task.value.currentStageId })
    ElMessage.success(t('pipelineTaskDetail.elMessage_10'))
  } catch (e: unknown) {
    stageRunning.value = false
    ElMessage.error(
      t('pipelineTaskDetail.elMessage_28', { err: e instanceof Error ? e.message : String(e) }),
    )
  }
}

async function handleAdvance() {
  if (!task.value) return
  try {
    task.value = await pipelineStore.advanceTask(task.value.id)
    addLog('task:stage-advanced', { from: t('pipelineTaskDetail.addLogManual'), to: task.value.currentStageId })
  } catch (e: unknown) {
    ElMessage.error(
      t('pipelineTaskDetail.elMessage_29', { err: e instanceof Error ? e.message : String(e) }),
    )
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
    ElMessage.success(t('pipelineTaskDetail.elMessage_11'))
  } catch (e: unknown) {
    ElMessage.error(
      t('pipelineTaskDetail.elMessage_30', { err: e instanceof Error ? e.message : String(e) }),
    )
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
    loadError.value = e instanceof Error ? e.message : t('pipelineTaskDetail.elMessage_31')
    console.error(t('pipelineTaskDetail.elMessage_31'), e)
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

.plan-pending-banner {
  margin: -8px 0 24px;
  padding: 16px 20px;
  border-radius: 12px;
  border: 1px solid var(--el-color-warning-light-5);
  background: linear-gradient(135deg, rgba(230, 162, 60, 0.1), rgba(230, 162, 60, 0.02));
}
.plan-pending-inner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.plan-pending-text strong {
  display: block;
  font-size: 15px;
  margin-bottom: 8px;
  color: var(--text-primary);
}
.plan-pending-text p {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}
.plan-pending-warn {
  margin-top: 8px !important;
  color: var(--el-color-danger) !important;
}
.plan-pending-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

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
  transition: background 0.3s, border-color 0.3s;
}
.approval-actions.sla-warn {
  background: rgba(245, 158, 11, 0.14);
  border-color: rgba(245, 158, 11, 0.55);
}
.approval-actions.sla-critical {
  background: rgba(239, 68, 68, 0.14);
  border-color: rgba(239, 68, 68, 0.65);
  animation: sla-pulse 2.4s ease-in-out infinite;
}
@keyframes sla-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
  50%      { box-shadow: 0 0 0 6px rgba(239, 68, 68, 0.2); }
}
.approval-hint {
  font-size: 12px;
  color: #f97316;
  margin: 0 0 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sla-pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 600;
  font-family: ui-monospace, monospace;
  background: rgba(148, 163, 184, 0.16);
  color: #cbd5e1;
}
.sla-pill-warn {
  background: rgba(245, 158, 11, 0.18);
  color: #fbbf24;
}
.sla-pill-critical {
  background: rgba(239, 68, 68, 0.22);
  color: #fca5a5;
  animation: sla-pulse 2.4s ease-in-out infinite;
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

/*
  Final-acceptance terminus banner.
  Distinct visual language from "paused" / "failed" — green/teal sheen +
  a soft pulse to draw the eye, since this is the state where we *want*
  the operator to act fast.
*/
.final-acceptance-banner {
  position: relative;
  padding: 20px 24px;
  border-radius: 14px;
  border: 1.5px solid rgba(34, 197, 94, 0.45);
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.10), rgba(56, 189, 248, 0.06));
  overflow: hidden;
}
.fab-pulse-bg {
  position: absolute;
  inset: -40%;
  background: radial-gradient(circle at 30% 30%, rgba(34, 197, 94, 0.22), transparent 60%);
  animation: fab-pulse 4.5s ease-in-out infinite;
  pointer-events: none;
}
@keyframes fab-pulse {
  0%, 100% { transform: scale(1); opacity: 0.55; }
  50%      { transform: scale(1.15); opacity: 0.85; }
}
.fab-title {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #22c55e;
  font-size: 16px;
  margin-bottom: 12px;
  position: relative;
  z-index: 1;
}
.fab-icon {
  font-size: 22px;
  filter: drop-shadow(0 0 6px rgba(34, 197, 94, 0.6));
}
.fab-info {
  position: relative;
  z-index: 1;
}
.fab-summary {
  margin: 0 0 14px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary, #e2e8f0);
}
.fab-summary strong {
  color: #22c55e;
}

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

/*
  Single source of truth for "what is happening right now" on a task.
  Replaces the wall-of-buttons that confused users into back-and-forth
  clicking. The banner stays mounted across runs so the page never goes
  silent after a button click.
*/
.exec-banner {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  border-radius: 10px;
  border: 1px solid var(--border-color, #2c2f36);
  background: var(--bg-elevated, #1a1d23);
  margin-bottom: 12px;
  transition: border-color 0.2s, background 0.2s;
}
.exec-banner-icon {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.04);
}
.exec-banner-text {
  flex: 1;
  min-width: 0;
}
.exec-banner-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 2px;
}
.exec-banner-sub {
  font-size: 12px;
  color: var(--text-secondary, #8a8f99);
  line-height: 1.5;
}
.exec-banner-action { flex-shrink: 0; }

.exec-banner-running {
  border-color: #1989fa;
  background: linear-gradient(90deg, rgba(25, 137, 250, 0.10), rgba(25, 137, 250, 0.02));
}
.exec-banner-running .exec-banner-icon {
  background: rgba(25, 137, 250, 0.18);
  color: #1989fa;
}
.exec-banner-warn {
  border-color: #e6a23c;
  background: linear-gradient(90deg, rgba(230, 162, 60, 0.10), rgba(230, 162, 60, 0.02));
}
.exec-banner-warn .exec-banner-icon {
  background: rgba(230, 162, 60, 0.18);
  color: #e6a23c;
}
.exec-banner-done {
  border-color: #67c23a;
  background: linear-gradient(90deg, rgba(103, 194, 58, 0.10), rgba(103, 194, 58, 0.02));
}
.exec-banner-done .exec-banner-icon {
  background: rgba(103, 194, 58, 0.18);
  color: #67c23a;
}
.exec-banner-idle .exec-banner-icon { color: var(--text-secondary, #8a8f99); }

.side-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/*
  Failure-cause panel embedded right under the banner. We keep it
  visually attached to the warn-state banner (no top border, same
  surrounding margin) so it reads as "here is the answer to the
  warning above" rather than as a standalone section.
*/
.exec-gate-detail {
  border: 1px solid #854d0e;
  border-top: none;
  border-radius: 0 0 10px 10px;
  background: rgba(133, 77, 14, 0.06);
  margin-top: -12px;
  margin-bottom: 12px;
  overflow: hidden;
}
.exec-gate-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  color: #fbbf24;
  font-weight: 600;
}
.exec-gate-header:hover { background: rgba(133, 77, 14, 0.12); }
.exec-gate-spacer { flex: 1; }
.exec-gate-body { padding: 0 16px 14px; }
.exec-gate-detail .toggle-icon {
  transition: transform 0.2s;
}
.exec-gate-detail .toggle-icon.expanded {
  transform: rotate(180deg);
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
.header-share { margin-top: 8px; }

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

/* Gate detail panel — header wraps the new QualityGatePanel component.
   The body styles below (.gate-block-reason etc.) are still used by the
   read-only quality-report section near the bottom of the page, not the
   per-stage panel. */
.gate-panel-wrap {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.gate-panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  background: rgba(148, 163, 184, 0.06);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 6px;
  transition: background 0.15s;
}
.gate-panel-header:hover {
  background: rgba(148, 163, 184, 0.12);
}
.gate-panel-header .toggle-icon {
  margin-left: auto;
  transition: transform 0.2s;
}
.gate-panel-header .toggle-icon.expanded {
  transform: rotate(180deg);
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
