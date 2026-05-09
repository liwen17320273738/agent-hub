Wave 6｜Plan/Act 双模态产品化

## 已落地

### H1 · Plan/Act 从 IM 隐藏能力升级为统一网关能力
`backend/app/api/gateway.py`

- 新增 `_should_use_plan_mode(source, explicit)`，不再只给飞书/QQ硬编码
- Slack / OpenClaw / API 来源也能进入同一套 plan pending 流程
- `OpenClawIntakeRequest.planMode` 允许按请求决定"先出方案还是直接开跑"
- Slack 的需求澄清问题也会通过 notify 推回 Slack channel

### H2 · plan session 开始保存运行时元数据
`backend/app/services/plan_session.py`

- `make_payload(..., metadata=...)`
- metadata 用来携带：
  - `auto_final_accept`
  - `source_message_id`
- 避免"计划审批前后的执行语义不一致"

### H3 · OpenClaw 增加受信任审批 API
`backend/app/api/gateway.py`

- `POST /api/gateway/openclaw/plans/{source}/{user_id}/approve`
- `POST /api/gateway/openclaw/plans/{source}/{user_id}/revise`
- `POST /api/gateway/openclaw/plans/{source}/{user_id}/reject`
- 统一使用 `PIPELINE_API_KEY` Bearer 认证

### H4 · approve 后继承运行选项
`backend/app/api/gateway.py`
`backend/app/api/plans.py`

- plan 通过后创建 task 时恢复 metadata
- `auto_final_accept=true` 时：
  - task 上写回 `auto_final_accept`
  - `_run_pipeline_background(..., pause_for_acceptance=False)`
- 这样 OpenClaw 的 Plan/Act 不会丢失上线语义

### H5 · 前端 Plan Inbox + 运行时选项展示
`src/views/PlanInbox.vue`
`src/services/planApi.ts`

- Plan Inbox 展示 `auto_final_accept`（自动上线 / 人工验收）和 `source_message_id`
- 修复审批后跳转路由：`/pipeline/${taskId}` → `/pipeline/task/${taskId}`
- 空状态文案加 OpenClaw/API 来源说明

### H6 · PipelineDashboard 待审批计划徽章
`src/views/PipelineDashboard.vue`

- 新增"待审批计划"stat card，点击跳转到 Plan Inbox
- 每 15 秒轮询 `/api/plans` 刷新计数
- pending > 0 时数字高亮（橙色脉冲动画）

### H7 · gateway_plan_mode 默认开启
`backend/app/config.py`

- `gateway_plan_mode` 默认从 `False` 改为 `True`
- 所有 IM/OpenClaw/API 入口默认先出方案、等用户确认后再执行
- 可通过 `.env` 或环境变量 `GATEWAY_PLAN_MODE=false` 关闭

### H8 · Slack 统一走 Plan/Act
`backend/app/api/gateway.py`

- Slack webhook 的 `_clarify_or_create_task` 已经走 `_should_use_plan_mode("slack")`
- 需求澄清通知扩展到 Slack（原先只有 feishu/qq）
- Slack Block Kit 的 `plan_approve` / `plan_revise` / `plan_reject` 按钮对接同一套 `_handle_plan_card_action`

## 测试

### 后端单测
- `backend/tests/test_gateway_plan_mode.py`
  - `openclaw/intake + planMode=true` 返回 `plan_pending`
  - `approve` 后启动 pipeline，并保留 `auto_final_accept`
  - `revise` 后重新生成 plan，`rotation_count += 1`
- `backend/tests/test_plans_api.py`
  - `get_plan` 返回 `auto_final_accept` + `source_message_id`
  - `revise_plan` 保留元数据

## 端到端剧本
用户 / 外部 agent 调：

`POST /api/gateway/openclaw/intake`

```json
{
  "title": "做一个待办应用",
  "description": "先给我方案，再开工",
  "userId": "Agent-phone",
  "source": "openclaw",
  "planMode": true,
  "autoFinalAccept": false
}
```

返回：
- `action=plan_pending`
- `pipelineTriggered=false`
- `plan`
- `planSession.links.approve|revise|reject`

然后外部 agent / 手机快捷指令按需调用：
- approve → 真正开始跑项目
- revise → 重新出方案
- reject → 丢弃计划

IM 通道（飞书/QQ/Slack）：
- 用户发任务 → 澄清（如需要）→ 出方案卡片
- 用户在 IM 中点"开干/修改/取消"按钮
- Plan Inbox Web 端也可同步管理

## 配置
| 变量 | 默认 | 说明 |
|---|---|---|
| `GATEWAY_PLAN_MODE` | `true` | 全局开关，`false` 恢复直接执行 |

## 下一步
- 把 `plan_pending` 和 `awaiting_final_acceptance` 两个闸门统一成一个"任务状态卡"
- UI 设计 agent / Figma / .pen 对接
- OpenClaw 返回的 plan links 在手机端渲染快捷操作按钮
