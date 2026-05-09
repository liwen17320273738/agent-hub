AI 军团现状诊断 — 距离"打仗"还差什么
先说结论：当前 agent-hub 已经是一个"自动化产线"，但还不是"军团"。

产线 = 流水线、按工序走、出错就停。 军团 = 多兵种、能侦察能撤退能补给、有指挥与冗余。

下面按"事实 → 差距 → 补齐路径"展开，所有结论都基于刚刚对 backend/app 的全量勘察，不是空话。

一、当前实力（一句话画像）
维度	现状	段位
Agent 角色
14 个种子角色（CEO/产品/设计/前后端/QA/法务/SRE…），但只有 5 个真正接到 SDLC 阶段
★★★☆☆
协作方式
DAG + 线性双轨，peer-review 但无对话/辩论
★★☆☆☆
工具调用
标准 OpenAI tool-calling、文件/bash/搜索/git/构建/测试
★★★☆☆
代码生成
Claude Code CLI 主路径 + regex/LLM 抽取 fallback + auto-fix×3
★★★★☆
沙箱隔离
cwd 限制 + 路径白名单，无容器
★★☆☆☆
记忆
TaskMemory（pgvector）+ Redis working + LearnedPattern
★★★☆☆
质量门
self-verify（启发式）/ quality_gates / guardrails 三层
★★★☆☆
观测
trace + span + token 估算 + SSE
★★★☆☆
入口
飞书 / QQ / OpenClaw / Webhook / API / Web
★★★★☆
部署
Vercel / CF / 微信小程序 / AppStore / GooglePlay
★★★★☆
长任务自治
单阶段 600s 上限、无 checkpoint
★☆☆☆☆
浏览器
没有
☆☆☆☆☆
MCP 生态
没有
☆☆☆☆☆
评估 / 回归
没有
☆☆☆☆☆
简评：单兵装备良好，团队作战结构缺失，无法长时间作战，没有侦察兵也没有训练场。

二、和市场主流 Agent 的差距
对比矩阵（精简）
能力	agent-hub	Cursor/Claude Code	Devin	OpenHands	Manus	Aider	AutoGen/CrewAI	v0/Bolt
单 agent 写代码
✅ 强（Claude CLI）
✅✅
✅
✅
✅
✅✅
—
✅
Codebase 索引 / map
❌
✅✅
✅
✅
—
✅✅
—
—
Container 沙箱
❌
—
✅✅
✅✅
✅
—
—
✅
浏览器自动化
❌
—
✅✅
✅✅
✅✅
—
部分
—
多 agent 对话 / 委派
弱
—
—
✅
—
—
✅✅
—
长时自治（>1h, 可恢复）
❌
—
✅✅
✅
✅
—
—
—
Plan/Act 双模式
❌
✅
✅
✅
✅
✅
✅
—
MCP tool 生态
❌
✅✅
—
✅
—
—
✅
—
在线预览/边生成边看
弱
✅
—
—
—
—
—
✅✅
自动评测 / 回归
❌
内部有
✅
✅
—
—
—
—
部署到生产
✅✅
弱
✅
弱
—
—
—
✅
多渠道 IM 入口
✅✅
—
—
—
—
—
—
—
多角色业务 agent
✅（14角色）
—
—
—
—
—
✅
—
你的两块独门：多渠道 IM 入口 + 多角色业务 agent + 真部署到生产。 你的最大短板：沙箱、浏览器、长时自治、Codebase 索引、评测。

三、核心问题分级（按"不补就出事"的紧迫度）
🔴 致命级（不补，永远只能跑 toy demo）
P0-1 沙箱没有真隔离

现在 bash 直接 subprocess.shell 跑在 host 上，cwd 锁了但命令里 cd / 不拦
一个被 prompt-injected 的 web 搜索结果就能让 agent rm -rf 你的服务器
参考：tools/bash_tool.py:14–47
后果：接入到陌生用户/外部内容的瞬间，从"工具"变成"漏洞"
P0-2 长任务无法自治

单 phase 600s 超时、没有 checkpoint、没有断点续跑
Devin 能跑 8 小时、OpenHands 能跑 2 小时；你跑 10 分钟就硬切
后果：稍微复杂一点的需求（如"分析这个旧项目并迁移到新框架"）做不到
P0-3 没有浏览器能力

只有 duckduckgo_search，没有 Playwright/Puppeteer agent loop
不能登录后台抓数据、不能自动测在线网页、不能研究 SPA 内容
后果：所有"需要看真实网页"的任务（市调、爬数据、E2E 测试）全部做不了
P0-4 多 agent 是流水线不是团队

5 个角色串行 + 一次性 peer-review reject，没有 agent-to-agent 真对话
AutoGen/CrewAI 的 baseline 是 N 个 agent 自由交互、辩论、委派
14 个种子 agent 里 9 个根本没接到任何阶段（agents/seed.py:24–55 vs pipeline_engine.py:38–44）
后果："14 角色"是营销话术，实战只有 5 人在干
P0-5 没有 Codebase 索引

接入"已有项目"后 LLM 只能盲读零散文件
Aider 有 repo map、Cursor 有 embedding 索引，你都没有
后果：项目超 2 万行就废了，只能做新项目
🟠 结构性（不补，无法演化成军团）
P1-1 没有 MCP 客户端

2025 年所有主流 agent 平台都在接 MCP（Anthropic/OpenAI/Google/Microsoft/Cursor 全接了）
社区已有几百个 MCP server（DB、Notion、Jira、Slack、AWS…）
你不接就只能自己重写工具，永远落后生态
P1-2 没有 Eval / 回归基准

改 prompt 是赌博，没法回答"今天的军团比上周强多少"
没有 task suite、没有 SWE-bench-like 自测、没有 regression
后果：做大了不可维护，每次改动都心慌
P1-3 Memory 还停留在消息级

没有项目知识图谱、没有"这个项目历史决策"的检索
AgentRuntime 写 memory 时把 task_id=agent_id（agent_runtime.py:156–164）—— bug，导致按任务检索是空的
后果：跨任务、跨项目的"经验复用"根本没生效
P1-4 没有 agent 之间的子任务派发

DeerFlow 是外部委托，内部 5 个 agent 不能彼此说"这部分你来"
等于 14 个员工但只能听老板调度，不能协同
P1-5 Skill/Tool 没有市场化

DEFAULT_SKILLS 硬编码，没有版本/动态注册/分享/订阅
"技能商店"概念在 cursor skills、claude skills、cherry studio 都已经成熟
🟡 体验/工程（直接影响"敢不敢用"）
P2-1 没有 Plan/Act 双模式

Clarifier 解决了"信息不足"，但没解决"信息足但方案要先审"
Cline/Cursor Composer 都是：先输出方案 → 用户点"批准" → 才动代码
现在用户在 IM 一句话进来直接全跑，翻车成本极高
P2-2 用户全程黑盒

等到 phase 5 才有预览
v0/Bolt 是边生成边渲染、Cursor 是边写边 diff —— 你没有 streaming UI
P2-3 失败没有自动归因

trace 有，但没有 root-cause 自动诊断
用户只能看到 "failed: build error" 然后懵圈
P2-4 没有成本/预算控制

有 token 估算，没有"超 $X 自动暂停 / 用便宜模型重试"
接 IM 之后一个恶意用户能烧掉一天预算
P2-5 没有定时/巡检 agent

没有 APScheduler/Celery beat
做不到"每天 8 点自动跑销售日报"、"每小时巡检线上是否挂"
P2-6 多模态薄

只在 LLM 层支持 image_attachments
agent 不能"看 Figma 截图自己写组件"、不能"读 PDF 招标书自动出方案"
🔵 安全 / 治理（接生产前必须）
P3-1 多租户没做

IM user 没映射 users 表，没有 RBAC、没有项目隔离
接进公司：A 部门能看到 B 部门的 task
P3-2 Prompt Injection 防御缺位

搜索结果/外部网页内容直接喂给 LLM，没有任何过滤
"Ignore previous instructions" 类攻击毫无防线
P3-3 审计日志不合规

trace 在 Redis/PG 但可被覆盖
合规要求：每个工具调用追加写、不可改、可导出
P3-4 DAG 路径质量门弱于线性

DAG 主路径没有 peer-review 重试 / human_gate
但 IM 触发的 E2E 走的就是 DAG —— 生产路径反而比手动路径质量低（dag_orchestrator.py:333–343 vs pipeline_engine.py:1010–1047）
四、"AI 军团"应该长什么样
借鉴 Devin / OpenHands / Manus / CrewAI 的合集，目标架构：

                    ┌──────────────────────────────┐
                    │   指挥层 Commander           │
                    │   (planner + dispatcher)     │
                    └──────────────┬───────────────┘
                                   │
       ┌───────────────────┬───────┴───────┬───────────────────┐
       ▼                   ▼               ▼                   ▼
   ┌────────┐         ┌────────┐      ┌─────────┐         ┌─────────┐
   │ 侦察兵 │         │ 工兵    │      │ 战斗员   │         │ 后勤兵   │
   │ Scout  │         │Sapper  │      │Combatant│         │Logistics│
   │ 浏览器 │         │ 代码生成│     │ 测试&修   │         │ 部署&运维│
   │ 搜索   │         │ 重构    │     │ 复       │         │ 监控    │
   │ 文档   │         │         │      │          │         │         │
   └────────┘         └────────┘      └─────────┘         └─────────┘
       │                   │               │                   │
       └───────────┬───────┴───────────────┴───────────────────┘
                   ▼
        ┌──────────────────────┐
        │ 共享基础设施          │
        │ - Container Sandbox  │
        │ - MCP Tool Hub       │
        │ - Codebase Index     │
        │ - Memory + Eval      │
        │ - Cost Governor      │
        │ - Audit Trail        │
        └──────────────────────┘
关键升级：

指挥层负责 plan → dispatch → 监督 → 复盘
兵种之间能互相 delegate(subtask, to_agent) 并接受 report(result)
所有工具走 MCP 协议（自家工具也包成 MCP server，无缝接入社区生态）
沙箱是 container per task（Firecracker / gVisor / Docker）
每个 agent 都能被 Eval Suite 量化打分
五、三段式补齐路线图
🟢 30 天（"先能打仗"）
#	事项	价值	工作量
1
Plan/Act 双模式：IM 进来先发方案卡片 → 用户 approve → 才跑
直接降低翻车概率 80%
S
2
修 AgentRuntime memory task_id bug
让历史 memory 真正可用
XS
3
Browser 工具（Playwright headless）：作为新 tool 注册到 registry
解锁所有 web 类任务
M
4
Container 沙箱 v1（Docker per task）：bash/file 工具走 docker exec
关闭 host RCE 大门
M
5
Cost Governor：单 task 预算上限，超额自动降级模型
防止恶意用户烧钱
S
6
DAG 路径补齐 peer-review + human-gate
生产路径质量等于手动
S
7
多租户 v1：IM user → users 表 + 项目级 RBAC
接公司前置条件
M
🟡 90 天（"成为团队"）
#	事项	价值	工作量
8
MCP 客户端 + 把现有 tools 包成 MCP server
接入社区生态
M
9
真·多 agent：基于 LangGraph 或自研 state graph 重写 orchestrator，agent 能 delegate / debate
14 角色全部启用
L
10
Codebase 索引：tree-sitter AST + embedding（参考 Aider repo map）
解锁大项目
L
11
Eval Suite v1：30 个固定任务的 nightly run + 评分
改 prompt 不再赌博
M
12
失败自动归因：trace 接 LLM 做 RCA，给用户"为什么失败 + 建议"
客诉率降一半
S
13
Streaming Preview：codegen 边生成边推送，前端边渲染
等待感→参与感
M
14
长任务 Checkpoint：阶段中断后可断点续跑、>1h 任务
接近 Devin baseline
L
15
Prompt Injection 防御：外部内容前置 sanitizer + 输出验证
接外部数据安全
M
🔵 180 天（"指挥军团"）
#	事项	价值	工作量
16
Skill/Tool Marketplace：用户/团队可发布、订阅技能
形成飞轮
L
17
自我反思 + 学习：跑完任务 → 自动总结 LearnedPattern → 下次自动调用
真正会"成长"
L
18
多模态 Agent：直接消费 Figma / PDF / 截图 / 视频
业务侧需求 80% 是图
L
19
Scheduler / 巡检 agent：APScheduler + 自治日报、监控、告警响应
从"开发"扩到"运维"
M
20
联邦/分布式 sandbox：Firecracker microVM 集群
真正的算力规模化
XL
21
不可篡改审计：append-only log + 每日哈希链
合规过审
M
22
Self-eval + RLAIF：用 Eval Suite 反馈微调小模型 / 选 prompt
闭环优化
XL
六、最重要的一句话
你已经把"产线"做到了 75 分，但要从产线升级成军团，缺的不是更多角色，是 4 件事：

Container 沙箱（不然这军团是赤膊上阵）
浏览器（不然这军团是聋瞎）
真·多 agent + delegate（不然 14 个角色只是 5 个在干）
Eval Suite（不然你不知道军团强弱、不敢迭代）
其他都是锦上添花。这 4 件事按 30/90 天路线图先吃掉，1 个季度后你就能和 Devin/OpenHands 同台。

要不要我现在挑一个开始动手？我建议从 #1 Plan/Act 双模式 开始 —— 工作量小、收益巨大、能立刻让 IM 接入安全可用。或者你想先吃掉 #3 Browser 工具（解锁的能力面积最大）？

