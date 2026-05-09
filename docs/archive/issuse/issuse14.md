Issue 14｜Plan/Act 双模态产品化：让飞书 / QQ / OpenClaw 发任务先出方案，再开干

目标
把现有 gateway 里的 Plan/Act 雏形，从“隐藏开关 + 主要服务飞书卡片”补成一条正式能力：

飞书 / QQ / Slack / OpenClaw 发需求
  ↓
clarifier 澄清
  ↓
planner 生成执行计划（产品 / 设计 / 开发 / 测试 / 运维 / 上线）
  ↓
用户确认「开干 / 修改 / 取消」
  ↓
才真正触发 pipeline + e2e + final acceptance

为什么做
现在仓库已经有：
- `clarifier`：能把含糊需求问清楚
- `planner`：能生成 4-8 步执行计划
- `plan_session`：能把待确认计划暂存在 Redis
- `feishu plan card`：能点击开干 / 修改 / 取消

但它还不是一个真正可对外宣称的能力，主要有 4 个缺口：

1. `OpenClaw / 龙虾` 入口没有 Plan/Act
它现在直接 `create task -> background run`，没有“先看计划”的停顿点。

2. Plan/Act 运行选项不会跨审批流保留
像 `autoFinalAccept` 这类执行选项，在 plan pending 后并没有跟着审批一起流转。

3. 计划审批过度依赖 IM 文字或卡片
外部 agent / 手机快捷指令 / 自建入口，缺少受信任的 `approve / revise / reject` API。

4. 多渠道行为还不统一
飞书/QQ 有 plan 流，Slack/OpenClaw 仍偏半成品，体验不一致。

本期范围
P0
- `gateway.py`
  - 抽出统一的 `should_use_plan_mode`
  - 支持 `OpenClawIntakeRequest.planMode`
  - `openclaw/intake` 在 planMode 下返回 `plan_pending`，不直接开跑
  - 新增 `openclaw/plans/{source}/{user}/approve|revise|reject`
- `plan_session.py`
  - plan payload 支持存 metadata / runtime options
- `plans.py`
  - web 侧审批也要继承 plan metadata（比如 `auto_final_accept`）
- tests
  - OpenClaw 提交计划
  - approve 后启动任务
  - revise 后重生成计划

P1
- Slack 也走统一 Plan/Act 触发条件
- API 返回当前 plan session 的可调用 links，方便外部 agent 串接

非目标
- 这期不做完整 UI 设计 agent
- 不做 Browser/Figma/.pen 深度接入
- 不改 final acceptance 状态机
- 不做长任务 checkpoint

完成标准
- OpenClaw 可以像飞书一样先出 plan，再由外部调用 approve
- approve 后仍能正确继承 `autoFinalAccept`
- revise 会生成新 plan 并累计 rotation_count
- 现有飞书/QQ final acceptance 闭环不回归

验收剧本
1. 调 `POST /api/gateway/openclaw/intake`，传 `planMode=true`
2. 返回 `action=plan_pending` 和 plan JSON，不触发 pipeline
3. 调 approve API 后，task 创建成功并开始执行
4. 若 `autoFinalAccept=true`，则审批通过后走直发；否则继续保留最终验收闸门
5. revise / reject 均可正常工作
