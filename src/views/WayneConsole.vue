<template>
  <div class="wayne-console-page">
    <header class="console-header">
      <div>
        <h1>Wayne Console</h1>
        <p class="subtitle">
          这是 Wayne Stack 在 Agent Hub 里的控制台入口。按阶段点击卡片，系统会把你送到合适的 Wayne agent，并自动带入建议提示词。
        </p>
      </div>
      <div class="console-actions">
        <el-button type="primary" @click="$router.push('/wayne-stack')">查看蓝图</el-button>
      </div>
    </header>

    <el-alert class="console-alert" type="success" :closable="false" show-icon>
      <template #title>推荐使用方式</template>
      先从 `Wayne Stack 总控` 判断当前阶段，再进入产品、开发、QA 对应智能体。这样最接近真正的 Wayne Stack 工作流。
    </el-alert>

    <el-alert class="console-alert" type="warning" :closable="false" show-icon>
      <template #title>当前成本模式：{{ currentCostMode.label }}</template>
      {{ currentCostMode.description }}
    </el-alert>

    <el-card class="settings-card">
      <template #header>
        <div class="scenario-head">
          <span>当前模型档案</span>
          <el-tag type="success" effect="plain">{{ activeProfileName }}</el-tag>
        </div>
      </template>
      <div class="profile-switch-row">
        <el-select v-model="consoleProfileId" class="profile-switch-select" placeholder="切换模型档案">
          <el-option
            v-for="profile in profileOptions"
            :key="profile.id"
            :label="`${profile.name} (${profile.provider || 'unknown'} / ${profile.model || 'no-model'})`"
            :value="profile.id"
          />
        </el-select>
        <el-button type="primary" @click="applyConsoleProfile" :disabled="!consoleProfileId">应用档案</el-button>
      </div>
      <p class="form-tip">在这里可以直接切换当前活动档案，不用再回 Settings 页面。</p>
    </el-card>

    <el-card class="core-model-card-panel">
      <template #header>
        <div class="scenario-head">
          <span>核心模型优先映射</span>
          <el-tag type="warning" effect="dark">前置展示</el-tag>
        </div>
      </template>
      <div class="core-model-panel-grid">
        <div v-for="item in coreModelRoles" :key="item.model" class="core-model-panel-item">
          <div class="core-model-panel-top">
            <strong>{{ item.model }}</strong>
            <el-tag size="small" effect="plain">{{ item.role }}</el-tag>
          </div>
          <p>{{ item.summary }}</p>
        </div>
      </div>
    </el-card>

    <el-card class="workflow-card">
      <template #header>
        <div class="scenario-head">
          <span>Wayne Workflow 状态机</span>
          <el-tag :type="currentWorkflow ? 'success' : 'info'" effect="plain">
            {{ currentWorkflow ? '运行中' : '未启动' }}
          </el-tag>
        </div>
      </template>

      <div class="workflow-form">
        <el-input v-model="workflowForm.title" placeholder="本轮工作流标题，例如：登录与权限重构" />
        <el-input
          v-model="workflowForm.goal"
          type="textarea"
          :rows="3"
          placeholder="本轮工作流目标，例如：完成登录与权限重构，从 PRD 到 QA 形成一条最小闭环。"
        />
        <div class="workflow-actions">
          <el-button type="primary" @click="ensureWorkflowStarted">启动工作流</el-button>
          <el-button @click="syncWorkflowMeta" :disabled="!currentWorkflow">更新工作流</el-button>
          <el-button type="success" plain @click="markCurrentStageDone" :disabled="!currentWorkflow">
            当前阶段完成
          </el-button>
          <el-button type="warning" plain @click="markCurrentStageBlocked" :disabled="!currentWorkflow">
            标记阻塞
          </el-button>
          <el-button text @click="resetWorkflow" :disabled="!currentWorkflow">重置</el-button>
        </div>
      </div>

      <div v-if="currentWorkflow" class="workflow-status">
        <div class="workflow-meta">
          <div>
            <div class="workflow-label">当前标题</div>
            <div class="workflow-value">{{ currentWorkflow.title }}</div>
          </div>
          <div>
            <div class="workflow-label">当前阶段</div>
            <div class="workflow-value">{{ workflowStore.currentStage?.label }}</div>
          </div>
          <div>
            <div class="workflow-label">推荐交付文档</div>
            <div class="workflow-value">{{ currentStageDoc }}</div>
          </div>
        </div>

        <div class="stage-timeline">
          <div
            v-for="stage in orderedStages"
            :key="stage.id"
            class="timeline-stage"
            :class="[`is-${stage.status}`, { current: currentStageId === stage.id }]"
          >
            <div class="timeline-badge">{{ stage.label }}</div>
            <div class="timeline-owner">{{ stage.ownerLabel }}</div>
            <div class="timeline-deliverable">{{ stage.deliverable }}</div>
            <div class="timeline-doc">{{ stage.deliveryDocName }}</div>
          </div>
        </div>

        <div class="handoff-section">
          <div class="section-heading small">
            <h2>最近交接记录</h2>
            <p>每次阶段推进、阻塞或转交都会沉淀在这里。</p>
          </div>
          <div v-if="currentWorkflow.handoffs.length" class="handoff-list">
            <div v-for="item in currentWorkflow.handoffs.slice(0, 6)" :key="item.id" class="handoff-item">
              <div class="handoff-top">
                <span>{{ item.stageId }}</span>
                <el-tag size="small" effect="plain">{{ item.recommendedModel }}</el-tag>
              </div>
              <div class="handoff-route">{{ item.fromAgentId }} -> {{ item.toAgentId }}</div>
              <p>{{ item.note }}</p>
            </div>
          </div>
          <div v-else class="handoff-empty">暂无交接记录，先从「启动工作流」开始。</div>
        </div>
      </div>
    </el-card>

    <section class="section-block">
      <div class="section-heading">
        <h2>一、当前工作流</h2>
        <p>最小可用链路：PRD -> Build -> QA -> Retro。每个卡片都能直接进入对应 agent 聊天并触发预设提示。</p>
      </div>

      <div class="stage-grid">
        <div
          v-for="stage in stages"
          :key="stage.id"
          class="stage-card"
          @click="openWorkflow(stage.agentId, stage.seed, stage.recommendedModel)"
        >
          <div class="stage-top">
            <div class="stage-badge">{{ stage.step }}</div>
            <el-tag size="small" effect="plain">{{ stage.agent }}</el-tag>
          </div>
          <div class="recommended-model">{{ stage.recommendedModel }}</div>
          <h3>{{ stage.title }}</h3>
          <p class="stage-desc">{{ stage.description }}</p>
          <div class="stage-footer">
            <span class="stage-output">{{ stage.output }}</span>
            <span class="launch-link">启动 →</span>
          </div>
        </div>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>二、一键启动场景</h2>
        <p>这是把抽象蓝图变成实际工作流的入口。适合从“我要做什么”快速进入“该找哪个 agent”。</p>
      </div>

      <div class="scenario-grid">
        <el-card v-for="scenario in scenarios" :key="scenario.title" class="scenario-card" shadow="hover">
          <template #header>
            <div class="scenario-head">
              <span>{{ scenario.title }}</span>
              <el-tag size="small" :type="scenario.tagType">{{ scenario.modelMode }}</el-tag>
            </div>
          </template>
          <p class="scenario-desc">{{ scenario.description }}</p>
          <div class="scenario-actions">
            <el-button
              v-for="action in scenario.actions"
              :key="action.label"
              size="small"
              @click="openWorkflow(action.agentId, action.seed, action.recommendedModel)"
            >
              {{ action.label }}
            </el-button>
          </div>
        </el-card>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>三、Wayne Agents</h2>
        <p>这些是当前已经接入 Agent Hub 的 Wayne 核心角色。核心角色排在前面，中文本土化角色也已加入。</p>
      </div>

      <div class="agent-grid">
        <div
          v-for="entry in agents"
          :key="entry.id"
          class="agent-entry"
          @click="openAgent(entry.id, entry.recommendedModel.replace('推荐：', '').trim())"
        >
          <div class="agent-entry-icon" :style="{ background: `${entry.color}18`, color: entry.color }">
            <el-icon :size="22"><component :is="entry.icon" /></el-icon>
          </div>
          <div class="agent-entry-body">
            <div class="agent-entry-top">
              <h3>{{ entry.name }}</h3>
              <el-tag size="small" effect="plain">{{ entry.title }}</el-tag>
            </div>
            <div class="agent-recommended-model">{{ entry.recommendedModel }}</div>
            <div class="agent-bound-profile">
              绑定档案：{{ settingsStore.getRoleBoundProfile(entry.id)?.name || '未绑定（将回退到模型匹配）' }}
            </div>
            <p>{{ entry.description }}</p>
            <div class="agent-bind-row">
              <el-select
                :model-value="roleProfileDrafts[entry.id]"
                class="agent-bind-select"
                placeholder="为该角色绑定默认档案"
                @change="(val) => (roleProfileDrafts[entry.id] = String(val || ''))"
                @click.stop
              >
                <el-option
                  v-for="profile in profileOptions"
                  :key="profile.id"
                  :label="profile.name"
                  :value="profile.id"
                />
              </el-select>
              <el-button size="small" @click.stop="bindRoleProfile(entry.id)">绑定</el-button>
              <el-button size="small" text @click.stop="unbindRoleProfile(entry.id)">清除</el-button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>四、真实交付文档</h2>
        <p>这里直接连接项目内的 `docs/delivery`，你现在编辑和保存的就是实际交付文件，而不是模拟数据。</p>
      </div>

      <el-card class="delivery-card">
        <template #header>
          <div class="scenario-head">
            <span>docs/delivery</span>
            <div class="delivery-actions">
              <el-button
                size="small"
                type="success"
                plain
                :disabled="!currentWorkflow"
                @click="openDeliveryDoc(currentStageDoc)"
              >
                打开当前阶段文档
              </el-button>
              <el-button size="small" @click="initializeDeliveryDocs" :loading="deliveryLoading">
                初始化模板
              </el-button>
              <el-button
                type="primary"
                size="small"
                @click="saveDeliveryDoc"
                :loading="deliverySaving"
                :disabled="!activeDeliveryName"
              >
                保存当前文档
              </el-button>
            </div>
          </div>
        </template>

        <div class="delivery-layout">
          <aside class="delivery-sidebar">
            <div
              v-for="doc in sortedDeliveryDocs"
              :key="doc.name"
              class="delivery-doc-item"
              :class="{ active: doc.name === activeDeliveryName }"
              @click="openDeliveryDoc(doc.name)"
            >
              <div class="delivery-doc-top">
                <strong>{{ doc.title }}</strong>
                <el-tag size="small" effect="plain">{{ doc.name }}</el-tag>
              </div>
              <p>{{ doc.description }}</p>
            </div>
          </aside>

          <div class="delivery-editor">
            <div class="delivery-editor-top">
              <div>
                <h3>{{ activeDeliveryDoc?.title || activeDeliveryName }}</h3>
                <p>{{ activeDeliveryDoc?.description || '请选择一个交付文档开始编辑。' }}</p>
              </div>
            </div>
            <el-input
              v-model="deliveryDraft"
              type="textarea"
              :rows="24"
              resize="none"
              :disabled="deliveryLoading"
            />
          </div>
        </div>
      </el-card>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getWayneCostModeMeta,
  tryApplyRecommendedModel,
} from '@/services/wayneRouting'
import { useWayneWorkflowStore } from '@/stores/wayneWorkflow'
import { WAYNE_STAGE_ORDER } from '@/services/wayneWorkflow'
import { useSettingsStore } from '@/stores/settings'
import {
  initDeliveryDocs,
  listDeliveryDocs,
  readDeliveryDoc,
  writeDeliveryDoc,
  type DeliveryDoc,
  type DeliveryDocMeta,
} from '@/services/deliveryDocs'

const router = useRouter()
const workflowStore = useWayneWorkflowStore()
const settingsStore = useSettingsStore()
const consoleProfileId = ref(settingsStore.activeProfileId)
const roleProfileDrafts = reactive<Record<string, string>>({})
const workflowForm = reactive({
  title: workflowStore.workflow?.title || 'Wayne 新工作流',
  goal: workflowStore.workflow?.goal || '',
})
const deliveryDocs = ref<DeliveryDocMeta[]>([])
const activeDeliveryName = ref('01-prd.md')
const activeDeliveryDoc = ref<DeliveryDoc | null>(null)
const deliveryDraft = ref('')
const deliveryLoading = ref(false)
const deliverySaving = ref(false)

const currentWorkflow = computed(() => workflowStore.workflow)
const currentStageId = computed(() => workflowStore.currentStage?.id || null)
const currentStageDoc = computed(() => workflowStore.currentStage?.deliveryDocName || '01-prd.md')
const currentCostMode = computed(() => getWayneCostModeMeta(settingsStore.settings.wayneCostMode))
const activeProfileName = computed(() => settingsStore.activeProfile?.name || '未命名档案')
const profileOptions = computed(() =>
  settingsStore.profiles.map((profile) => ({
    id: profile.id,
    name: profile.name,
    provider: profile.settings.provider,
    model: profile.settings.model,
  })),
)
const orderedStages = computed(() => {
  const wf = workflowStore.workflow
  if (!wf) return []
  return WAYNE_STAGE_ORDER.map((id) => wf.stages.find((stage) => stage.id === id)).filter(Boolean)
})

const sortedDeliveryDocs = computed(() => deliveryDocs.value)

const stages = [
  {
    id: 'orchestrate',
    step: '01',
    title: '判断当前阶段',
    agent: 'Wayne Stack 总控',
    agentId: 'wayne-orchestrator',
    description: '先让总控判断这是 PRD、开发、QA 还是发布阶段，避免一上来就乱做。',
    output: '阶段判断 / 下一步动作',
    seed: '请判断这个任务现在处于 Wayne Stack 的哪个阶段，并给出下一步最小动作。',
    recommendedModel: 'Opus 4.6',
  },
  {
    id: 'prd',
    step: '02',
    title: '生成 PRD',
    agent: 'Wayne 产品经理',
    agentId: 'wayne-product-manager',
    description: '把模糊需求整理成目标、范围、非目标、用户故事和验收标准。',
    output: '01-prd.md',
    seed: '请把这个想法整理成一版 Wayne Stack PRD，包含目标、范围、非目标、用户故事、验收标准和开放问题。',
    recommendedModel: 'GPT-4.5',
  },
  {
    id: 'build',
    step: '03',
    title: '进入开发',
    agent: 'Wayne 开发工程师',
    agentId: 'wayne-developer',
    description: '根据已确认需求输出最小实现方案、涉及模块、验证方式和潜在风险。',
    output: '实现方案 / 开发任务',
    seed: '根据当前需求，给我一版 Wayne Stack 的最小实现方案，列出涉及模块、改动点、验证方式和风险。',
    recommendedModel: 'Sonnet 4.6',
  },
  {
    id: 'qa',
    step: '04',
    title: '质量验证',
    agent: 'Wayne QA 负责人',
    agentId: 'wayne-qa-lead',
    description: '把验收标准转成 QA 检查清单，并输出 PASS / NEEDS WORK 的判断模板。',
    output: '测试计划 / 风险结论',
    seed: '请基于这项工作生成 Wayne Stack QA 检查清单，重点覆盖主路径、边界、回归风险，并给出 PASS / NEEDS WORK 模板。',
    recommendedModel: 'Gemini 4',
  },
]

const scenarios = [
  {
    title: '新功能从 0 到 1',
    description: '先做需求定义，再做实现与 QA，适合产品和功能起步阶段。',
    modelMode: 'GPT-4.5 -> Sonnet 4.6 -> Gemini 4',
    tagType: 'success' as const,
    actions: [
      {
        label: '先找总控',
        agentId: 'wayne-orchestrator',
        seed: '我要开始一个新功能，请先判断 Wayne Stack 的推进顺序和最小起步动作。',
        recommendedModel: 'Opus 4.6',
      },
      {
        label: '写 PRD',
        agentId: 'wayne-product-manager',
        seed: '把这个新功能整理成一版可以直接开发的 PRD。',
        recommendedModel: 'GPT-4.5',
      },
    ],
  },
  {
    title: '已有需求准备开发',
    description: '你已经想清楚方向，现在需要最小实现方案和开发任务分解。',
    modelMode: 'Sonnet 4.6 主施工',
    tagType: 'primary' as const,
    actions: [
      {
        label: '进入开发',
        agentId: 'wayne-developer',
        seed: '基于当前需求，给我最小可交付实现方案，并拆成开发任务。',
        recommendedModel: 'Sonnet 4.6',
      },
      {
        label: '开发前把关',
        agentId: 'wayne-orchestrator',
        seed: '开发前请检查我还缺哪些上游产物，避免 Wayne Stack 跳阶段。',
        recommendedModel: 'Opus 4.6',
      },
    ],
  },
  {
    title: '功能做完准备上线',
    description: '先做 QA 结论，再回到总控判断是否可以进入 acceptance / release。',
    modelMode: 'Gemini 4 + GPT-4.5 -> Opus 4.6',
    tagType: 'warning' as const,
    actions: [
      {
        label: '跑 QA',
        agentId: 'wayne-qa-lead',
        seed: '请从 Wayne Stack QA 视角检查当前功能，给出风险点和是否建议发布。',
        recommendedModel: 'Gemini 4',
      },
      {
        label: '总控判断',
        agentId: 'wayne-orchestrator',
        seed: '结合当前 QA 结论，判断是否可以进入 Wayne Stack 的发布阶段。',
        recommendedModel: 'Opus 4.6',
      },
    ],
  },
  {
    title: '中文本土化与老板汇报',
    description: '适合把方案、PRD、技术说明转成更自然的中文业务表达。',
    modelMode: 'GLM-4.5 / 中文策略',
    tagType: 'info' as const,
    actions: [
      {
        label: '中文润色',
        agentId: 'wayne-china-strategist',
        seed: '请把当前内容改成更自然、更像中国业务语境的中文表达，并指出原文的 AI 腔问题。',
        recommendedModel: '智谱 GLM-4.5',
      },
      {
        label: '老板汇报版',
        agentId: 'wayne-china-strategist',
        seed: '请把这份内容重写成老板能快速读懂的中文汇报版本，强调目标、风险和下一步。',
        recommendedModel: '智谱 GLM-4.5',
      },
    ],
  },
]

const agents = [
  {
    id: 'wayne-orchestrator',
    name: 'Wayne Stack 总控',
    title: 'Orchestrator',
    icon: 'Connection',
    color: '#7c5cff',
    description: '总控编排、阶段判断、角色路由、阶段门与风险升级。',
    recommendedModel: '推荐：Opus 4.6',
  },
  {
    id: 'wayne-product-manager',
    name: 'Wayne 产品经理',
    title: 'Product Manager',
    icon: 'Memo',
    color: '#3b82f6',
    description: '负责 PRD、范围控制、用户故事与验收标准。',
    recommendedModel: '推荐：GPT-4.5',
  },
  {
    id: 'wayne-developer',
    name: 'Wayne 开发工程师',
    title: 'Developer',
    icon: 'Cpu',
    color: '#14b8a6',
    description: '负责最小可交付实现、修改点、验证方式与偏差说明。',
    recommendedModel: '推荐：Sonnet 4.6',
  },
  {
    id: 'wayne-qa-lead',
    name: 'Wayne QA 负责人',
    title: 'QA Lead',
    icon: 'CircleCheckFilled',
    color: '#f59e0b',
    description: '负责风险验证、测试结论与是否进入下一阶段的建议。',
    recommendedModel: '推荐：Gemini 4',
  },
  {
    id: 'wayne-china-strategist',
    name: 'Wayne 中文策略',
    title: 'China Strategist',
    icon: 'ChatLineSquare',
    color: '#ef4444',
    description: '负责中文自然表达、本土化内容、老板视角汇报和中国市场语境适配。',
    recommendedModel: '推荐：智谱 GLM-4.5',
  },
]

const coreModelRoles = [
  {
    model: 'Opus 4.6',
    role: 'Wayne Stack 总控 / 架构裁决',
    summary: '做复杂权衡、冲突仲裁、架构收口和高风险发布判断。',
  },
  {
    model: 'Sonnet 4.6',
    role: 'Wayne 开发工程师',
    summary: '作为主力施工模型，负责连续编码、修复和仓库级执行。',
  },
  {
    model: 'GPT-4.5',
    role: 'Wayne 产品经理',
    summary: '负责 PRD、结构化输出、需求澄清和对人友好的高质量总结。',
  },
  {
    model: 'Gemini 4',
    role: 'Wayne QA / 研究挑战者',
    summary: '负责长上下文研究、风险挑战、方案对比和 QA 补充视角。',
  },
  {
    model: '智谱 GLM-4.5',
    role: 'Wayne 中文策略 / 本土化',
    summary: '负责中文表达、本土业务语境、本土化内容和老板汇报润色。',
  },
]

async function openAgent(agentId: string, recommendedModel?: string) {
  const matchedProfile =
    settingsStore.getRoleBoundProfile(agentId) ?? findProfileForRecommendedModel(recommendedModel)
  if (matchedProfile) {
    settingsStore.activateProfile(matchedProfile.id)
    consoleProfileId.value = matchedProfile.id
    ElMessage.success(`已切换到档案：${matchedProfile.name}`)
  }
  const result = tryApplyRecommendedModel(recommendedModel)
  if (result.reason) {
    if (result.applied) ElMessage.success(result.reason)
    else ElMessage.warning(result.reason)
  }

  router.push({
    path: `/agent/${agentId}`,
    query: recommendedModel
      ? {
          recommendedModel,
          recommendedApplied: result.applied ? '1' : '0',
        }
      : {},
  })
}

async function openWorkflow(agentId: string, seed: string, recommendedModel?: string) {
  const matchedProfile =
    settingsStore.getRoleBoundProfile(agentId) ?? findProfileForRecommendedModel(recommendedModel)
  if (matchedProfile) {
    settingsStore.activateProfile(matchedProfile.id)
    consoleProfileId.value = matchedProfile.id
    ElMessage.success(`已切换到档案：${matchedProfile.name}`)
  }
  const result = tryApplyRecommendedModel(recommendedModel)
  if (result.reason) {
    if (result.applied) ElMessage.success(result.reason)
    else ElMessage.warning(result.reason)
  }

  router.push({
    path: `/agent/${agentId}`,
    query: {
      autorun: '1',
      seed,
      ...(recommendedModel
        ? {
            recommendedModel,
            recommendedApplied: result.applied ? '1' : '0',
          }
        : {}),
    },
  })
}

function recommendedModelNeedles(label?: string) {
  const text = (label || '').toLowerCase()
  if (text.includes('opus')) return ['claude-opus-4-6', 'opus']
  if (text.includes('sonnet')) return ['claude-sonnet-4-6', 'sonnet']
  if (text.includes('gpt-4.5')) return ['gpt-4.5']
  if (text.includes('gemini')) return ['gemini']
  if (text.includes('glm') || text.includes('智谱')) return ['glm-4.5', 'glm', 'zhipu']
  return [text]
}

function findProfileForRecommendedModel(label?: string) {
  const needles = recommendedModelNeedles(label)
  return settingsStore.profiles.find((profile) => {
    const name = profile.name.toLowerCase()
    const model = (profile.settings.model || '').toLowerCase()
    return needles.some((needle) => needle && (name.includes(needle) || model.includes(needle)))
  })
}

function applyConsoleProfile() {
  if (!consoleProfileId.value) return
  settingsStore.activateProfile(consoleProfileId.value)
  ElMessage.success(`已切换到档案：${settingsStore.activeProfile?.name || ''}`)
}

function bindRoleProfile(agentId: string) {
  const profileId = roleProfileDrafts[agentId]
  if (!profileId) {
    ElMessage.warning('请先选择一个档案')
    return
  }
  const ok = settingsStore.bindRoleProfile(agentId, profileId)
  if (!ok) {
    ElMessage.error('绑定失败')
    return
  }
  ElMessage.success('已绑定默认档案')
}

function unbindRoleProfile(agentId: string) {
  settingsStore.unbindRoleProfile(agentId)
  roleProfileDrafts[agentId] = ''
  ElMessage.success('已清除角色默认档案绑定')
}

for (const entry of agents) {
  roleProfileDrafts[entry.id] = settingsStore.getRoleBoundProfileId(entry.id) || ''
}

function ensureWorkflowStarted() {
  if (workflowStore.hasWorkflow) return true
  if (!workflowForm.goal.trim()) {
    ElMessage.warning('请先填写本轮工作流目标')
    return false
  }
  workflowStore.startWorkflow(workflowForm.title, workflowForm.goal)
  activeDeliveryName.value = currentStageDoc.value
  void openDeliveryDoc(currentStageDoc.value)
  ElMessage.success('Wayne 工作流已启动')
  return true
}

function syncWorkflowMeta() {
  if (!workflowStore.hasWorkflow) return
  workflowStore.updateMetadata({
    title: workflowForm.title,
    goal: workflowForm.goal,
  })
  ElMessage.success('工作流信息已更新')
}

function markCurrentStageDone() {
  if (!workflowStore.hasWorkflow) return
  workflowStore.completeCurrentStage('由 Wayne Console 推进到下一阶段')
  activeDeliveryName.value = currentStageDoc.value
  void openDeliveryDoc(currentStageDoc.value)
  ElMessage.success('已推进到下一阶段')
}

function markCurrentStageBlocked() {
  if (!workflowStore.hasWorkflow) return
  workflowStore.blockCurrentStage('需要 Wayne 人工判断或补齐上游产物')
  ElMessage.warning('当前阶段已标记为阻塞')
}

function resetWorkflow() {
  workflowStore.resetWorkflow()
  workflowForm.title = 'Wayne 新工作流'
  workflowForm.goal = ''
  ElMessage.success('已重置 Wayne 工作流')
}

async function loadDeliveryList() {
  deliveryDocs.value = await listDeliveryDocs()
}

async function openDeliveryDoc(name: string) {
  deliveryLoading.value = true
  try {
    activeDeliveryName.value = name
    activeDeliveryDoc.value = await readDeliveryDoc(name)
    deliveryDraft.value = activeDeliveryDoc.value.content
  } finally {
    deliveryLoading.value = false
  }
}

async function initializeDeliveryDocs() {
  deliveryLoading.value = true
  try {
    deliveryDocs.value = await initDeliveryDocs()
    await openDeliveryDoc(activeDeliveryName.value)
    ElMessage.success('已初始化 docs/delivery 模板')
  } finally {
    deliveryLoading.value = false
  }
}

async function saveDeliveryDoc() {
  if (!activeDeliveryName.value) return
  deliverySaving.value = true
  try {
    activeDeliveryDoc.value = await writeDeliveryDoc(activeDeliveryName.value, deliveryDraft.value)
    await loadDeliveryList()
    ElMessage.success('交付文档已保存到 docs/delivery')
  } finally {
    deliverySaving.value = false
  }
}

onMounted(async () => {
  try {
    await loadDeliveryList()
    activeDeliveryName.value = currentStageDoc.value
    await openDeliveryDoc(activeDeliveryName.value)
  } catch (e) {
    console.error(e)
  }
})
</script>

<style scoped>
.wayne-console-page {
  padding: 32px 40px 48px;
  max-width: 1400px;
  margin: 0 auto;
}

.console-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 20px;
}

.console-header h1 {
  font-size: 28px;
  font-weight: 800;
  margin-bottom: 8px;
  color: var(--text-primary);
}

.subtitle {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.7;
  max-width: 860px;
}

.console-alert {
  margin-bottom: 24px;
}

.profile-switch-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.profile-switch-select {
  width: min(640px, 100%);
}

.core-model-card-panel {
  margin-bottom: 24px;
  background: var(--bg-card);
  border-color: var(--border-color);
}

.workflow-card {
  margin-bottom: 24px;
  background: var(--bg-card);
  border-color: var(--border-color);
}

.core-model-panel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.core-model-panel-item {
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.core-model-panel-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.core-model-panel-item p {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.workflow-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.workflow-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.workflow-status {
  margin-top: 18px;
}

.workflow-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.workflow-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.workflow-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.stage-timeline {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.timeline-stage {
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.timeline-stage.current {
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px rgba(100, 108, 255, 0.3);
}

.timeline-stage.is-done {
  border-color: rgba(34, 197, 94, 0.35);
}

.timeline-stage.is-blocked {
  border-color: rgba(245, 158, 11, 0.35);
}

.timeline-badge {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.timeline-owner,
.timeline-deliverable {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.timeline-doc {
  margin-top: 6px;
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
}

.handoff-section {
  margin-top: 8px;
}

.section-heading.small h2 {
  font-size: 16px;
}

.handoff-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.handoff-item {
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.handoff-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
}

.handoff-route {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.handoff-item p,
.handoff-empty {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
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

.stage-grid,
.scenario-grid,
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}

.stage-card,
.agent-entry {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 18px;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.stage-card:hover,
.agent-entry:hover {
  transform: translateY(-2px);
  border-color: var(--accent);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.18);
}

.stage-top,
.agent-entry-top,
.scenario-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.stage-badge {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, var(--accent), #6ea8ff);
}

.stage-card h3,
.agent-entry-top h3 {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.stage-desc,
.scenario-desc,
.agent-entry-body p {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.recommended-model,
.agent-recommended-model {
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

.agent-bound-profile {
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
}

.agent-bind-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.agent-bind-select {
  width: min(320px, 100%);
}

.stage-footer {
  margin-top: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.stage-output {
  font-size: 12px;
  color: var(--text-muted);
}

.launch-link {
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
}

.scenario-card {
  background: var(--bg-card);
  border-color: var(--border-color);
}

.scenario-actions {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.agent-entry {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.agent-entry-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-entry-body {
  min-width: 0;
  flex: 1;
}

.delivery-card {
  background: var(--bg-card);
  border-color: var(--border-color);
}

.delivery-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.delivery-layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
}

.delivery-sidebar {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.delivery-doc-item {
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  cursor: pointer;
  transition: border-color 0.18s ease, transform 0.18s ease;
}

.delivery-doc-item:hover,
.delivery-doc-item.active {
  border-color: var(--accent);
  transform: translateY(-1px);
}

.delivery-doc-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.delivery-doc-item p {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.delivery-editor {
  min-width: 0;
}

.delivery-editor-top {
  margin-bottom: 12px;
}

.delivery-editor-top h3 {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.delivery-editor-top p {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.7;
}

@media (max-width: 1100px) {
  .delivery-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .wayne-console-page {
    padding: 24px 20px 36px;
  }

  .console-header {
    flex-direction: column;
  }
}
</style>
