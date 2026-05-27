<template>
  <div class="Agent-stack-page">
    <header class="page-header">
      <div>
        <h1>{{ t('AgentStack.text_1') }}</h1>
        <p class="subtitle">
          以 Claude Code {{ $t('WayneStack.execHub') }}、Cursor {{ $t('WayneStack.cockpit') }}、Opus/Sonnet/GPT/Gemini {{ $t('WayneStack.multiModel') }}。
        </p>
      </div>
      <div class="header-badges">
        <el-tag type="success" effect="dark">{{ t('AgentStack.text_2') }}</el-tag>
        <el-tag type="info">{{ t('AgentStack.text_3') }}</el-tag>
        <el-tag type="warning">{{ t('AgentStack.text_4') }}</el-tag>
      </div>
    </header>

    <el-alert class="summary-alert" type="info" :closable="false" show-icon>
      <template #title>{{ $t('WayneStack.oneSentence') }}</template>
      {{ $t('WayneStack.summary') }}
    </el-alert>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneStack.section1Title') }}</h2>
        <p>{{ $t('WayneStack.section1Desc') }}</p>
      </div>

      <div class="model-grid">
        <el-card v-for="model in modelRoles" :key="model.name" class="model-card" shadow="hover">
          <template #header>
            <div class="model-head">
              <div>
                <div class="model-name">{{ model.name }}</div>
                <div class="model-role">{{ model.role }}</div>
              </div>
              <el-tag :type="model.tagType">{{ model.tag }}</el-tag>
            </div>
          </template>
          <ul class="model-list">
            <li v-for="item in model.items" :key="item">{{ item }}</li>
          </ul>
        </el-card>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneStack.section2Title') }}</h2>
        <p>{{ $t('WayneStack.section2Desc') }}</p>
      </div>

      <div class="architecture-stack">
        <div v-for="layer in architectureLayers" :key="layer.title" class="layer-card">
          <div class="layer-top">
            <span class="layer-index">{{ layer.index }}</span>
            <div>
              <h3>{{ layer.title }}</h3>
              <p>{{ layer.summary }}</p>
            </div>
          </div>
          <div class="layer-points">
            <span v-for="point in layer.points" :key="point" class="chip">{{ point }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneStack.section3Title') }}</h2>
        <p>{{ $t('WayneStack.section3Desc') }}</p>
      </div>

      <el-table :data="commandRoutes" stripe class="route-table">
        <el-table-column prop="command" :label="$t('WayneStack.colCommand')" width="160" />
        <el-table-column prop="lead" :label="$t('WayneStack.colLead')" width="120" />
        <el-table-column prop="review" :label="$t('WayneStack.colReview')" min-width="180" />
        <el-table-column prop="output" :label="$t('WayneStack.colOutput')" min-width="220" />
      </el-table>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneStack.section4Title') }}</h2>
        <p>{{ $t('WayneStack.section4Desc') }}</p>
      </div>

      <div class="flow-grid">
        <div v-for="step in executionFlow" :key="step.title" class="flow-card">
          <div class="flow-step">{{ step.step }}</div>
          <h3>{{ step.title }}</h3>
          <p class="flow-owner">{{ step.owner }}</p>
          <p class="flow-desc">{{ step.description }}</p>
          <div class="layer-points">
            <span v-for="artifact in step.artifacts" :key="artifact" class="chip chip-accent">{{ artifact }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneStack.section5Title') }}</h2>
        <p>{{ $t('WayneStack.section5Desc') }}</p>
      </div>

      <div class="mvp-grid">
        <el-card class="mvp-card">
          <template #header>{{ $t('WayneStack.mvpRoles') }}</template>
          <ul class="plain-list">
            <li>`Agent-orchestrator`</li>
            <li>`Agent-product-manager`</li>
            <li>`Agent-developer`</li>
            <li>`Agent-qa-lead`</li>
          </ul>
        </el-card>

        <el-card class="mvp-card">
          <template #header>{{ $t('WayneStack.mvpCommands') }}</template>
          <ul class="plain-list">
            <li>`/Agent-prd`</li>
            <li>`/Agent-build`</li>
            <li>`/Agent-qa`</li>
            <li>`/Agent-retro`</li>
          </ul>
        </el-card>

        <el-card class="mvp-card">
          <template #header>{{ $t('WayneStack.mvpDocs') }}</template>
          <ul class="plain-list">
            <li>`docs/delivery/01-prd.md`</li>
            <li>`docs/delivery/04-implementation-notes.md`</li>
            <li>`docs/delivery/05-test-report.md`</li>
            <li>`docs/memory/decisions.md`</li>
          </ul>
        </el-card>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneStack.section6Title') }}</h2>
        <p>{{ $t('WayneStack.section6Desc') }}</p>
      </div>

      <div class="mode-grid">
        <el-card v-for="mode in executionModes" :key="mode.name" class="mode-card" shadow="hover">
          <template #header>
            <div class="mode-head">
              <span class="mode-name">{{ mode.name }}</span>
              <el-tag size="small" :type="mode.tagType">{{ mode.short }}</el-tag>
            </div>
          </template>
          <p class="mode-desc">{{ mode.description }}</p>
          <ul class="plain-list">
            <li v-for="step in mode.steps" :key="step">{{ step }}</li>
          </ul>
        </el-card>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneStack.section7Title') }}</h2>
        <p>{{ $t('WayneStack.section7Desc') }}</p>
      </div>

      <div class="agent-entry-grid">
        <div
          v-for="entry in AgentAgents"
          :key="entry.id"
          class="entry-card"
          @click="goAgent(entry.id)"
        >
          <div class="entry-icon" :style="{ background: `${entry.color}18`, color: entry.color }">
            <el-icon :size="24"><component :is="entry.icon" /></el-icon>
          </div>
          <div class="entry-body">
            <div class="entry-top">
              <h3>{{ entry.name }}</h3>
              <el-tag size="small" effect="plain">{{ entry.title }}</el-tag>
            </div>
            <div class="entry-recommended-model">{{ entry.recommendedModel }}</div>
            <p>{{ entry.description }}</p>
            <span class="entry-link">{{ $t('WayneStack.goChat') }}</span>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

type Layer = {
  index: string
  title: string
  summary: string
  points: string[]
}

type ModelRole = {
  name: string
  role: string
  tag: string
  tagType: 'primary' | 'success' | 'warning' | 'info'
  items: string[]
}

type ExecutionMode = {
  name: string
  short: string
  description: string
  tagType: 'primary' | 'success' | 'warning' | 'info'
  steps: string[]
}

const router = useRouter()

const architectureLayers: Layer[] = [
  {
    index: '01',
    title: t('WayneStack.layer1Title'),
    summary: t('WayneStack.layer1Summary'),
    points: [t('WayneStack.layer1Point1'), t('WayneStack.layer1Point2'), t('WayneStack.layer1Point3'), t('WayneStack.layer1Point4')],
  },
  {
    index: '02',
    title: t('WayneStack.layer2Title'),
    summary: t('WayneStack.layer2Summary'),
    points: ['commands', 'plugins', 'hooks', 'MCP'],
  },
  {
    index: '03',
    title: t('WayneStack.layer3Title'),
    summary: t('WayneStack.layer3Summary'),
    points: ['Opus 4.6', 'Sonnet 4.6', 'GPT-4.5', 'Gemini 4', 'GLM-4.5'],
  },
  {
    index: '04',
    title: t('WayneStack.layer4Title'),
    summary: t('WayneStack.layer4Summary'),
    points: ['CEO', 'Product', 'Developer', 'QA', 'PRD', 'Test'],
  },
  {
    index: '05',
    title: t('WayneStack.layer5Title'),
    summary: t('WayneStack.layer5Summary'),
    points: ['code', 'docs', 'tests', 'decisions', 'agent diaries'],
  },
]

const modelRoles: ModelRole[] = [
  {
    name: t('WayneStack.modelOpus'),
    role: t('WayneStack.modelOpusRole'),
    tag: t('WayneStack.tagJudgment'),
    tagType: 'warning',
    items: [t('WayneStack.modelOpusItem1'), t('WayneStack.modelOpusItem2'), t('WayneStack.modelOpusItem3'), t('WayneStack.modelOpusItem4'), t('WayneStack.modelOpusItem5')],
  },
  {
    name: t('WayneStack.modelSonnet'),
    role: t('WayneStack.modelSonnetRole'),
    tag: t('WayneStack.tagExecution'),
    tagType: 'success',
    items: [t('WayneStack.modelSonnetItem1'), t('WayneStack.modelSonnetItem2'), t('WayneStack.modelSonnetItem3'), t('WayneStack.modelSonnetItem4'), t('WayneStack.modelSonnetItem5')],
  },
  {
    name: t('WayneStack.modelGpt'),
    role: t('WayneStack.modelGptRole'),
    tag: t('WayneStack.tagStructure'),
    tagType: 'primary',
    items: [t('WayneStack.modelGptItem1'), t('WayneStack.modelGptItem2'), t('WayneStack.modelGptItem3'), t('WayneStack.modelGptItem4'), t('WayneStack.modelGptItem5')],
  },
  {
    name: t('WayneStack.modelGemini'),
    role: t('WayneStack.modelGeminiRole'),
    tag: t('WayneStack.tagResearch'),
    tagType: 'info',
    items: [t('WayneStack.modelGeminiItem1'), t('WayneStack.modelGeminiItem2'), t('WayneStack.modelGeminiItem3'), t('WayneStack.modelGeminiItem4'), t('WayneStack.modelGeminiItem5')],
  },
  {
    name: t('WayneStack.modelGlm'),
    role: t('WayneStack.modelGlmRole'),
    tag: t('WayneStack.tagLocalization'),
    tagType: 'success',
    items: [t('WayneStack.modelGlmItem1'), t('WayneStack.modelGlmItem2'), t('WayneStack.modelGlmItem3'), t('WayneStack.modelGlmItem4'), t('WayneStack.modelGlmItem5')],
  },
]

const commandRoutes = [
  {
    command: '/Agent-prd',
    lead: 'GPT-4.5',
    review: t('WayneStack.routePrdReview'),
    output: t('WayneStack.routePrdOutput'),
  },
  {
    command: '/Agent-ui',
    lead: 'GPT-4.5 / Gemini 4',
    review: t('WayneStack.routeUiReview'),
    output: t('WayneStack.routeUiOutput'),
  },
  {
    command: '/Agent-arch',
    lead: 'Opus 4.6',
    review: t('WayneStack.routeArchReview'),
    output: t('WayneStack.routeArchOutput'),
  },
  {
    command: '/Agent-build',
    lead: 'Sonnet 4.6',
    review: t('WayneStack.routeBuildReview'),
    output: t('WayneStack.routeBuildOutput'),
  },
  {
    command: '/Agent-qa',
    lead: 'Gemini 4 / Sonnet 4.6',
    review: t('WayneStack.routeQaReview'),
    output: t('WayneStack.routeQaOutput'),
  },
  {
    command: '/Agent-ship',
    lead: 'Opus 4.6',
    review: t('WayneStack.routeShipReview'),
    output: t('WayneStack.routeShipOutput'),
  },
]

const executionFlow = [
  {
    step: '01',
    title: t('WayneStack.flow1Title'),
    owner: t('WayneStack.flow1Owner'),
    description: t('WayneStack.flow1Desc'),
    artifacts: ['01-prd.md', t('WayneStack.flow1Artifact2'), t('WayneStack.flow1Artifact3')],
  },
  {
    step: '02',
    title: t('WayneStack.flow2Title'),
    owner: t('WayneStack.flow2Owner'),
    description: t('WayneStack.flow2Desc'),
    artifacts: ['03-architecture.md', 'ADR', t('WayneStack.flow2Artifact3')],
  },
  {
    step: '03',
    title: t('WayneStack.flow3Title'),
    owner: t('WayneStack.flow3Owner'),
    description: t('WayneStack.flow3Desc'),
    artifacts: [t('WayneStack.flow3Artifact1'), '04-implementation-notes.md'],
  },
  {
    step: '04',
    title: t('WayneStack.flow4Title'),
    owner: t('WayneStack.flow4Owner'),
    description: t('WayneStack.flow4Desc'),
    artifacts: ['05-test-report.md', t('WayneStack.flow4Artifact2')],
  },
  {
    step: '05',
    title: t('WayneStack.flow5Title'),
    owner: t('WayneStack.flow5Owner'),
    description: t('WayneStack.flow5Desc'),
    artifacts: ['06-acceptance.md', t('WayneStack.flow5Artifact2'), t('WayneStack.flow5Artifact3')],
  },
]

const executionModes: ExecutionMode[] = [
  {
    name: t('WayneStack.modeAName'),
    short: t('WayneStack.modeAShort'),
    description: t('WayneStack.modeADesc'),
    tagType: 'success',
    steps: [t('WayneStack.modeAStep1'), t('WayneStack.modeAStep2'), t('WayneStack.modeAStep3'), t('WayneStack.modeAStep4')],
  },
  {
    name: t('WayneStack.modeBName'),
    short: t('WayneStack.modeBShort'),
    description: t('WayneStack.modeBDesc'),
    tagType: 'warning',
    steps: [t('WayneStack.modeBStep1'), t('WayneStack.modeBStep2'), t('WayneStack.modeBStep3'), t('WayneStack.modeBStep4')],
  },
  {
    name: t('WayneStack.modeCName'),
    short: t('WayneStack.modeCShort'),
    description: t('WayneStack.modeCDesc'),
    tagType: 'info',
    steps: [t('WayneStack.modeCStep1'), t('WayneStack.modeCStep2'), t('WayneStack.modeCStep3'), t('WayneStack.modeCStep4')],
  },
  {
    name: t('WayneStack.modeDName'),
    short: t('WayneStack.modeDShort'),
    description: t('WayneStack.modeDDesc'),
    tagType: 'primary',
    steps: [t('WayneStack.modeDStep1'), t('WayneStack.modeDStep2'), t('WayneStack.modeDStep3'), t('WayneStack.modeDStep4')],
  },
]

const AgentAgents = [
  {
    id: 'Agent-orchestrator',
    name: t('WayneConsole.agentOrchName'),
    title: 'Orchestrator',
    icon: 'Connection',
    color: '#7c5cff',
    description: t('WayneStack.agentOrchestratorDesc'),
    recommendedModel: t('WayneStack.recommendedOpus'),
  },
  {
    id: 'Agent-product-manager',
    name: t('WayneConsole.agentPmName'),
    title: 'Product Manager',
    icon: 'Memo',
    color: '#3b82f6',
    description: t('WayneStack.agentPmDesc'),
    recommendedModel: t('WayneStack.recommendedGpt'),
  },
  {
    id: 'Agent-developer',
    name: t('WayneConsole.agentDevName'),
    title: 'Developer',
    icon: 'Cpu',
    color: '#14b8a6',
    description: t('WayneStack.agentDevDesc'),
    recommendedModel: t('WayneStack.recommendedSonnet'),
  },
  {
    id: 'Agent-qa-lead',
    name: t('WayneConsole.agentQaName'),
    title: 'QA Lead',
    icon: 'CircleCheckFilled',
    color: '#f59e0b',
    description: t('WayneStack.agentQaDesc'),
    recommendedModel: t('WayneStack.recommendedGemini'),
  },
  {
    id: 'Agent-china-strategist',
    name: t('WayneConsole.agentChinaName'),
    title: 'China Strategist',
    icon: 'ChatLineSquare',
    color: '#ef4444',
    description: t('WayneStack.agentChinaDesc'),
    recommendedModel: t('WayneStack.recommendedGlm'),
  },
]

function goAgent(id: string) {
  router.push(`/agent/${id}`)
}
</script>

<style scoped>
.Agent-stack-page {
  padding: 32px 40px 48px;
  max-max-width: 1400px; width: 100%;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 20px;
}

.page-header h1 {
  font-size: 28px;
  font-weight: 800;
  margin-bottom: 8px;
  color: var(--text-primary);
}

.subtitle {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.7;
  max-max-width: 860px; width: 100%;
}

.header-badges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.summary-alert {
  margin-bottom: 24px;
}

.section-block {
  margin-bottom: 28px;
}

.section-heading {
  margin-bottom: 14px;
}

.section-heading h2 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.section-heading p {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.architecture-stack {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px;
}

.layer-card,
.flow-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 18px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
}

.layer-top {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
}

.layer-index,
.flow-step {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, var(--accent), #6ea8ff);
  flex-shrink: 0;
}

.layer-top h3,
.flow-card h3 {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.layer-top p,
.flow-desc {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.layer-points {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
}

.chip-accent {
  color: var(--accent);
}

.model-grid,
.mvp-grid,
.flow-grid,
.mode-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
}

.model-card,
.mvp-card,
.mode-card {
  background: var(--bg-card);
  border-color: var(--border-color);
}

.model-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.mode-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.model-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.mode-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.model-role,
.flow-owner {
  font-size: 12px;
  color: var(--text-muted);
}

.mode-desc {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.model-list,
.plain-list {
  margin: 0;
  padding-left: 18px;
  color: var(--text-secondary);
  line-height: 1.8;
  font-size: 13px;
}

.agent-entry-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}

.entry-card {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 18px;
  border-radius: 16px;
  border: 1px solid var(--border-color);
  background: var(--bg-card);
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.entry-card:hover {
  transform: translateY(-2px);
  border-color: var(--accent);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.18);
}

.entry-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.entry-body {
  min-width: 0;
  flex: 1;
}

.entry-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.entry-top h3 {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.entry-body p {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
  margin-bottom: 10px;
}

.entry-recommended-model {
  display: inline-flex;
  align-items: center;
  margin-bottom: 8px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(124, 92, 255, 0.12);
  border: 1px solid rgba(124, 92, 255, 0.2);
  color: #9f8bff;
  font-size: 12px;
  font-weight: 600;
}

.entry-link {
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
}

.route-table {
  border: 1px solid var(--border-color);
  border-radius: 14px;
  overflow: hidden;
}

@media (max-max-width: 900px; width: 100%) {
  .page-header {
    flex-direction: column;
  }

  .header-badges {
    justify-content: flex-start;
  }

  .Agent-stack-page {
    padding: 24px 20px 36px;
  }
}
</style>
