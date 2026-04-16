Phase 1 完成状态总结
Phase 1: 统一 Agent 数据源 + 接入工具运行时 -- 已完成 + 启动问题已修复

已交付的 10 项内容
#	交付项	关键文件	状态
1
Agent 种子数据统一 — 14 个 Agent，每个包含 capabilities（domain、seniority、boundary、deliverables、standards、collaboration）
backend/app/agents/seed.py
Done
2
工具绑定映射 (AGENT_TOOLS) — 每个 Agent 精确分配可执行工具（文件读写、bash、git、构建、测试等）
backend/app/agents/seed.py
Done
3
技能绑定 (AGENT_SKILL_BINDINGS) — Agent 与 10 个 Skill 的多对多关联，通过 AgentSkill 表落地
backend/app/agents/seed.py
Done
4
Agent API 丰富返回 — /api/agents/ 接口返回完整 Profile，含 tools[] 和 skills[]
backend/app/api/agents.py + schemas/agent.py
Done
5
Pipeline 接入 AgentRuntime — 流水线 Layer 4 调用 AgentRuntime.execute，有工具则用工具循环，无工具回退纯 LLM
backend/app/services/pipeline_engine.py
Done
6
Chat 接入工具 — 新增 POST /api/llm/chat-with-tools 端点，支持 Agent 带工具对话
backend/app/api/llm_proxy.py
Done
7
Skill 文件系统同步 — SKILL.md 启动时自动同步到数据库，category 保留语义分类
backend/app/services/skill_loader.py
Done
8
STAGE_SKILL_MAP 对齐 — 流水线阶段与技能 category 正确匹配
backend/app/services/skill_marketplace.py
Done
9
前端统一数据源 — 新建 useAgentStore Pinia store，Dashboard / App / AgentChat 三个视图全部从后端 API 加载 Agent 数据
src/stores/agents.ts + 3 个视图文件
Done
10
AgentCard 展示增强 — 展示 seniority、domain 标签、工具数、技能数
src/components/AgentCard.vue
Done
本轮额外修复（启动阻塞问题）
问题	修复
PG 有容器但无表，create_all 被跳过
main.py 增加自动检测：PG 无 users 表时执行 create_all
pgvector 扩展不存在导致建表失败
compat.py 改为启动时探测，无扩展则 vector 列回退 TEXT
seed_agent_skills 在 async session 中触发 lazy load
改用显式 select 查询替代 agent.skills 属性访问
架构变化一句话
之前：前端静态定义、后端 DB、Pipeline 硬编码 — 三套互不相通的 Agent 身份
之后：后端 DB 是唯一数据源，每个 Agent 携带 capabilities + tools + skills，Pipeline 和 Chat 都通过 AgentRuntime 执行工具调用，前端从 API 动态加载