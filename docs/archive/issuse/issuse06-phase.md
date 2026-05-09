#3 观测看板 ✅
后端

backend/app/services/observability_dashboard.py — 单次聚合：日趋势、阶段热力图、Agent/Model 战绩、最近失败、审批 & 预算治理事件、任务状态分布
在 backend/app/api/observability.py 新增 GET /api/observability/dashboard?days=N
前端

src/services/insightsApi.ts — TS 类型 + API 客户端
src/views/InsightsObservability.vue — 5 个 tab：总览 / 阶段表现 / Agent 战绩 / 模型对比 / 失败拒绝列表（+ 学习闭环 tab，见下）
自带轻量 SVG SparkBars + RateBar，零新增依赖
侧边栏新增「Agent 观测台」入口，路由 /insights/observability
实测命中 30 天窗口：13 任务 / 40 阶段 / 34 LLM 调用 / 0.0045 USD / 6 模型档位区分，全活。

#1 学习回路 ✅
新表（migration 6a9b0c1d2e3f，已 upgrade）

learning_signals — 每次 REJECT / GATE_FAIL / RETRY / APPROVE_AFTER_RETRY / HUMAN_OVERRIDE 一条，自带 distilled 标志
prompt_overrides — 蒸馏出来的提示补丁，状态机 proposed → active → archived + disabled，带 impact 计数器（uses / approves / rejects）
核心服务 backend/app/services/learning_loop.py

capture_signal() — 记录信号；REJECT/GATE_FAIL/HUMAN_OVERRIDE 累计到 3 条自动触发蒸馏
distill_signals_for_stage() — 用 LLM 教练（Prompt 在 _DISTILL_SYSTEM）把 N 条失败样本提炼成「## 强制要求（来自历史复盘）」补丁，落库为 proposed
set_override_status() — 激活同阶段会自动归档旧版本，60 秒 Redis 缓存确保 hot path 不卡 DB
get_active_addendum() — 给 pipeline_engine 用，读取活跃补丁
record_override_outcome() — 给 pipeline_engine 用，记录补丁的实战胜率
Pipeline Engine 接入（backend/app/services/pipeline_engine.py）


pipeline_engine.py
Lines 737-751
    role = stage_conf["role"]
    system_prompt = stage_conf["system"] + _DELEGATE_HINT
    # --- Layer 0: Learning loop — inject historically-distilled prompt patches ---
    from .learning_loop import get_active_addendum
    active_addendum = await get_active_addendum(db, stage_id=stage_id)
    if active_addendum and active_addendum.get("addendum"):
        system_prompt += (
            f"\n\n<!-- learning-override id={active_addendum.get('id')} "
            f"v{active_addendum.get('version')} -->\n"
            f"{active_addendum['addendum']}"
        )
并在 review_stage_output 末尾捕获 REJECT 信号 + 给活跃 override 计 approve/reject；在 quality gate 失败时捕获 GATE_FAIL 信号。

REST API /api/learning/{signals,overrides,distill,summary,overrides/{id}/{activate|archive|disable}}

UI：观测台「学习闭环」tab — 每阶段一行，显示信号统计、活跃补丁、未蒸馏数；点「蒸馏 → 提案」按钮调 LLM；侧抽屉详情可看补丁全文 + 信号样本，可一键启用/归档/弃用。

端到端跑通验证
直连 DB 已跑通：capture × 2 → propose → activate → 注入 system_prompt → archive，addendum 出现/消失符合预期。HTTP 端点：登录后 /api/observability/dashboard 与 /api/learning/summary 返回真数据。

系统升级，从「能跑」到「越跑越聪明」
维度	之前	现在
观测
只有 redis trace + 周报
全景仪表盘（5 tab + 学习中心），SVG 图表零依赖
失败回放
retry 完就忘
每次 REJECT/GATE_FAIL 入库成 LearningSignal
提示进化
出厂设置永不变
阈值触发 LLM 蒸馏 → 提案 → 人工/自动激活 → 注入 system prompt → 计 ROI
灰度回滚
—
一键 archive/disable，60s Redis 缓存自动失效
下一步候选（如果继续推到「军团」）
真并行 DAG 执行器（剩下 7 件中最大的杠杆）
学习回路自动激活策略：active override 在最近 N 次使用中 approve_rate ≥ 阈值就自动晋升
Skill 沙箱按角色白名单：security-agent 不该能调 deploy 工具
要直接接哪一个？