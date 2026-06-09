/**
 * 企业 Agent 角色注册表
 * 
 * 每个角色定义了:
 * - 需要的 Skill 文件
 * - 需要的 MCP/工具
 * - 需要遵守的 Rule
 * - 推荐的 Agent 客户端
 * - 执行流程模板
 * 
 * 前端配置页面读取此数据，用户选择角色后自动勾选对应的 Skill/Tool/Rule
 */

export interface AgentRoleDefinition {
  id: string
  name: string
  line: string        // 业务线
  icon: string
  description: string
  skills: string[]           // 需要的Skill名称
  tools: string[]            // 需要的MCP/工具
  rules: string[]            // 需要遵守的Rule
  agentClients: string[]     // 推荐的Agent客户端
  workflowTemplate: string   // 执行流程简述
  configForm: {              // 配置页面需要用户填写的字段
    label: string
    key: string
    type: 'input' | 'password' | 'path' | 'select' | 'cron'
    required: boolean
    options?: { label: string; value: string }[]
  }[]
  schedule?: {               // 默认定时计划
    cron: string
    description: string
  }
}

export const agentRoles: AgentRoleDefinition[] = [
  // ========== 研发线 ==========
  {
    id: 'developer-backend',
    name: '后端开发',
    line: '研发',
    icon: 'Cpu',
    description: 'Java/Spring Boot 后端开发。自动查禅道Bug和任务，修复/开发 → 测试 → git提交 → 禅道完成',
    skills: ['zentao-workflow', 'springboot-patterns', 'java-coding-standards', 'springboot-tdd', 'database-reviewer'],
    tools: ['zentao', 'postgres', 'git', 'shell'],
    rules: ['zentao-constraints', 'commit-format', 'quality-gate', 'security-baseline'],
    agentClients: ['Claude Code', 'Codex', 'Cursor'],
    workflowTemplate: '查禅道active Bug → 修复 → mvn compile → mvn test → git commit #id → zentao_update_bug resolved',
    configForm: [
      { label: '禅道账号', key: 'zentao_account', type: 'input', required: true },
      { label: '禅道密码', key: 'zentao_password', type: 'password', required: true },
      { label: '后端项目路径', key: 'backend_path', type: 'path', required: true },
      { label: '前端项目路径(可选)', key: 'frontend_path', type: 'path', required: false },
      { label: '提交分支', key: 'branch', type: 'input', required: true },
    ],
    schedule: { cron: '0 9 * * 1-5', description: '工作日 9:00' },
  },
  {
    id: 'developer-frontend',
    name: '前端开发',
    line: '研发',
    icon: 'Monitor',
    description: 'Vue/React 前端开发。自动查禅道Bug和UI任务 → 修复 → type-check → 提交 → 禅道完成',
    skills: ['zentao-workflow', 'frontend-patterns', 'frontend-design', 'react-best-practices'],
    tools: ['zentao', 'git', 'shell'],
    rules: ['zentao-constraints', 'commit-format', 'quality-gate'],
    agentClients: ['Cursor', 'Claude Code'],
    workflowTemplate: '查禅道active Bug → 修复 → npm run type-check → git commit #id → zentao_update_bug resolved',
    configForm: [
      { label: '禅道账号', key: 'zentao_account', type: 'input', required: true },
      { label: '禅道密码', key: 'zentao_password', type: 'password', required: true },
      { label: '前端项目路径', key: 'frontend_path', type: 'path', required: true },
      { label: '提交分支', key: 'branch', type: 'input', required: true },
    ],
    schedule: { cron: '0 9 * * 1-5', description: '工作日 9:00' },
  },
  {
    id: 'developer-mobile',
    name: '移动端开发',
    line: '研发',
    icon: 'Phone',
    description: 'Flutter/小程序/iOS/Android 开发',
    skills: ['zentao-workflow', 'flutter-reviewer', 'dart-flutter-patterns', 'compose-multiplatform-patterns'],
    tools: ['zentao', 'git', 'shell'],
    rules: ['zentao-constraints', 'commit-format', 'quality-gate'],
    agentClients: ['Cursor', 'Codex', 'Claude Code'],
    workflowTemplate: '查禅道任务 → 开发 → flutter analyze → git commit #id → zentao_update_task done',
    configForm: [
      { label: '禅道账号', key: 'zentao_account', type: 'input', required: true },
      { label: '禅道密码', key: 'zentao_password', type: 'password', required: true },
      { label: '项目路径', key: 'project_path', type: 'path', required: true },
      { label: '项目类型', key: 'project_type', type: 'select', required: true,
        options: [
          { label: 'Flutter', value: 'flutter' },
          { label: '小程序', value: 'miniapp' },
          { label: 'iOS/Swift', value: 'ios' },
          { label: 'Android/Kotlin', value: 'android' },
        ]
      },
      { label: '提交分支', key: 'branch', type: 'input', required: true },
    ],
    schedule: { cron: '0 9 * * 1-5', description: '工作日 9:00' },
  },
  {
    id: 'qa-automation',
    name: '测试工程师',
    line: '研发',
    icon: 'CircleCheck',
    description: '自动验证已修复Bug、执行测试任务。查待测Bug → 执行测试 → 禅道更新状态',
    skills: ['zentao-workflow', 'e2e-testing', 'python-testing'],
    tools: ['zentao', 'puppeteer', 'postgres', 'shell', 'git'],
    rules: ['zentao-constraints', 'test-coverage'],
    agentClients: ['Claude Code', 'Cursor'],
    workflowTemplate: '查禅道resolved Bug → 验证 → 通过→closed / 不通过→active+备注',
    configForm: [
      { label: '禅道账号', key: 'zentao_account', type: 'input', required: true },
      { label: '禅道密码', key: 'zentao_password', type: 'password', required: true },
      { label: '项目路径', key: 'project_path', type: 'path', required: true },
    ],
    schedule: { cron: '0 10 * * 1-5', description: '工作日 10:00（等开发先提交）' },
  },
  {
    id: 'code-reviewer',
    name: '代码审查',
    line: '研发',
    icon: 'Document',
    description: '自动Review PR、代码质量检查、安全扫描',
    skills: ['ce-code-review', 'security-reviewer', 'typescript-reviewer', 'code-simplifier'],
    tools: ['github', 'zentao', 'code-review-graph'],
    rules: ['security-baseline', 'review-standards'],
    agentClients: ['Cursor Automation', 'Claude Code'],
    workflowTemplate: '查未Review的PR → 并行Review → 通过/打回+建议',
    configForm: [
      { label: 'GitHub Token', key: 'github_token', type: 'password', required: true },
      { label: '仓库地址', key: 'repo_url', type: 'input', required: true },
    ],
    schedule: undefined, // PR事件触发，非定时
  },

  // ========== 运维线 ==========
  {
    id: 'devops-automation',
    name: 'DevOps自动化',
    line: '运维',
    icon: 'Setting',
    description: '服务器巡检、部署流水线、CI修复、环境管理',
    skills: ['operations-baseline', 'fix-ci', 'deployment-expert', 'azure-deploy'],
    tools: ['shell', 'github', 'docker', 'zentao'],
    rules: ['operations-baseline', 'security-baseline'],
    agentClients: ['Claude Code', 'Cursor'],
    workflowTemplate: '每日服务器巡检 → 检查服务健康 → 报告异常 → 自动修复',
    configForm: [
      { label: '服务器地址', key: 'server_host', type: 'input', required: true },
      { label: 'SSH密钥路径', key: 'ssh_key_path', type: 'path', required: true },
    ],
    schedule: { cron: '0 7 * * 1-5', description: '工作日 7:00' },
  },
  {
    id: 'dba-automation',
    name: '数据库管理(DBA)',
    line: '运维',
    icon: 'DataBoard',
    description: 'SQL优化、慢查询分析、备份检查、数据库迁移',
    skills: ['database-reviewer', 'python-patterns', 'azure-storage'],
    tools: ['postgres', 'shell', 'filesystem'],
    rules: ['data-baseline', 'security-baseline'],
    agentClients: ['Claude Code'],
    workflowTemplate: '查慢查询日志 → 分析索引 → 生成优化SQL → 检查备份',
    configForm: [
      { label: '数据库连接串', key: 'db_connection', type: 'input', required: true },
      { label: '备份目录', key: 'backup_path', type: 'path', required: true },
    ],
    schedule: { cron: '0 6 * * 1-5', description: '工作日 6:00' },
  },
  {
    id: 'monitoring-sre',
    name: '监控SRE',
    line: '运维',
    icon: 'DataAnalysis',
    description: '告警响应、根因分析、自动恢复、事故报告',
    skills: ['azure-diagnostics', 'azure-kusto', 'sentry-workflow'],
    tools: ['sentry', 'shell', 'postgres'],
    rules: ['operations-baseline'],
    agentClients: ['Claude Code'],
    workflowTemplate: '收到告警 → 分析日志 → 定位根因 → 自动修复 → 生成事故报告',
    configForm: [
      { label: 'Sentry DSN', key: 'sentry_dsn', type: 'input', required: true },
    ],
    schedule: undefined, // 事件驱动
  },

  // ========== 数据线 ==========
  {
    id: 'data-analyst',
    name: '数据分析师',
    line: '数据',
    icon: 'TrendCharts',
    description: 'SQL查询、Python分析、可视化报表、商业洞察',
    skills: ['database-reviewer', 'python-patterns', 'chart-visualization'],
    tools: ['postgres', 'sqlite', 'shell', 'filesystem'],
    rules: ['data-baseline'],
    agentClients: ['Claude Code', 'Cursor'],
    workflowTemplate: '查数据需求 → SQL查询 → Python分析 → 生成可视化报告',
    configForm: [
      { label: '数据库连接串', key: 'db_connection', type: 'input', required: true },
    ],
    schedule: { cron: '30 8 * * 1-5', description: '工作日 8:30' },
  },
  {
    id: 'bi-analyst',
    name: 'BI分析师',
    line: '数据',
    icon: 'DataBoard',
    description: 'Dashboard设计、指标看板、周报/月报自动生成',
    skills: ['chart-visualization', 'python-patterns', 'frontend-slides'],
    tools: ['postgres', 'filesystem'],
    agentClients: ['Claude Code'],
    workflowTemplate: '查询本周核心指标 → 趋势分析 → 图表可视化 → 生成周报',
    configForm: [
      { label: '数据库连接串', key: 'db_connection', type: 'input', required: true },
    ],
    schedule: { cron: '0 16 * * 5', description: '每周五 16:00（周报）' },
  },

  // ========== AI/ML线 ==========
  {
    id: 'ai-developer',
    name: 'AI应用开发',
    line: 'AI',
    icon: 'MagicStick',
    description: 'RAG管道、Agent编排、Tool设计、LLM集成',
    skills: ['ai-sdk', 'mcp-server-patterns', 'ce-agent-native-architecture', 'vercel-workflow'],
    tools: ['shell', 'github', 'docker', 'postgres'],
    rules: ['security-baseline'],
    agentClients: ['Claude Code', 'Codex'],
    workflowTemplate: '理解AI需求 → 设计Agent架构 → 开发 → 测试 → 部署',
    configForm: [
      { label: '项目路径', key: 'project_path', type: 'path', required: true },
      { label: 'LLM API Key', key: 'llm_api_key', type: 'password', required: true },
    ],
  },
  {
    id: 'prompt-engineer',
    name: 'Prompt工程师',
    line: 'AI',
    icon: 'Edit',
    description: 'Prompt优化、Few-shot设计、评估集管理、LLM评测',
    skills: ['ai-sdk', 'ce-optimize', 'python-patterns'],
    tools: ['shell', 'github'],
    agentClients: ['Claude Code'],
    workflowTemplate: '分析Prompt缺陷 → 多版本迭代 → 评估集测试 → 上线',
    configForm: [
      { label: '项目路径', key: 'project_path', type: 'path', required: true },
    ],
  },

  // ========== 产品线 ==========
  {
    id: 'product-manager',
    name: '产品经理',
    line: '产品',
    icon: 'Memo',
    description: 'PRD撰写、需求评审、验收确认、竞品分析',
    skills: ['zentao-workflow', 'ce-brainstorm', 'ce-plan', 'ce-doc-review', 'sdlc-lifecycle'],
    tools: ['zentao', 'filesystem', 'github', 'brave-search'],
    rules: ['data-baseline'],
    agentClients: ['Claude Code', 'Cursor'],
    workflowTemplate: '查禅道reviewing需求 → 验收 → active(通过)/打回+备注',
    configForm: [
      { label: '禅道账号', key: 'zentao_account', type: 'input', required: true },
      { label: '禅道密码', key: 'zentao_password', type: 'password', required: true },
    ],
    schedule: { cron: '0 10 * * 1-5', description: '工作日 10:00' },
  },
  {
    id: 'ui-designer',
    name: 'UI设计师',
    line: '产品',
    icon: 'PictureFilled',
    description: '界面设计、设计系统维护、组件库管理、Figma操作',
    skills: ['figma-generate-design', 'figma-generate-library', 'ce-frontend-design'],
    tools: ['figma', 'pencil', 'zentao'],
    agentClients: ['Cursor'],
    workflowTemplate: '查禅道UI任务 → Figma设计 → 禅道完成+附设计稿链接',
    configForm: [
      { label: '禅道账号', key: 'zentao_account', type: 'input', required: true },
      { label: '禅道密码', key: 'zentao_password', type: 'password', required: true },
      { label: 'Figma Token', key: 'figma_token', type: 'password', required: true },
    ],
    schedule: { cron: '0 9 * * 1-5', description: '工作日 9:00' },
  },

  // ========== 营销线 ==========
  {
    id: 'content-marketer',
    name: '内容营销',
    line: '营销',
    icon: 'Promotion',
    description: '公众号/小红书/抖音内容生成、SEO优化、品牌文案',
    skills: ['ce-frontend-slides', 'ce-gemini-imagegen', 'seo-specialist'],
    tools: ['web-search', 'brave-search', 'filesystem'],
    agentClients: ['Claude Code'],
    workflowTemplate: '分析热点 → 选题 → 撰写内容 → SEO优化 → 多平台适配',
    configForm: [
      { label: '内容输出目录', key: 'output_path', type: 'path', required: true },
    ],
    schedule: { cron: '0 8 * * 1-5', description: '工作日 8:00' },
  },

  // ========== 商务线 ==========
  {
    id: 'sales-agent',
    name: '销售',
    line: '商务',
    icon: 'Goods',
    description: '话术生成、报价方案、客户跟进策略',
    skills: ['deploy-on-aws', 'azure-prepare'],
    tools: ['filesystem', 'slack', 'brave-search'],
    agentClients: ['Claude Code'],
    workflowTemplate: '分析客户需求 → 生成技术方案 → 报价 → 跟进策略',
    configForm: [
      { label: 'Slack Token', key: 'slack_token', type: 'password', required: false },
    ],
  },

  // ========== 职能线 ==========
  {
    id: 'hr-agent',
    name: 'HR',
    line: '职能',
    icon: 'UserFilled',
    description: '简历筛选、面试问题生成、入职流程管理',
    skills: ['python-patterns'],
    tools: ['filesystem', 'slack'],
    agentClients: ['Claude Code'],
    workflowTemplate: '阅读简历 → 筛选匹配 → 生成面试问题 → 安排流程',
    configForm: [
      { label: '简历目录', key: 'resume_path', type: 'path', required: true },
    ],
  },
  {
    id: 'finance-agent',
    name: '财务',
    line: '职能',
    icon: 'Money',
    description: '收支分析、发票管理、税务提醒、预算跟踪',
    skills: ['python-patterns', 'database-reviewer'],
    tools: ['filesystem', 'postgres'],
    agentClients: ['Claude Code'],
    workflowTemplate: '读取财务数据 → 收支分析 → 生成报表 → 税务提醒',
    configForm: [
      { label: '财务数据目录', key: 'finance_path', type: 'path', required: true },
    ],
    schedule: { cron: '0 9 1 * *', description: '每月1日 9:00' },
  },
  {
    id: 'legal-agent',
    name: '法务',
    line: '职能',
    icon: 'Document',
    description: '合同审查、隐私合规、知识产权保护',
    skills: ['security-reviewer', 'compliance-baseline'],
    tools: ['filesystem', 'web-search'],
    rules: ['compliance-baseline', 'security-baseline'],
    agentClients: ['Claude Code'],
    workflowTemplate: '审查合同 → 标注风险条款 → 合规检查 → 生成审查意见',
    configForm: [
      { label: '合同目录', key: 'contract_path', type: 'path', required: true },
    ],
  },

  // ========== 管理线 ==========
  {
    id: 'project-manager',
    name: '项目经理',
    line: '管理',
    icon: 'SetUp',
    description: '进度跟踪、风险预警、周报生成、跨团队协调',
    skills: ['zentao-workflow', 'ce-plan', 'operations-baseline'],
    tools: ['zentao', 'slack', 'github'],
    rules: ['zentao-constraints'],
    agentClients: ['Claude Code', 'Cursor'],
    workflowTemplate: '查禅道全项目进度 → 识别延期风险 → 生成晨会简报 → Slack推送',
    configForm: [
      { label: '禅道账号', key: 'zentao_account', type: 'input', required: true },
      { label: '禅道密码', key: 'zentao_password', type: 'password', required: true },
      { label: 'Slack Webhook', key: 'slack_webhook', type: 'input', required: false },
    ],
    schedule: { cron: '0 8 * * 1-5', description: '工作日 8:00（晨会前）' },
  },
  {
    id: 'executive-assistant',
    name: 'CEO助手',
    line: '管理',
    icon: 'TrendCharts',
    description: '决策支持、竞品洞察、战略分析、管理层周报',
    skills: ['zentao-workflow', 'ce-product-pulse', 'ce-weekly-review'],
    tools: ['zentao', 'github', 'slack', 'brave-search'],
    agentClients: ['Claude Code'],
    workflowTemplate: '收集本周所有Agent报告 → 汇总关键指标 → 生成管理层周报 → Slack发送',
    configForm: [
      { label: 'Slack Webhook(报告推送)', key: 'slack_webhook', type: 'input', required: true },
    ],
    schedule: { cron: '0 17 * * 5', description: '每周五 17:00（管理层周报）' },
  },
]

export function getRoleById(id: string): AgentRoleDefinition | undefined {
  return agentRoles.find(r => r.id === id)
}

export function getRolesByLine(line: string): AgentRoleDefinition[] {
  return agentRoles.filter(r => r.line === line)
}

export function getLines(): string[] {
  return [...new Set(agentRoles.map(r => r.line))]
}

export function getRequiredSkills(roleIds: string[]): string[] {
  return [...new Set(roleIds.flatMap(id => {
    const role = getRoleById(id)
    return role ? role.skills : []
  }))]
}

export function getRequiredTools(roleIds: string[]): string[] {
  return [...new Set(roleIds.flatMap(id => {
    const role = getRoleById(id)
    return role ? role.tools : []
  }))]
}

export function getRequiredRules(roleIds: string[]): string[] {
  return [...new Set(roleIds.flatMap(id => {
    const role = getRoleById(id)
    return role ? role.rules : []
  }))]
}
