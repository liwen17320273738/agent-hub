Phase 2：Agent Profile 页面 + 能力展示 — 完成
新增内容
1. Agent Profile 页面 (src/views/AgentProfile.vue)

路由：/#/agent/:id/profile
Hero 区域：头像、名称、职称、资历、描述、专业域标签、关键数据（工具数/技能数/交付物数/标准数）
能力雷达图（SVG）：6 维度（分析、设计、编码、测试、运维、沟通），每个 Agent 形状不同
可用工具列表：双列网格，含名称和描述
绑定技能列表：含启用状态标签
协作关系：审阅/被审阅/升级路径，用彩色标签展示关联 Agent
交付物：该 Agent 的核心产出清单
工作边界：擅长处理 + 委派给其他专家
质量标准：有序列表
2. 后端数据增强 (backend/app/agents/seed.py)

为全部 14 个 Agent 添加 radar 维度评分
修改 seed_agents() 支持更新已有 Agent 的 capabilities（合并新字段）
3. 入口链接

AgentCard.vue：每张卡片新增"档案"链接
AgentChat.vue：侧边栏标题新增 Profile 图标链接
4. 路由 (src/router/index.ts)

/agent/:id/profile 放在 /agent/:id 前面，确保正确匹配
验证
76 个后端测试全部通过
Puppeteer 截图验证了开发工程师（编码 98 突出）和 CEO（沟通 95、分析 90 突出）的 Profile 页面，雷达图形态差异明显
所有前端 lint 检查无错误