
分析当前项目： 0-1 自动化AI-agent 是否已经完成。 每一个Agent 之间 的角色、能力怎么关联。给一个任务是否具备产品分析、UI设计、开发、测试、验收、运维-上线。代码生成、测试工作流、验收工作流等

下面是一份基于代码事实的全景诊断（不走文档，直接对照 backend/app/services/、backend/app/agents/seed.py、pipeline_engine.py、dag_orchestrator.py、e2e_orchestrator.py、tools/registry.py 等实文件）。

一、结论先行
维度	是否完成	实际成熟度
0→1 自动化端到端管线
✅ 已打通
75 分（产线级），可以从一句话需求一路跑到部署预览
多 Agent 角色覆盖 SDLC
⚠️ 部分
14 个种子角色，但主管线只接 5 个，其余 9 个靠 delegate_to_agent 被动召唤
真·军团（自由委派/辩论/长任务）
❌ 未到位
角色之间是流水线交接，不是协同作战
简评："0-1 自动化产线"已经做完，但"AI 军团"只完成了 60%。

二、Agent 角色矩阵（按代码事实）
1. 14 个种子 Agent（backend/app/agents/seed.py）
Agent ID	角色	在主管线	工具数	绑定技能	备注
Agent-ceo
CEO/总控
✅ planning + reviewing
6
prd-writing
orchestrator
Agent-cto
CTO/架构师
✅ architecture
16（含 codebase_*）
code-review/security-audit/architecture-design
tech-lead
Agent-product
产品经理
❌ 未挂阶段
8
prd-writing/deep-research/data-analysis
与 CEO 角色重叠
Agent-developer
开发
✅ development
22（最完整）
code-review/api-design
全工具链
Agent-qa
测试
✅ testing
16（含 browser/test_execute）
test-strategy/code-review
真正能跑测试
Agent-designer
UI/UX 设计
❌ 未挂阶段
7
deep-research
仅靠 codegen 内部插 design 段
Agent-devops
DevOps/SRE
✅ deployment
12
deploy-checklist/security-audit
Agent-acceptance
验收官
❌ 未挂阶段
8
prd-writing/test-strategy
角色与 reviewing 重叠
Agent-security
安全
❌ delegation only
7
security-audit/code-review
被动召唤
Agent-data
数据分析
❌ delegation only
6
data-analysis
Agent-marketing
CMO
❌ delegation only
4
deep-research
Agent-finance
CFO
❌ delegation only
4
data-analysis/token-optimization
Agent-legal
法务
❌ delegation only
4
deep-research
openclaw
IM 网关
✅ gateway 入口
2
—
意图识别
关键事实：pipeline_engine.STAGE_ROLE_PROMPTS 只为 6 个阶段提供 prompt，分别对应 ceo/architect/developer/qa/ceo/devops。其他 9 个角色虽在 DB 里，但永远不会被主管线主动调用。要触发它们，必须：

用户在 UI 里直接 @ 选择
主线 agent 在 ReAct 循环里调用 delegate_to_agent(role, task)（已经实现，见 agent_delegate.py）
或者通过 agent_publish/agent_wait_for 发消息总线（Wave-4 新增）
2. Agent 之间的关联机制（已实现）
              ┌─────── OpenClaw 网关 ────────┐
              ▼                              │
       ┌───── CEO ─────┐                     │
       │   (planning)  │                     │
       │       ↓ peer-review by 架构师       │
       │   架构师                            │
       │       ↓ peer-review by 开发         │
       │   开发                              │
       │       ↓ peer-review by 测试         │
       │   测试                              │
       │       ↓ peer-review by CEO          │
       │   CEO 验收 (human gate)             │
       │       ↓                             │
       │   DevOps 部署 (human gate)          │
       └─────────────────────────────────────┘
                   ↑↓ 任何人可以
                   delegate_to_agent(security/designer/data/legal/...)
                   agent_publish/wait_for
                   agent_bus 异步消息总线
源代码证据：

串行接力：STAGE_REVIEW_CONFIG（pipeline_engine.py:78-144）每个阶段都有下一阶段角色做 peer-review，最多重试 2 次
DAG 并行：PIPELINE_TEMPLATES（dag_orchestrator.py:84-168）有 12 套模板，可并行
Human Gate：reviewing 和 deployment 阶段强制人工审批
异步总线：agent_bus.py + agent_publish/agent_wait_for 工具
委派工具：agent_delegate.py + delegate_to_agent 工具
三、给一个任务，能否走完全流程？逐项核验
阶段	是否实现	证据	成熟度
产品分析 (PRD)
✅
STAGE_ROLE_PROMPTS["planning"] (CEO 输出 8 段式 PRD)
★★★★☆
UI 设计
⚠️ 不完整
设计师角色有，但主管线没有 design 阶段；只有 codegen_agent.py:42-49 在拼 prompt 时把 design 字段读出来；web-design-guidelines / frontend-design 在 skills 里
★★☆☆☆
开发 (代码生成)
✅ 强
services/codegen/codegen_agent.py — 主路径 Claude Code CLI，fallback 是 LLM 抽 markdown 代码块；支持模板脚手架
★★★★☆
测试
✅
QA agent + test_execute / run_tests / test_detect（pytest/jest/vitest/go/cargo），结果带结构化报告
★★★★☆
构建 & 自动修复
✅
e2e_orchestrator.py:230-269 build → fail → auto_fix → retry，最多 3 次
★★★★☆
验收 (Acceptance)
⚠️
在 reviewing 阶段由 CEO 角色做评审 + human gate；但专门的"验收官"agent 是孤儿，没接到管线里
★★★☆☆
运维/上线
✅
deploy/ 下 5 个适配器：Vercel / Cloudflare / 微信小程序 / AppStore / GooglePlay；e2e_orchestrator._auto_deploy 自动选平台
★★★★☆
预览 + 反馈
✅
interaction/preview.py 截图 + IM 通知 "回复『通过』即上线"
★★★★☆
观测/审计
✅
observability.py trace + span + token；SSE 实时；pipeline_checkpoint.py 断点续跑
★★★☆☆
端到端串接器
e2e_orchestrator.run_full_e2e 是真正的"主调度"，分 6 个 phase：

Phase 1: design-pipeline        (planning + architecture)
Phase 2: codegen                (Claude Code 写真实文件)
Phase 3: build-test → auto-fix  (build 失败自动修，最多 3 次)
Phase 4: deploy                 (Vercel/CF/小程序…)
Phase 5: preview                (Playwright 截图)
Phase 6: notify                 (飞书/QQ 推送预览链接)
结论：0→1 自动化已经端到端跑通。 一句话需求从 IM 进来，可以一路跑到生产 URL + 通知用户。这一点已经超过 OpenHands 和 Aider，部分追上了 v0/Bolt。

四、代码生成 / 测试工作流 / 验收工作流详解
1. 代码生成（已实现 ★★★★☆）
backend/app/services/codegen/：

templates.py — 内置 vue-app / react-app / fastapi-backend / wechat-miniprogram 等脚手架
codegen_agent.py — 主路径：把 PRD + 架构方案拼成 prompt 喂给 Claude Code CLI（executor_bridge.py），让它在 projects/{slug}/ 下真实写文件
沙箱：tools/sandbox.py (cwd 锁定) + tools/docker_sandbox.py（容器隔离，新加的）
兜底：regex 抽 markdown 代码块 / LLM 二次抽取
2. 测试工作流（已实现 ★★★★☆）
tools/test_runner.py：

自动检测 runner（pytest/jest/vitest/go/cargo）
解析结果（pass/fail/skip/失败用例）
输出 markdown 报告
tools/build_tool.py 提供 build/install_deps/run_tests 三个粗粒度工具；agent_runtime.py 通过 OpenAI tool-calling 让 QA agent 自由调用。

3. 验收工作流（部分实现 ★★★☆☆）
两条路线重复且未对齐：

路线 A：pipeline_engine.STAGE_REVIEW_CONFIG 的 peer-review（每阶段下游角色审上游，REJECT 自动重试）
路线 B：reviewing 阶段 CEO 出最终结论（APPROVED/REJECTED + REJECT_TO 路由），human-gate 强制人审
问题：

DAG 路径下 peer-review 比线性路径弱（AI-Agent.md P3-4 已记录）
"验收官" agent (Agent-acceptance) 完全没接管线
验收没用 e2e 真实部署后的 URL 做 E2E 验证
五、能力短板（按"距军团差距"分级）
🔴 致命级（0→1 已通，但不可大规模商用）
#	问题	现状
1
9 个角色未接管线
product/designer/acceptance/security/data/legal/marketing/finance/openclaw 在 DB 但不进 STAGE_ROLE_PROMPTS
2
没有专门的 design 阶段
UI 设计被塞进了 codegen 的 prompt 里，没有独立产物可审
3
多 Agent 是流水线，不是辩论
没有 round-robin 讨论、没有 vote、没有协商
4
delegate_to_agent 是树形递归而非图
不能形成长链路协作记忆
🟠 结构性
#	问题	现状
5
Codebase 索引已建（codebase_indexer.py + pgvector），但 embedding 在 ivfflat 上才稳
大项目体验未验证
6
MCP 客户端已有（mcp_client.py），但 MCP server 生态没接
仍然是自家工具为主
7
Eval 框架已有（eval_runner.py / eval_scorer.py），但 没有固定 benchmark 集
不能量化"今天比上周强多少"
8
长任务 checkpoint 已有（pipeline_checkpoint.py），但 单 stage 仍 600s 上限
复杂任务仍会硬切
🟡 体验
#	问题
9
Plan/Act 双模式：有 plan_session.py / clarifier.py，但默认仍直接全跑
10
UI 没有 streaming preview（边生成边渲染）
11
失败自动归因有 rca_reporter.py 雏形，但没接到主流程
12
Cost Governor 缺失 — 有 token 估算无预算硬上限
🔵 治理
#	问题
13
多租户：用户表存在，但 IM user → users 映射弱，项目隔离未做
14
Prompt Injection 防御缺位（外部网页内容直接喂 LLM）
15
审计日志非 append-only
六、给你的产品判断
"0→1 自动化"是否完成？
✅ 完成 — 但只在『新建小项目』场景下。

一句话 → PRD → 架构 → 代码 → 构建 → 部署 → 预览 → 通知，链路无断点
12 个 DAG 模板覆盖 web/api/data/微服务/SaaS/移动 6 个常见品类
Build 失败可自动修复 3 次，部署有 Vercel/CF/小程序 5 个真渠道
14 个 Agent 是否真的协作？
⚠️ 营销话术 vs 实战脱节：

真正协作的是 5 个：CEO ↔ 架构师 ↔ 开发 ↔ QA ↔ DevOps（peer-review 闭环 + human gate）
9 个是"被动咨询专家"：得有人主动 delegate_to_agent 或在 UI 里 @ 才会被叫醒
没有任何两个 agent 之间能"自由对话"，只能走 publish/wait_for 异步总线
给一个真实需求能完成 PM/UI/DEV/QA/Acceptance/Ops 的全流程？
流程项	答案
产品分析
✅ 8 段式 PRD，质量看模型
UI 设计
❌ 没有独立阶段，靠 codegen 的 prompt 拼凑
开发
✅ Claude Code 真写真跑
测试
✅ 自动检测 runner + 结构化报告
验收
⚠️ peer-review + human-gate，但与"验收官 agent"角色重叠未对齐
运维上线
✅ 5 个真平台
七、最优先 4 件事（30 天内吃掉）
按 ROI 排序，全部基于已有代码可低成本补齐：

把 9 个孤儿 agent 接进 DAG 模板 — 在 dag_orchestrator.PIPELINE_TEMPLATES 加 design / acceptance / security / legal 等阶段，让 14 角色真上场
新增 design 独立阶段 — 设计师 agent 输出布局/配色/组件规范，作为 codegen 的强输入而不是 prompt 拼接
统一 reviewing 与 acceptance — 把 Agent-acceptance 真正挂到 reviewing 阶段（替代当前 CEO），并要求基于 e2e 部署后的 URL 做截图验证
Cost Governor + Prompt Injection 防御 — 接 IM 进生产前的两个最低门槛