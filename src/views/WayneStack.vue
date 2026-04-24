<template>
  <div class="wayne-stack-page">
    <header class="page-header">
      <div>
        <h1>{{ t('wayneStack.text_1') }}</h1>
        <p class="subtitle">
          以 Claude Code 为执行中枢、Cursor 为驾驶舱、Opus/Sonnet/GPT/Gemini 为多模型总线的人机协同架构。
        </p>
      </div>
      <div class="header-badges">
        <el-tag type="success" effect="dark">{{ t('wayneStack.text_2') }}</el-tag>
        <el-tag type="info">{{ t('wayneStack.text_3') }}</el-tag>
        <el-tag type="warning">{{ t('wayneStack.text_4') }}</el-tag>
      </div>
    </header>

    <el-alert class="summary-alert" type="info" :closable="false" show-icon>
      <template #title>一句话总结</template>
      Agent Hub 不是多开几个模型，而是把命令、角色、技能、工具和记忆层组织成一个可持续运转的 AI 交付操作系统。
    </el-alert>

    <section class="section-block">
      <div class="section-heading">
        <h2>一、核心模型 → 核心角色</h2>
        <p>核心展示前置。每一个核心模型对应 Agent Hub 的一个关键角色，不再只是抽象分工。</p>
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
        <h2>二、运行架构</h2>
        <p>从 Agent Hub 的目标开始，流经 Claude Code、工作流引擎、多模型总线、角色与技能，最终落到代码、文档和记忆。</p>
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
        <h2>三、命令路由</h2>
        <p>从终端发起命令，Claude Code 调总控编排器，再按任务类型路由到不同模型。</p>
      </div>

      <el-table :data="commandRoutes" stripe class="route-table">
        <el-table-column prop="command" label="命令" width="160" />
        <el-table-column prop="lead" label="主模型" width="120" />
        <el-table-column prop="review" label="复核 / 挑战" min-width="180" />
        <el-table-column prop="output" label="典型产出" min-width="220" />
      </el-table>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>四、典型执行链</h2>
        <p>以“登录与权限重构”为例，展示从 PRD 到上线建议的一次完整交付路径。</p>
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
        <h2>五、最小落地组合</h2>
        <p>先跑通需求、实现、质量验证，不要一开始就做完整军团。</p>
      </div>

      <div class="mvp-grid">
        <el-card class="mvp-card">
          <template #header>先启用的角色</template>
          <ul class="plain-list">
            <li>`wayne-orchestrator`</li>
            <li>`wayne-product-manager`</li>
            <li>`wayne-developer`</li>
            <li>`wayne-qa-lead`</li>
          </ul>
        </el-card>

        <el-card class="mvp-card">
          <template #header>先跑通的命令</template>
          <ul class="plain-list">
            <li>`/wayne-prd`</li>
            <li>`/wayne-build`</li>
            <li>`/wayne-qa`</li>
            <li>`/wayne-retro`</li>
          </ul>
        </el-card>

        <el-card class="mvp-card">
          <template #header>先沉淀的文档</template>
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
        <h2>六、调度模式面板</h2>
        <p>Agent Hub 不让四个模型同时做同一件事，而是按模式组合使用。</p>
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
        <h2>七、进入 Agent Hub 智能体</h2>
        <p>下面这 4 个已经接入当前 Agent Hub，可直接点击查看聊天入口和快捷提示词。</p>
      </div>

      <div class="agent-entry-grid">
        <div
          v-for="entry in wayneAgents"
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
            <span class="entry-link">进入聊天 →</span>
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
    title: 'Agent Hub',
    summary: '目标、审批、资源取舍和高风险动作的最终裁决者。',
    points: ['方向', '审批', '取舍', '人在环上'],
  },
  {
    index: '02',
    title: 'Claude Code Runtime',
    summary: '终端执行中枢，承载命令、插件、hooks、MCP 和流程编排。',
    points: ['commands', 'plugins', 'hooks', 'MCP'],
  },
  {
    index: '03',
    title: 'Workflow + Models',
    summary: '工作流引擎和多模型总线协同推进 Discovery -> Retro 全链路。',
    points: ['Opus 4.6', 'Sonnet 4.6', 'GPT-4.5', 'Gemini 4', 'GLM-4.5'],
  },
  {
    index: '04',
    title: 'Roles + Skills',
    summary: '用岗位层承担责任，用技能层固化方法，避免只靠 prompt vibe。',
    points: ['CEO', 'Product', 'Developer', 'QA', 'PRD', 'Test'],
  },
  {
    index: '05',
    title: 'Workspace + Memory',
    summary: '所有结果都落到代码、文档、测试和记忆层，而不是只停留在聊天里。',
    points: ['code', 'docs', 'tests', 'decisions', 'agent diaries'],
  },
]

const modelRoles: ModelRole[] = [
  {
    name: 'Opus 4.6',
    role: 'Agent Hub 总控 / 架构裁决',
    tag: 'Judgment',
    tagType: 'warning',
    items: ['复杂权衡', '架构收口', '高风险发布判断', '冲突仲裁', '最终 go/no-go'],
  },
  {
    name: 'Sonnet 4.6',
    role: 'Agent Hub 开发工程师',
    tag: 'Execution',
    tagType: 'success',
    items: ['连续编码', '多轮修复', '仓库级执行', '需求实现', '开发主力'],
  },
  {
    name: 'GPT-4.5',
    role: 'Agent Hub 产品经理',
    tag: 'Structure',
    tagType: 'primary',
    items: ['PRD / 文档', '结构化输出', '需求澄清', '代码 review', '高质量总结'],
  },
  {
    name: 'Gemini 4',
    role: 'Agent Hub QA / 研究挑战者',
    tag: 'Research',
    tagType: 'info',
    items: ['长上下文归纳', '方案对比', '架构 challenge', '风险挑战', 'QA 补充视角'],
  },
  {
    name: '智谱 GLM-4.5',
    role: 'Agent Hub 中文策略 / 本土化',
    tag: 'Localization',
    tagType: 'success',
    items: ['中文表达', '本土化内容', '中文业务沟通', '中国市场语境', '中文润色'],
  },
]

const commandRoutes = [
  {
    command: '/wayne-prd',
    lead: 'GPT-4.5',
    review: 'Opus 4.6 收缩范围 / GLM-4.5 中文润色',
    output: 'PRD、目标/非目标、验收标准',
  },
  {
    command: '/wayne-ui',
    lead: 'GPT-4.5 / Gemini 4',
    review: 'Opus 4.6 审核方向',
    output: 'UI spec、状态设计、交互说明',
  },
  {
    command: '/wayne-arch',
    lead: 'Opus 4.6',
    review: 'Gemini 4 challenge + GPT-4.5 结构化',
    output: '架构说明、接口契约、风险与 ADR',
  },
  {
    command: '/wayne-build',
    lead: 'Sonnet 4.6',
    review: 'GPT-4.5 代码与逻辑审查',
    output: '实现代码、实现说明、验证步骤',
  },
  {
    command: '/wayne-qa',
    lead: 'Gemini 4 / Sonnet 4.6',
    review: 'GPT-4.5 输出结论 / GLM-4.5 中文结论润色',
    output: '测试报告、PASS/NEEDS WORK 结论',
  },
  {
    command: '/wayne-ship',
    lead: 'Opus 4.6',
    review: 'Agent Hub 最终审批',
    output: '验收结论、回滚要点、发布建议',
  },
]

const executionFlow = [
  {
    step: '01',
    title: '需求定义',
    owner: 'GPT-4.5 -> Opus 4.6',
    description: '先把问题定义清楚，再收缩范围和验收标准。',
    artifacts: ['01-prd.md', '目标', '非目标'],
  },
  {
    step: '02',
    title: '架构与边界',
    owner: 'Opus 4.6 -> Gemini 4',
    description: '先决定模块边界、契约、失败路径，再进入实现。',
    artifacts: ['03-architecture.md', 'ADR', '风险'],
  },
  {
    step: '03',
    title: '代码实现',
    owner: 'Sonnet 4.6 -> GPT-4.5',
    description: 'Sonnet 主实现，GPT 负责 correctness 与 review。',
    artifacts: ['代码', '04-implementation-notes.md'],
  },
  {
    step: '04',
    title: '质量验证',
    owner: 'Gemini 4 / Sonnet 4.6 -> GPT-4.5',
    description: '对照 PRD 和风险点验证，明确 PASS / NEEDS WORK。',
    artifacts: ['05-test-report.md', '风险清单'],
  },
  {
    step: '05',
    title: '发布建议',
    owner: 'Opus 4.6 -> Agent Hub',
    description: '把验收、回滚、监控和上线建议收敛成最终结论。',
    artifacts: ['06-acceptance.md', '回滚', '监控'],
  },
]

const executionModes: ExecutionMode[] = [
  {
    name: 'Mode A: Build + Dual Review',
    short: '默认',
    description: '最适合开发任务。Sonnet 4.6 主实现，GPT-4.5 审 correctness，Gemini 4 审架构与维护性。',
    tagType: 'success',
    steps: ['Sonnet 4.6 实现', 'GPT-4.5 代码/逻辑审查', 'Gemini 4 架构 challenge', 'Opus 4.6 仅在冲突时裁决'],
  },
  {
    name: 'Mode B: Competing Proposals',
    short: '方案竞争',
    description: '适合架构与方案选择。让多个模型给不同实现路径，再由 Opus 4.6 收口。',
    tagType: 'warning',
    steps: ['Sonnet 4.6 方案 A', 'GPT-4.5 方案 B', 'Gemini 4 对比 tradeoff', 'Opus 4.6 选方案'],
  },
  {
    name: 'Mode C: Research + Converge',
    short: '研究收敛',
    description: '适合调研和大上下文任务。Gemini 4 先研究，GPT-4.5 结构化，Opus 4.6 决策。',
    tagType: 'info',
    steps: ['Gemini 4 研究归纳', 'GPT-4.5 结构化总结', 'Opus 4.6 方向结论', 'Sonnet 4.6 落地实现'],
  },
  {
    name: 'Mode D: High-Risk Change',
    short: '高风险',
    description: '涉及生产、权限、计费、数据风险时，必须先审查再执行。',
    tagType: 'primary',
    steps: ['GPT-4.5 写风险摘要', 'Gemini 4 挑战假设', 'Opus 4.6 做 go/no-go', 'Agent Hub 审批后执行'],
  },
]

const wayneAgents = [
  {
    id: 'wayne-orchestrator',
    name: 'Agent Hub 总控',
    title: 'Orchestrator',
    icon: 'Connection',
    color: '#7c5cff',
    description: '负责阶段推进、角色分配、阶段门检查和风险升级。',
    recommendedModel: '推荐：Opus 4.6',
  },
  {
    id: 'wayne-product-manager',
    name: 'Agent Hub 产品经理',
    title: 'Product Manager',
    icon: 'Memo',
    color: '#3b82f6',
    description: '负责 PRD、范围管理、用户故事和验收标准。',
    recommendedModel: '推荐：GPT-4.5',
  },
  {
    id: 'wayne-developer',
    name: 'Agent Hub 开发工程师',
    title: 'Developer',
    icon: 'Cpu',
    color: '#14b8a6',
    description: '负责最小改动实现、开发任务拆解和验证路径。',
    recommendedModel: '推荐：Sonnet 4.6',
  },
  {
    id: 'wayne-qa-lead',
    name: 'Agent Hub QA 负责人',
    title: 'QA Lead',
    icon: 'CircleCheckFilled',
    color: '#f59e0b',
    description: '负责风险验证、测试结论和发布前质量闸门。',
    recommendedModel: '推荐：Gemini 4',
  },
  {
    id: 'wayne-china-strategist',
    name: 'Agent Hub 中文策略',
    title: 'China Strategist',
    icon: 'ChatLineSquare',
    color: '#ef4444',
    description: '负责中文自然表达、本土化内容、老板视角汇报和中国市场语境适配。',
    recommendedModel: '推荐：智谱 GLM-4.5',
  },
]

function goAgent(id: string) {
  router.push(`/agent/${id}`)
}
</script>

<style scoped>
.wayne-stack-page {
  padding: 32px 40px 48px;
  max-width: 1400px;
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
  max-width: 860px;
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

@media (max-width: 900px) {
  .page-header {
    flex-direction: column;
  }

  .header-badges {
    justify-content: flex-start;
  }

  .wayne-stack-page {
    padding: 24px 20px 36px;
  }
}
</style>
