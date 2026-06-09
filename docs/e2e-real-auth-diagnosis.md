# 真实认证链路 E2E 诊断报告

> 方法：用真实 admin JWT 走完整 API 链路（`POST /api/auth/login` → `POST /api/pipeline/tasks` → `POST .../auto-run` → 轮询 `GET /api/pipeline/tasks/{id}`），同时比对后端日志（`logs/backend.log`）与 PostgreSQL 真实状态。**不绕过认证、不直接调内部函数**。
>
> 任务样例：`3a2140ea`（"待办看板"，纯前端 SPA），2026-06-05 09:19 触发。

## 1. 现象：看板与真实执行是两套互不同步的状态机

| 时间 (UTC) | 引擎实际（后端日志） | 用户看板（API/DB 轮询） |
|---|---|---|
| 01:19:28 | 拿到 task-lock（TTL 1800s） | planning / pending |
| 01:22:07 | 写出 `brief`、`prd` 工件 | planning / pending |
| 01:22:08 | **Peer review 报错**（见 §2.2） | planning / pending |
| 01:22:09 | **验证失败但 force_continue 强行继续** | planning / pending |
| 01:22:12 | 进入 design 阶段 | planning / pending |
| 01:22:53 | `Agent-developer` 跑完（已到 development） | planning / pending |
| 01:22:53 之后 | **彻底静默，主进程 0% CPU 挂死** | planning / pending |
| 09:25（实测结束） | 进程 `%CPU=0.0`，无任何子进程 | **仍 active / planning / pending，spent=$0** |

DB 终态：`task=(active, planning, 无错误)`；`pipeline_stages` 只有 1 行且为 `planning/pending`，`quality_score=None`。

**结论**：引擎在内存里已跑过 planning→design→development，但 DB 那行始终是 `pending`。用户盯着看板 6 分钟，看到的是"planning 进行中、0 完成、$0"，既不报错也不前进，最后无声挂死。

## 2. 逐阶段问题（不只 planning）

### 2.1 planning — 能产出，但慢且脏
- 耗时约 2.5 分钟。慢在三处叠加：主 agent + 事后并行评审（额外 LLM 调用）+ peer review + `zhipu embedding 429 Too Many Requests` 风暴（每存一次 memory 打一次 embedding，被限流后重试）。

### 2.2 正式评审闸门因模型名失效直接报错
`logs/backend.log` 01:22:08：
```
[pipeline] Peer review for planning failed: LLM error:
The supported API model names are deepseek-v4-pro or deepseek-v4-flash,
but you passed google/gemma-4-26b-a4b
```
根因见 §3.2。

### 2.3 验证失败被 force_continue 静默越过
01:22:09：`Stage planning verification failed but force_continue=True, proceeding`。`force_continue=True`（auto-run 默认）会越过 blocked / 阶段错误 / peer-review 拒绝 / 质量闸门 / 验证失败 / human_gate **所有**停止条件。

### 2.4 design — 潜伏 bug（已修）
`pipeline_engine.py:467` 调 `stage_span.set_metadata(...)`，但 `TraceSpan`（`app/core/context.py`）当时**没有该方法**。被 466-469 的 `try/except` 吞掉（仅 debug 打印 traceback），属侥幸未致命，但证明 Phase 5 新增代码**从没真跑过**。

### 2.5 development — 跑完 agent 后挂死
01:22:53 `Agent-developer` execute-complete 后引擎彻底静默；主进程 `%CPU=0.0`，无 Claude/codex/pnpm/node 子进程。典型**无超时网络 await 挂起**（anthropic 熔断已开，codegen 优先调 Claude CLI 拿不到 → 卡在没有 `wait_for` 的等待上）。

### 2.6 test / deploy / preview / acceptance — 根本没到达
一个最简单的纯前端待办看板，连代码生成都没走完。

### 2.7 附带：Playwright Chromium 僵尸进程泄漏
pid 87013–87085 等多个 chromium 进程残留，之前 qa/deploy 跑完未清理。

## 3. Agent 层的真问题

1. **"军团协作"是非阻塞的咨询装饰**。`stage_layers.py:_run_parallel_reviews` docstring 明写 *"NOT a blocking gate — feedback is advisory ... not used for REJECT"*。security/developer/qa 评审各跑一次 LLM（max_steps=2），即便喊"有 SQL 注入/无法实现"，结果也只是被**字符串拼接**进交付文档（`content += "## 并行评审反馈"`）。只增成本和延迟、零约束力。
2. **agent 末尾"强制凑字数"兜底**。`agent_runtime.py:273-292`：ReAct 循环若无产出，再逼模型"一次性写 ≥500 字最终报告，禁止再请求工具"。不管真实工作有没有做成，最后总会吐出一篇像样文档——"演示能看、生产没用"的机制根源。
3. **质量分是假的**。`agent_runtime.py:306` 写记忆时 `quality_score = 0.8 if pass else 0.5`，是写死常数，非真实测量。
4. **delegate 是可选工具，不是编排**。agent 协作要靠 LLM 自己想起来调 `delegate_to_agent`。所谓 14 角色，实际是按阶段顺序各跑一次单 agent prompt。
5. **质量闸门走过场**。`quality_gates.py:_apply_thresholds`：PASSED 和 **WARNING 都 `can_proceed=True`**，只有 avg<0.4 或 deliverable 类 check 显式 FAILED 才拦；LLM 评分器不可用时返回 `WARNING, score=0.5`，而多数阈值是 0.6——天然放行。

## 4. 根因：为什么"反复修，结果一样"

- **根因 1：6 套并存的运行器，每次修的不是同一条路**。`dag_orchestrator` / `e2e_orchestrator` / `execute_full_pipeline`（auto-run 实际走的）/ `pipeline_engine` / `workflow_runner`，外加 10+ 触发端点（`/auto-run /dag-run /smart-run /run-stage /advance /codegen /plan /resume-dag`…）。修 A 路径，用户/测试走 B 路径。
- **根因 2：每个 Phase 叠新代码，但从没真正端到端跑一次**。`set_metadata` 不存在却合入、`google/gemma-4-26b-a4b` 早失效却仍在配置、`deepseek-chat` 默认名问题——只要真跑一次就会立刻暴露。说明测试是 unit/mock 级，没有"建任务→真跑→出可访问产物"的冒烟测试。
- **根因 3：系统目标是"流程不中断"，不是"产出可信"**。`force_continue=True` 强行越过失败、闸门 WARNING 即放行、评审非阻塞、agent 强制凑字数、降级 HTML 冒充设计稿——每一处都在"让流程看起来往前走"，而非"没做成就停下报错"。
- **根因 4：可观测性断裂**。`pipeline_stages` 不随真实执行更新（单大事务只在末尾 commit，挂死→永不 commit）；进程挂死无超时无告警；崩溃被 `try/except` 静默吞掉。

## 5. 本次已落地的修复

| # | 文件 | 改动 |
|---|---|---|
| b1 | `backend/app/core/context.py` | 给 `TraceSpan` 增加 `set_metadata(key, value)` 方法，消除 design/architecture 阶段的潜伏 `AttributeError`。 |
| b2 | `backend/app/config.py` | 别名模型（如本地 LM-Studio 的 `google/gemma-4-26b-a4b`）**仅在同时采用了别名 endpoint 时**才注入 `llm_model`；否则会与显式配置的 `LLM_API_URL`（DeepSeek）错配，导致 422 "unsupported model name"，进而打挂 peer review 并熔断 provider。 |
| b2 | `backend/app/services/planner_worker.py` | 移除虚构的 `google/gemma-4-26b-a4b` 兜底，改用已定义的真实本地强模型。 |
| b3 | `backend/app/services/execute_full_pipeline.py` | ①阶段生命周期改为**逐阶段 `commit`**（active / error / output），使看板实时可见、挂死也不丢已完成阶段；②`force_continue` 跳过的失败计入 `failed_stages`，末尾在 `task.scheduler_last_error` 与返回值 `degraded` 中**诚实暴露**，不再伪装成干净完成。 |
| 测试 | `backend/tests/test_process_flow.py` | 修正过期 monkeypatch 目标（`execute_full_pipeline` 已从 `pipeline_engine` 拆到独立模块）。 |
| 测试 | `backend/tests/test_credible_closed_loop.py` | **新增可信闭环冒烟测试**，hermetic（无 LLM/网络）守护上述三个 bug 的回归。 |

验证：
```bash
cd backend && python3 -m pytest tests/test_credible_closed_loop.py -v
```

## 6. 配置冲突（已按用户确认修复）

根 `.env` 原有两处问题：(a) 与 `backend/.env` 对 anthropic 别名冲突；(b) 根 `.env` 内有**重复**的 anthropic 块（`45-50` 与 `105-110`，内容相同），dotenv 取最后一个为准 → 实际生效的是 LM-Studio + `google/gemma-4-26b-a4b`。

已落地修改（经用户确认 “要”）：

- 第一个块（`45-50`，LM-Studio）整体**注释**为可恢复参考，并加说明：如需切回本地推理取消注释即可。
- 生效的第二个块改为 **DeepSeek 的 anthropic 端点**：`ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`、`ANTHROPIC_AUTH_TOKEN=<DeepSeek key>`、`ANTHROPIC_MODEL=deepseek-v4-pro`（haiku→`deepseek-v4-flash`）。

效果：anthropic provider 不再依赖内网 LM-Studio 是否在线，云端稳定；配合 b2（`config.py`）也不会把别名模型名错配到主 `LLM_API_URL`（DeepSeek）。`.env` 含密钥、已 gitignore——这是唯一直接改 `.env` 的地方，且保留了一键还原 LM-Studio 的路径。

## 7. 根治项进展（超出最初三 bug 范围）

| 项 | 状态 | 落地 |
|---|---|---|
| 缺失阶段行 | ✅ 已修 | `execute_full_pipeline.py`：执行某阶段前若 DB 无对应 `PipelineStage` 行则**自动建行**（带中文 label / owner_role / sort_order），消除“非模板阶段执行后无行可写、看板永久不可见”。 |
| 网络 await 总超时 | ✅ 已修 | `execute_full_pipeline.py`：给每个 `execute_stage` 套**总看门狗** `asyncio.wait_for(timeout=phase_timeout_seconds, 下限120s)` + **心跳** `stage:heartbeat`（每 30s）。即便内层某个子进程/socket 等待无超时，阶段也不会 0% CPU 永久挂死——超时即中止、记诚实错误、（force_continue 下）继续。 |
| Playwright 进程清理 | ✅ 已修 | 根因：`stealth_browser.open()` 的 `pw = await async_playwright().start()` 是局部变量，`close()` 只关 browser、从不 `pw.stop()` → node driver + chromium 泄漏。改为 `self._playwright=pw` 并在 `close()` 中独立 `stop()`；`local_preview.py` / `qa_executor.py` 的截图块改 `try/finally` 保证异常路径也回收。 |
| 运行器/入口收敛 | 📋 方案见 §8 | 涉及冻结正在使用的端点，风险高，本轮只产出方案不强改。 |

回归守护（hermetic，无 LLM/网络）：`tests/test_credible_closed_loop.py` 现含 5 项——三个原始 bug + 自动建行 + 看门狗中止挂起。

## 8. 运行器/入口收敛（核心一刀已落地）

**复核纠偏**：原以为 `/advance` 在内部分叉两个 runner——实际 `/advance` 是**手动推进**（只标当前阶段 done、移到下一阶段，不调任何 runner），不是分叉点。真正的 runner 注册在 `api/pipeline.py` 的 `register_kind`：

| kind | runner | 性质 |
|---|---|---|
| `auto-run` | `execute_full_pipeline` | ✅ 本轮加固的规范闭环 |
| `resume-pipeline` | `execute_full_pipeline` | ✅ 同上 |
| `dag-run` | `execute_dag_pipeline` | DAG 并行（高级） |
| `smart-run` | `lead_agent.run_smart_pipeline` | 拆解并行（高级，**不跑** codegen/build/QA/deploy） |
| `run-stage` | `execute_stage` | 单阶段 |

### 8.1 已落地：hero 一键路径切到规范 runner

**真正的根因 1 活样本**：`PipelineDashboard.vue` 的"创建后立即全自动执行"勾选时，调的是 **`smartRunPipeline`→`/smart-run`→`run_smart_pipeline`**，而非加固过的 `execute_full_pipeline`。`run_smart_pipeline` 的问题：

- 只做"LLM 拆解→并行跑 agent→按角色映射回阶段→标 done"，**完全不经过** codegen(Phase4)/build/QA(Phase6)/deploy(Phase7)/质量门禁/工件契约/同行评审；
- `stage_mapping` 缺 `design`，且无 codegen/preview → **永远产不出代码和可点开的 preview URL**（hero 的核心承诺直接落空）；
- 自身也带同款三连 bug：末尾单次 `flush`（看板 desync）、无看门狗/心跳（可挂死）、`if stage_id in db_stage_map` 缺行即丢（不可见）。

**修复**（`PipelineDashboard.vue`）：hero 一键按钮由 `smartRunPipeline` 改为 **`autoRunPipeline`**（`/auto-run`→`execute_full_pipeline`），并移除随之未用的 import。`/auto-run` 无需 body，签名兼容。

**保留高级路径**（demote, not delete）：`smart-run` 仍可用——`PipelineTaskDetail.vue` 的"智能运行"按钮（`handleSmartRun`，自带 subtasks 展示）是有意的高级动作，未改；`dag-run` 同样保留。

收益：用户一键点的路径 = 我加固并被 `test_credible_closed_loop.py` 守护的同一条路径。"修 A 路径、用户走 B 路径"的根因 1 在 hero 入口被消除。

### 8.2 已落地：DAG 路径可观测性对齐

复核 `execute_dag_pipeline` 后发现，三件套里**两件已具备**：
- 看门狗：`asyncio.wait_for(execute_stage, timeout=STAGE_TIMEOUT)`（已有）；
- 心跳：`_heartbeat_loop` 周期 emit `stage:heartbeat`（已有）；
- 逐阶段 commit：`_persist_stage_state` 在 active/done/error 各状态写入后 `flush()+commit()`（已有）。

**唯一缺口**：`_persist_stage_state` 遇到 DB 无对应行的阶段时 `if not row: return` 静默跳过 → 该阶段在看板永久不可见（与线性 runner 同类 bug）。

**修复**（`dag_orchestrator.py`）：改为**自动建行**——用 `DAGStage` 的 `label`/`role` 填充，`sort_order` 取现有最大值 +1 追加。回归测试 `test_dag_persist_state_auto_creates_missing_row`（直接驱动 `_persist_stage_state`，hermetic）守护。

至此两条主要执行路径（线性 `execute_full_pipeline` + DAG `execute_dag_pipeline`）在"逐阶段 commit + 看门狗 + 心跳 + 缺行自动建"四项上已对齐。

### 8.3 仍建议（后续，非必须）

- 在前端按钮文案 / API docstring 上把 `smart-run` / `dag-run` 明确标注为"高级/实验"，避免再被误接成默认路径。
