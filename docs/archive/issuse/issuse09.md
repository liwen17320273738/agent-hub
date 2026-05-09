路线 1：垂直产品 — AI Issue Resolver
1.1 一句话定位（用这个去说服别人）
Devin for your existing Jira/GitHub backlog — open-source, self-hosted, and it actually merges PRs.

中文版："AI 工程师插进你现有的 Jira/GitHub 工作流。你照常写 ticket，它写代码、开 PR、跑测试、回应 reviewer 评论、改完再 push，直到 reviewer approve 或主动撤回。"

关键差异化（一句话能讲清的才是 differentiator）：

vs Devin：开源 + 自部署（Devin $500/mo + 闭源 + 数据上云）
vs Aider / Cline / Claude Code：异步（你不在终端守着，AI 在后台跑），接 Jira/GitHub 原生流程（不是新建 IDE 工具）
vs Sweep AI / Cosine：双向闭环（reviewer 评论会触发 AI 修改，不是单次 PR），self-heal（reject 后自动 patch prompt）
vs GitHub Copilot Workspace：自部署 + 任意模型（Copilot Workspace 锁 GitHub + OpenAI）
1.2 产品名 / 域名建议
候选名	优点	缺点
Resolvr
短，可注册（.dev .ai 应该都在）
假名词
Backlog AI
自解释
太通用，搜索被挤
Issuely
押 PMF 名"-ly"
烂大街
Acme (内部代号)
—
别用
PR-Bot / PRagmatic
"PR" 是关键词
淹没在 GitHub 工具里
推荐：Resolvr + 域名 resolvr.dev（如不可用退到 resolvr.ai 或 resolvr.so）。GitHub 仓库名 resolvr-io/resolvr。

1.3 MVP 功能矩阵（4 周交付）
把 agent-hub 现有能力剪枝成专注做"issue → PR → merge"。

必须有（MVP 不能砍）
功能	来源	改造工作量
GitHub Issue webhook → 创建 task
✅ 已有 integrations.py webhook
改 trigger 类型加 issues.opened/labeled
Jira ticket → 创建 task
✅ 已有 parse_jira_comment，要补 parse_jira_issue_created
1 天
AI 读 issue → clone repo → 写代码
🟡 部分有：codegen_agent + git_tool
2 天接
在 Docker sandbox 里跑测试
✅ docker_sandbox.py 已有
0 天
自动开 PR + 链接回 issue
🟠 github.py 只支持 issue + comment，要加 create_pull_request
2 天
Reviewer 评论 → AI 修改 → 推 commit
✅ webhook + reject self-heal 已有
1 天接通
Approval 信号 → 自动 merge
❌ 全新
1 天
失败 N 次 → escalate + label
✅ escalation.py 已有
0 天
Web UI：看 issue 队列 + 当前阶段 + diff 预览
🟠 现有 dashboard 改造
3 天
小计：~10.5 天 一人 = 2.5 周到 MVP（前提是单人全职）。

V1 补丁（MVP 后 2 周）
多模型路由（用户带自己的 Claude / GPT / DeepSeek key）— 已有
Cost cap（防止单 issue 烧 $100）— cost_governor.py 已有，要露 UI
Allowlist 仓库 / 分支保护规则 — 1 天
RESOLVR_INSTRUCTIONS.md 仓库根级配置文件（项目规范、test 命令、禁忌）— 模仿 CLAUDE.md/AGENTS.md 套路 — 2 天
V2 才考虑（不要在 launch 前做）
Slack/飞书审批流（已有适配，但不是核心 UX）
RAG codebase 索引（codebase_indexer.py 有，但加进 MVP 增加 demo 复杂度）
Self-hosted "team plan"（多人协作）
VS Code 插件
1.4 技术裁剪清单（agent-hub → Resolvr）
保留（直接复用）：

backend/app/services/connectors/        # Jira + GitHub 双向
backend/app/services/escalation.py
backend/app/services/dedup.py
backend/app/services/feedback_lock.py
backend/app/services/dag_orchestrator.py
backend/app/services/codegen/
backend/app/services/tools/docker_sandbox.py
backend/app/services/tools/git_tool.py
backend/app/services/tools/test_runner.py
backend/app/services/tools/build_tool.py
backend/app/services/llm_router.py
backend/app/services/cost_governor.py
backend/app/services/quality_gates.py
backend/app/redis_client.py
砍掉（垂直产品不需要）：

backend/app/services/deploy/           # Vercel/小程序 等部署能力
backend/app/services/notify/qq_onebot.py    # 国际市场无 QQ
backend/app/services/notify/feishu_im.py    # 飞书可后期加回
backend/app/services/skill_marketplace.py   # 不要分散注意力
backend/app/services/weekly_digest.py
skills/public/ppt-generation/, image-generation/, frontend-design/, etc.
新增（MVP 缺的）：

backend/app/services/connectors/github.py
  + create_pull_request(repo, branch, title, body)
  + get_pr_review_comments(pr_number)
  + merge_pull_request(pr_number, method="squash")
backend/app/services/connectors/jira.py
  + transition_issue(key, status)   # In Progress / In Review / Done
backend/app/services/resolvr/
  ├── issue_to_task.py     # 入口转换器
  ├── repo_workspace.py    # clone / cleanup / cache
  ├── pr_lifecycle.py      # PR 状态机：draft → ready → review → merge
  └── instruction_loader.py # 读 RESOLVR.md
DAG 模板换一套：

PIPELINE_TEMPLATES["resolvr"] = [
    DAGStage("triage",    "Read issue + repo context",       "issue-reader"),
    DAGStage("plan",      "Plan changes + files to touch",    "planner",        depends_on=["triage"]),
    DAGStage("implement", "Write code in sandbox",            "codegen",        depends_on=["plan"]),
    DAGStage("test",      "Run repo's test suite",            "test-runner",    depends_on=["implement"]),
    DAGStage("pr",        "Open draft PR",                    "pr-opener",      depends_on=["test"]),
    DAGStage("review",    "Wait for reviewer + apply fixes",  "review-handler", depends_on=["pr"]),
    DAGStage("merge",     "Squash & merge after approval",    "merger",         depends_on=["review"]),
]
1.5 商业模式 / 定价（先想清楚再写代码）
层	价格	内容	对标
OSS Free
$0
自部署，全功能，无 issue 数限制
Aider OSS
Cloud Hobby
$19 / mo
100 issues/mo，单 user，BYO API key
Lindy starter
Cloud Team
$99 / user / mo
unlimited issues，team RBAC，audit log
Linear scale
Enterprise
$callme
self-host w/ SSO + SOC2
Linear enterprise
关键：OSS 必须真正可用（不要做 "open-core" 把核心能力锁掉）——这是 vs Devin 的最大武器，也是上 HN 的入场券。Cloud 的价值在于"我不想自己跑 PostgreSQL + Redis + 给 GitHub 配 webhook"，不在功能阉割。

1.6 Go-to-Market（4 个月路线）
月	动作	目标指标
M1
砍 + 重命名 + 单仓库分叉 → Resolvr v0.1
code 跑通
M1 末
自己用 Resolvr 给 Resolvr 提 issue（dogfood）
至少 5 个真 PR merge
M2
录 90 秒 demo（"AI 自己开 PR 自己改"） + 写文档
demo 视频 + landing page
M2 末
HN launch + r/programming + r/devops + Twitter/X
100 ★
M3
第一波用户反馈迭代 + Cloud beta（10 人 waitlist）
500 ★ + 10 cloud waitlist
M4
Cloud 公测 $19/mo + 写 "我们怎么做 Devin 平替" 长文
1k ★ + 第一笔订阅
1.7 致命风险（不解决会死）
风险	概率	缓解
GitHub 把它当成滥用 → API 限流 / token 封号
高
明确文档：用户必须用自己的 PAT；不做"集中 bot 账号"
跑出来的代码能力撑不住 demo
高
MVP 前必须自己跑通 30+ 真实 issue（自家 + 几个友好 OSS 仓库），录视频前要剪掉惨案
Cognition 直接降价或开源 Devin
中
OSS 先发优势 + 多模型支持（Devin 锁自家）
OSS 被人 fork 包装成 SaaS 抢市场
中
Cloud 端深度集成 + license 用 BSL（n8n 套路）而非 MIT
demo 仓库选错 → 跑不出像样 PR
高
选 npm 库 / 小型 Python 库（< 5k LoC）做 launch demo，别碰 monorepo
路线 2：3 周拿 1k 星 — Builder + SWE-Bench + Launch
2.1 Workflow Builder（前端 2 周）
技术选型（10 分钟搞定，不要纠结）
决策	选	不选的理由
节点编辑库
Vue Flow (vueflow.dev)
React Flow 是行业事实标准但你是 Vue 3，转 React 不值；Vue Flow 是 React Flow 的 Vue 直接移植，API 一致
数据序列化
JSON 跟现有 DAGStage 1:1 映射
不要发明 DSL
状态管理
Pinia 复用
已用
节点配置面板
Element Plus（项目已用）
不引新依赖
pnpm add @vue-flow/core @vue-flow/background @vue-flow/controls @vue-flow/minimap
Schema 映射（builder 输出 = 后端能直接吃的格式）
DAGStage 已经长这样：

DAGStage(name, label, agent_role, depends_on=[...])
Builder 节点 → JSON：

{
  "id": "stage_dev",
  "type": "agentStage",
  "position": {"x": 280, "y": 150},
  "data": {
    "name": "development",
    "label": "开发实现",
    "agentRole": "developer",
    "model": "claude-sonnet-4",     // 可选，默认走 router
    "qualityGate": {"minScore": 0.8},
    "rejectAction": "self-heal"     // self-heal | escalate | manual
  }
}
后端零改动——builder 序列化的 JSON 经过一个新的 parse_workflow_json() 转成现有 List[DAGStage] 喂给 dag_orchestrator。

2 周交付分解（按 5 工作日 × 2）
Week 1：能跑通

Day	内容
D1
装 Vue Flow，画一个 hello-world canvas 在 src/views/WorkflowBuilder.vue
D2
自定义节点组件 AgentStageNode.vue（图标 + 名字 + role 下拉）
D3
连线 = depends_on，禁止环（topological 校验）
D4
右侧配置面板：点击节点 → 编辑 name/role/model/quality gate
D5
保存 / 加载 JSON（本地 + 调后端 /api/pipeline/templates 新增 CRUD）
Week 2：能用

Day	内容
D6
"运行" 按钮 → 调 POST /pipeline/tasks 带自定义 stages
D7
执行视图：节点高亮当前 stage（订阅现有 SSE），失败标红，输出 hover 显示
D8
模板库：load web_app / api_service / full 一键 import
D9
导出 JSON / YAML，README 截图替换成 builder 截图
D10
录 30 秒 GIF，写 builder 文档 docs/BUILDER.md
预计风险：节点上显示运行状态比想象的吃细节（颜色 + 进度 + tooltip + 错误展开），可能要 +2 天。提前砍：只标"running / done / failed"三态，不做百分比进度条。

2.2 SWE-Bench 跑分（后端 1 周）
选哪个 benchmark
选项	题量	跑一遍成本	推荐
SWE-Bench full
2294
$500-2000+ + 数天
❌ 太重
SWE-Bench Lite
300
~$50-150 + 6-12 小时
✅ 选这个
SWE-Bench Verified
500
$100-300
🟡 备选（OpenAI 官方筛过的高质量子集）
**推荐：**先跑 SWE-Bench Lite 拿数据，再跑 Verified对比 — Verified 是现在 leaderboard 上最有声量的指标。

1 周交付分解
D1-D2：环境搭通

装 swebench Python 包（pip install swebench）
写 scripts/run_swebench.py — 拉数据集 → 每题构造一个 PipelineTask → 喂给 codegen DAG → 收 patch → 用官方 evaluator 验证
配 Docker harness（SWE-Bench 用 Docker 跑测试）
D3：单题跑通

选一个简单 instance（django__django-15814 之类一行修改的）
端到端跑通：issue text → AI patch → 应用到 repo → pytest → score
关键：复用 docker_sandbox.py 而不是 SWE-Bench 自带的 harness（性能更好，能跟 cost_governor 集成）
D4：批量并发跑

5-10 题并行（限 MAX_CONCURRENT=8 防爆 LLM rate limit）
进度落 PostgreSQL，断点续跑（你已经有 pipeline_checkpoint.py，复用）
失败自动 retry 一次（防 flaky）
D5：跑 Lite 全集

后台跑 6-12 小时
当晚收数据：resolved / total，分桶（语言、难度、文件改动量）
D6：跑 Verified 全集 + 出报告

同上
写 BENCHMARK.md：分数 + 配置 + 复现脚本 + 失败案例分析（最有价值的部分）
D7：缓冲日 / 调参重跑

期望分数 / 不要被吓到
2026 年的 SOTA 数据点（参考）：

系统	SWE-Bench Verified	模型
Claude 4.5 Sonnet (anthropic 官方 agent)
~75-80%
自家
Devin
~50-60% (公开数据)
私
OpenHands (OSS)
~55-65%
Claude/GPT
Aider (OSS)
~45-55%
多模型
Sweep
~35-45%
OpenAI
agent-hub 现实期望（用 Claude Sonnet 4.5）：30-50%。

关键：别为冲分而冲——OSS 项目能跑出复现脚本 + 公开 trace + 老实标注模型 比"分高于 OpenHands 0.5%" 重要 10 倍。HN 标题写 "Open-source 45% on SWE-Bench Verified, with full traces" 比 "55% but you can't reproduce" 强。

钱与算力
LLM：300 题 × 平均 5 万 token × Claude Sonnet 4.5 ≈ $80-120 / 跑一遍
算力：本机 Docker 够用（不用 GPU），需 32GB RAM + 100GB SSD（Docker images 占大头）
网络：克隆 300+ repo，准备 50GB 带宽
2.3 英文 Launch Post（最关键，别凑合）
平台 / 时机 / 顺序（重要）
平台	时机	注意事项
HN (Show HN)
周二 / 周三 太平洋时间 7:00 AM（PST 9-12 是黄金 4 小时）
标题加 Show HN:，第一条评论自己写"为什么做 + 故事"，准备 2 小时盯回复
Reddit r/programming
HN 当天晚 4 小时
标题别 clickbait，否则被秒删
Reddit r/devops
同上
强调"自部署 + 不锁数据"
Reddit r/selfhosted
同上
强调 docker-compose 一行启动
Twitter/X
HN 同步
@anthropic @paulgauthier (aider) @cognitionlabs，求 RT
lobste.rs
HN 后第二天
需要邀请码或熟人发
dev.to
HN 后一周
长文版，重发流量
HN 标题公式（实测有效）
模板：Show HN: <Project> – <one-line outcome>

候选标题：

✅ Show HN: Agent-Hub – AI dev team that opens PRs from your Jira tickets
✅ Show HN: Open-source DAG agent platform that scored 45% on SWE-Bench
❌ Show HN: Agent-Hub - A revolutionary AI agent framework (revolutionary = 死)
❌ Show HN: I built an AI agent platform with self-healing pipelines (太抽象)
判断标准：标题里有具体数字 / 名词 > 空洞形容词。

帖子结构（500-700 字最佳）
Hi HN, I'm Agent. For the last X months I've been building Agent-Hub, an
open-source AI agent platform that does one thing well: it takes a Jira
ticket or GitHub issue, writes the code, opens a PR, responds to reviewer
comments, and merges when you approve.
# Why another agent platform?
Most "AI agent" tools today are either (a) frameworks (LangGraph, CrewAI)
that leave you to plumb everything together, or (b) IDE plugins (Aider,
Cline, Copilot) that need a human at the keyboard. We wanted something
asynchronous: dump work into Jira, come back tomorrow.
# What's actually shipping today
- DAG-based pipelines (parallel stages, dependency resolution)
- Self-healing: when a reviewer rejects, the AI patches its own prompt
  and re-runs the failed stage automatically
- Bidirectional Jira/GitHub integration with webhook signature verification
  and self-loop prevention (so the bot doesn't reply to its own comments)
- Multi-provider LLM router: Claude, GPT, Gemini, DeepSeek, anything
  OpenAI-compatible
- Visual workflow builder (Vue Flow), or just write JSON
- 161 unit tests, 0 lint errors
# SWE-Bench Verified: <X>%
Honest number, not cherry-picked. Full traces here: <link>
Beats <baseline> with <model>; trails Claude's official agent by ~Y%.
Reproduction script in `scripts/run_swebench.py`.
# What it doesn't do (yet)
- Strong sandbox isolation (Docker only, no microVM)
- Multi-tenant RBAC (single org per deployment)
- Hosted SaaS (you self-host; cloud beta coming)
# Try it
docker compose up
Open localhost:5200, paste your GitHub PAT + Anthropic key, point it at
a small repo, file an issue. Demo video: <90 sec gif>
Happy to answer anything. Especially curious if anyone has run agent
platforms in production — what broke?
Repo: github.com/...
Demo 资产（不准备这个就不要发）
资产	长度	必须
90 秒 demo 视频（issue → PR → review → merge）
90s
✅ 必须
Builder 拖拽截图 GIF
10-15s
✅ 必须（HN 评论里自动展开）
SWE-Bench 跑分截图 + leaderboard 对比
静图
✅ 必须
Architecture 图（Mermaid）
静图
🟡 加分项
docker compose up 一行启动可复现
—
✅ 必须（HN 用户会 5 分钟内试，跑不起来直接 -10 票）
期望结果 / 失败应对
场景	概率	应对
前 2 小时 < 5 票 → 沉了
40%
不要重发！等 2-4 周改进后换标题再试
上首页（front page，> 100 票）
30%
准备 4 小时不间断回评论；服务器扩容（demo 视频 / GIF 走 CDN）
上 Top 10（> 300 票）
10%
GitHub 流量爆炸，准备 issue 模板 + 24 小时回
火爆（> 1000 票）
5%
准备 ZenHub-style "next steps" 文章趁热发出去
期望 GitHub stars 跃迁：launch 当天 100-500 ★，一周内若进 trending → 1k-3k ★。

2.4 三件事并行排期（3 周窗口）
周	Frontend (你/前端)	Backend (你/后端)	文案
W1
Builder Day 1-5
SWE-Bench D1-D3（搭环境 + 单题）
写 demo 仓库选型 + 准备 dogfood issue
W2
Builder Day 6-10
SWE-Bench D4-D5（批量 + Lite 全跑）
写 launch 文 v1，给 5 个朋友 review
W3
Demo 录制 + bug fix
SWE-Bench D6（Verified + 报告） + bug fix
launch 文定稿，预热 Twitter
W3 末
—
—
周二/周三 PST 7AM 发 HN
2.5 综合判断（你该选哪条路）
选	适合	6 个月后期望状态
路线 1（Resolvr 垂直产品）
想做产品 / 想验证创业 / 接受 6-12 月看不到现金流
1-3k ★ + 第一批付费 + waitlist
路线 2（3 周冲星）
想打个人品牌 / 找下一份工作 / 不想 commit 长线
1-3k ★ + 求职 portfolio 跃迁
两条同时（不推荐）
—
大概率两边都做不深
我的建议：先做路线 2（3 周窗口，现成代码够用，risk 可控），根据 launch 反馈再决定要不要切路线 1。

如果 launch 反馈集中在 "wow Jira 那个 demo 真有用" → 切路线 1
如果集中在 "builder 比 Dify 好用" / "DAG 模型有意思" → 留在通用平台路线，做 SaaS
Launch 是最便宜的市场调研——3 周拿到的真实信号比你自己脑补 6 个月强。

要不要从这里开始挑一件事先动手？我可以马上：

(A) 起 WorkflowBuilder.vue 骨架 + Vue Flow 集成（Builder Day 1-2）
(B) 起 scripts/run_swebench.py 骨架 + 单题跑通验证（SWE-Bench D1-D3）
(C) 把 Resolvr 的仓库分叉 + 砍掉非核心模块 + 重命名（路线 1 第一周）
