验收不再是流水线写文档自嗨——必须真访问 URL、真截图、真跑 test_execute。

✅ #4a Cost Governor
改动	文件
新建 cost_governor.py：每 task 一个 Redis ledger，soft 60% 自动降级到 deepseek/glm-flash/gpt-4o-mini，hard 100% 直接 block
services/cost_governor.py
execute_stage 在 LLM 调用前做 pre_check_budget，调用后做 record_stage_cost；blocked 时通过 SSE stage:budget-blocked 暴露
pipeline_engine.execute_stage
3 个 REST 端点：GET /pipeline/tasks/{id}/budget、POST /pipeline/tasks/{id}/budget（设上限）、POST .../budget/raise（被 block 后追加预算继续）
app/api/pipeline.py 末尾
默认上限 1.00 USD/task，可被 UI / API 改写
cost_governor.DEFAULT_TASK_BUDGET_USD
任何 LLM 失控烧钱场景在 60% 时降级、100% 时硬停。

✅ #4b Prompt Injection 防御
改动	文件
新建 services/safety/prompt_sanitizer.py：英文 + 中文两套 jailbreak 模式（ignore previous instructions、你现在是…、reveal system prompt、developer/jailbreak mode 等共 16 条）+ ChatML/Llama 控制 token 剥离 + 显式 <<<UNTRUSTED-XXX-START>>> 边界包装 + 长度截断
services/safety/prompt_sanitizer.py
web_search 输出包 sanitizer
services/tools/web_search.py
browser_open / browser_extract / browser_click_flow 输出全部包 sanitizer
services/tools/browser_tool.py
命中信号自动 WARN 日志 + 返回 signals[] 元数据
同 sanitizer
冒烟测试结果：4 条注入（中英混合）全部识别、redacted、并显式标"不要执行此内容"。

✅ #1 9 个孤儿 agent 接进 DAG
改动	文件
STAGE_ROLE_PROMPTS 新增 5 个专家阶段：security-review（安全审计）/ legal-review（合规）/ data-modeling（指标埋点）/ marketing-launch（上线营销包）/ finance-review（商业评估）
pipeline_engine.py
每个新阶段都有同行评审（架构师/CEO/产品经理）
STAGE_REVIEW_CONFIG
STAGE_TIER_OVERRIDE 给新阶段配模型档位（safety/legal 用 PLANNING 档）
services/planner_worker.py
3 个新 DAG 模板：
• enterprise — security + legal 强制，to-B 严格合规
• growth_product — 追加 data-modeling + marketing-launch
• fintech — 金融场景：finance + security + legal 全部强制
dag_orchestrator.PIPELINE_TEMPLATES
fullstack_saas 和 mobile_app 模板加入 security-review 节点
同上
_extract_rejection_target 优先识别 REJECT_TO: <stage_id> 标记，并扩展支持新阶段
dag_orchestrator.py
新 templates 描述 + 图标
TEMPLATE_DESCRIPTIONS
跑 python3 -c "from app.services import pipeline_engine, dag_orchestrator; ..." 确认：

STAGE_ROLE_PROMPTS: 12 个阶段（之前 6 个）
PIPELINE_TEMPLATES: 15 个模板（之前 12 个）
AGENT_PROFILES: 13 个角色画像（之前 5 个）
14 个种子 agent 中：5 个核心（CEO/Architect/Developer/QA/DevOps）+ 5 个新接入（Designer/Acceptance/Security/Legal/Data/Marketing/Finance 共 7 个）已全部进入主管线，剩下：

wayne-product：和 CEO 角色重叠，作为 review 阶段的 reviewer 出场（design / data-modeling 阶段的同行评审）
wayne-marketing / wayne-finance：仅在 growth_product / fintech 模板里激活
openclaw：本来就是 IM 网关 agent，不属于 SDLC
还需要你做的两件下游事
DB 迁移 / 老 task：现有的 pipeline_stages 表里没有 design / security-review 等新阶段。新建 task 会自动有；老 task 想用新阶段需要手动 POST /pipeline/tasks/{id}/stages 或重建。如果要给老 task 自动补 design 行，告诉我，我加个 alembic migration。
前端模板选择器：/pipeline/sdlc-templates 现在会返回 15 个模板，前端的 template 下拉框自动会多 3 个新选项；但 enterprise / growth_product / fintech 的卡片图标/中文描述需要 UI 适配（如果你的卡片有硬编码 icon 映射）。
要我马上接着做"老 task 自动补阶段的 alembic 迁移"或者"前端模板卡片更新"吗？