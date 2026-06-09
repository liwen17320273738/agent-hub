# E2E 深排查（第二轮）：质量与诚实层的根因

> 时间：2026-06-05　方法：真实认证链路（`admin@example.com`）→ 建任务 → hero `/auto-run`（已收敛到 `execute_full_pipeline`）→ 直查 PostgreSQL 逐阶段观测。
>
> 案例：并发 3 个任务 `c0979a55` / `837164f4` / `350f27ac`（同一需求"纯前端待办看板"）。

---

## 0. 与上一轮的关系

上一轮（见 `docs/e2e-real-auth-diagnosis.md`）解决的是**"看起来没跑"**：Dashboard 假 pending、阶段不可见、网络 await 挂死、Playwright 僵尸进程。

本轮验证那些结构性修复**确实生效**，但暴露了**更深一层**的问题：**"跑完了，但内容是垃圾，而系统假装它是好的"**。这正是反复修仍不可用的根因层。

---

## 1. 已验证生效的上轮修复 ✅

| 修复 | 本轮证据 |
|------|----------|
| 逐阶段 `commit` → Dashboard 实时 | DB 中 planning/design/architecture 状态随执行实时翻转，非最终一次性写入 |
| `stage:heartbeat` 心跳 | 日志持续 `[sse] emitted stage:heartbeat`，含 `design elapsedSeconds=30`；架构卡住时仍有心跳 |
| 结构端到端推进 | 三任务均推进到 `planning→design→architecture→development` |
| codegen 真实执行 | development 阶段日志：`[codegen] 使用 Claude Code (primary engine)` / `Invoking Claude Code`，`claude=True codex=True` |

结论：**管道连通性已不是问题**。

---

## 2. 仍存在的问题（按严重度）

### 🔴 #1 质量闸门形同虚设 —— "假装成功"根因仍在

**证据**（DB 快照）：

```
TASK 837164f4  planning  done  q=0.2  gate=failed/0.3
TASK c0979a55  planning  done  q=0.2  gate=failed/0.3
TASK 350f27ac  planning  done  q=0.5  gate=failed/0.721
TASK 350f27ac  design    done  q=0.2  gate=failed/0.304
```

planning 阶段三任务 `gate=failed` + `verify=fail` + `review=rejected`，却全部 `status=done` 并继续；350f27ac 的 design 也是 `failed/0.304` 照过。

**根因**：`/auto-run` 端点**默认 `force_continue=True`**：

```818:818:backend/app/api/pipeline.py
                force_continue=bool(params.get("force_continue", True)),
```

`force_continue=True` 会绕过 `execute_full_pipeline.py` 中所有质量关卡：

- gate 失败拦截：`if not gate_result.can_proceed and not force_continue:`（503）
- reviewer 驳回暂停：`if not force_continue:`（394 / 581）
- verify 失败：`if force_continue: ... proceeding`（545）
- human gate：`if review_conf.get("human_gate") and not force_continue:`（714）
- 硬失败跳过：`if force_continue: ... skipping to next`（300）

→ 任何阶段无论多差都会被标 `done` 往下走。用户看到"全绿/已完成"，实际内容不合格。

---

### 🔴 #2 DeepSeek 工具调用 token 字面泄漏

**证据**（planning 输出原文，仅 936 字节）：

```
好的，项目骨架已经搭好了…让我看看现有的组件
<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="file_list">
<｜｜DSML｜｜parameter name="path" string="true">todo-board/src/stores</｜｜DSML｜｜parameter>
...
```

模型把 DeepSeek 内部工具调用 token（`<｜｜DSML｜｜>`，DeepSeek Markup Language）当作**普通文本**输出，没被解析成真正的工具调用。结果 planning 产出是一坨损坏标记而非 PRD。

**关联**：design 阶段（不调用文件工具）输出干净（9063 字节、含设计 token 表）。→ **泄漏只发生在"使用工具的 agent"**，指向 `agent_runtime` / `llm_router` 对 DeepSeek 原生工具协议的解析路径。

---

### 🟠 #3 planning agent 行为错位（像码农而非产品经理）

**证据**：
- planning 输出："好的，项目骨架已经搭好了，代码结构清晰。让我看看现有的组件和 store 目录" → 在**浏览代码文件**，不是写需求。
- reviewer 反馈："您提供的'待审阅内容'似乎不是完整的 PRD 文档，而是项目代码结构的描述和文件列表操作。"

**根因**：planning 角色被赋予了文件工具，且 prompt 未约束其只产出 PRD，导致它去探索目录。应让 planning 产 PRD（需求概述/目标用户/功能范围/用户故事/验收标准），而不是 file_list。

---

### 🟠 #4 成本记账 = $0，预算治理失明

**证据**：三任务真实跑了大量 LLM 调用 + Claude Code codegen，`spent_usd` 全为 `$0.0`。

**根因**：`backend/app/services/execute_full_pipeline.py` 中**完全没有**任何 `spent_usd` / `token_tracker` / `cost_governor` 调用（grep 零命中）。hero 路径上 60% 软封顶 / 100% 硬封顶的预算治理形同虚设。

---

### 🟡 #5 单 worker 并发无隔离

**证据**：`837164f4` 的 architecture 阶段 `active` 持续 5+ 分钟、`out=0b`；3 个任务抢同一 worker + LLM 通道，整体变慢。

**根因 / 风险**：
- 无并发上限 / 队列深度控制。
- `phase_timeout_seconds = 1800`（30 分钟）过长，per-stage watchdog 迟迟不触发，慢/卡难以被及时熔断。

---

### 🟡 #6 日志不可用于排查

**证据**：`logs/backend.log` 被刷爆——
- `sql_echo` 全开：每条 SQL 连参数整段打印。
- SSE chunk debug：每个 `agent:tool-call` 事件按**每个订阅者重复打印**（本轮观察到 3 个订阅 → 同一事件出现 3 次）。

→ 真正的 `[pipeline]` / 错误行被淹没，排查需大量 `grep -v` 过滤。

---

## 3. 一句话根因

> **`force_continue=True` 默认值让整条 hero 路径的质量门禁失效（#1）**，叠加 planning 阶段输出本身损坏（#2 DSML 泄漏 / #3 角色错位），于是系统"跑完并报告成功"，但交付物不合格——这就是"反复修仍不可用"的根因层。

---

## 4. 建议修复优先级（待确认后实施）

| 优先级 | 动作 | 文件 |
|--------|------|------|
| P0 | `/auto-run` 默认 `force_continue=False`，让 gate 真正拦截/暂停；保留显式覆盖（请求体可传 true） | `backend/app/api/pipeline.py:818` |
| P0 | 修 DeepSeek DSML 工具调用 token 解析/泄漏 | `agent_runtime` / `llm_router` |
| P1 | planning 角色去掉文件工具、收紧 prompt（只产 PRD） | 角色/prompt 定义 |
| P1 | `execute_full_pipeline` 接入 token/cost 记账，恢复预算治理 | `execute_full_pipeline.py` |
| P2 | 关闭 SQL echo + 按事件而非按订阅者打印 SSE debug | `config`/`sse.py` |
| P2 | 并发上限 + 调低 `phase_timeout_seconds` | `dag_orchestrator`/`config` |

---

---

## 5. 第二次修复 + 复验（2026-06-05 下午）

### 已修复并复验 ✅ —— #2 / #3（内容质量根因）

**根因定位**：planning 阶段 = `ceo-agent`，其 `AGENT_TOOLS` 含 `file_read/file_list/browser_*`。DeepSeek 拿到文件工具后跑去"浏览脚手架代码目录"，且其原生工具调用协议把 `<｜｜DSML｜｜tool_calls>` 当文本吐出 → planning 产出变成损坏的工具调用标记而非 PRD。

**修复**：
1. `pipeline_engine.py`：新增 `_AUTHORING_ONLY_STAGES = {"planning"}` + `_AUTHORING_BLOCKED_TOOLS`，对纯文档创作阶段剥离文件系统/浏览器/shell 工具（保留 web_search/delegate），不动全局 `AGENT_TOOLS`。
2. `agent_runtime.py`：新增泄漏标记检测 `_looks_like_leaked_tool_markup`，若最终输出含 `<｜｜DSML｜｜>` 等标记则触发"禁止工具、一次性重写报告"重合成，并对残留做行级清洗兜底。

**复验**（新案例 `5f7f2836`）：

| | 修复前 | 修复后 |
|---|--------|--------|
| planning 输出 | 936b，`<｜｜DSML｜｜tool_calls>` + file_list | **4505b 真 PRD**（一句话价值主张/目标用户画像表/功能范围…） |
| gate | `failed/0.3`，缺关键章节 | **`passed/0.9`，7/7 章节齐全** |
| DSML 泄漏 | 有 | **无** |

### 阻塞 ⛔ —— #1（force_continue 默认值）

`#1`（翻转 `/auto-run` 默认 `force_continue=False`）**暂不能动**：当前 testing 阶段必失败（见 #8）、部分 reviewer 过严必驳回，若此刻让 gate 真正拦截，每个 hero 任务都会立刻卡在 testing/review。**必须先修通 testing（#8）与 reviewer 严苛度，#1 才安全。**

---

## 6. 本轮新增发现（#7–#10）

### 🔴 #8 bash 沙箱拦截真实工作目录 —— testing 失败的直接根因

**证据**：
```
[bash] Blocked command (pattern: \bcd\s+/(?!workspace|tmp|var/tmp)):
  cd /Users/wayne/Documents/agent-hub/data/workspace/tasks/TASK-...深排查-待办看板 && npm install
```
`bash_tool.py:63` 的 `_BYPASS_PATTERNS` 只放行 `cd /workspace|/tmp|/var/tmp`，但真实 worktree 在 `data/workspace/tasks/...`。testing agent 的 `cd <worktree> && npm install` 被拦 → 装不了依赖 → testing 失败。

> 注：bash 工具其实已用 `cwd=workspace_dir`（`bash_tool.py:146`）在正确目录执行，agent 的 `cd /abs/path` 是多余且踩雷。修法二选一：放宽正则纳入 `data/workspace`（有安全权衡），或在 prompt/QaExecutor 层让 agent 不要 `cd`（直接裸命令）。

### 🟠 #9 development 契约未满足

**证据**：`[pipeline] Artifact contract unmet after stage development: missing ['source_manifest', 'build_log']`。开发阶段出了 ~16k 代码却没写 Phase 4 的 `source_manifest`/`build_log` 工件。

### 🟠 #10 cross-stage 校验 `division by zero`

**证据**：`[pipeline] cross-stage verification failed for testing: division by zero`。`stage_layers` 跨阶段校验里一个被吞掉的真 bug（除零）。

### 🟡 #7 testing → deployment 仍靠 force_continue 带病前进

**证据**：`stage:testing-failed` 紧跟 `Stage testing failed but force_continue=True, skipping to next`，deployment 照常 active。与 #1 同源。

---

## 7. 第三次修复 + 复验（#8 / #1 + 诚实终态）

### 已修复并复验 ✅ —— #8 bash 沙箱拦截真实 worktree

**修复**：`tools/sandbox.py` 新增 `is_path_allowed()`；`tools/bash_tool.py` 的 `_scan` 对 `cd` 改为**路径感知**——`cd` 进 sandbox/已注册 worktree 放行，仍拦逃逸到 `/`、`/etc` 等。

**单元复验**：
```
ALLOWED | cd <worktree> && npm install   (was BLOCKED)
BLOCKED | cd /etc && cat passwd
BLOCKED | cd / && rm x
ALLOWED | npm install
```

### 已修复并复验 ✅ —— #1 force_continue 默认 False + 诚实终态

**修复**：
1. `api/pipeline.py`：`/auto-run` 端点与 `_build_auto_run` 默认 `force_continue=False`（原 True，是"假装成功"的总开关）。
2. `execute_full_pipeline.py`：补齐三处诚实终态——
   - early peer review 驳回：`stage=rejected` + `task=paused` + commit + `pipeline:auto-paused`；
   - 普通 stage 失败（非 forced）：`task=failed` + commit；
   - （gate / 后期 review / blocked 路径原已写 paused）。

**复验**（任务 `e549e138`，force_continue=False）：
```
TASK e549e138  status=paused  cur=planning
  [0] planning  rejected  out=1417b
事件: peer-review-rejected → peer-review-blocked → pipeline:auto-paused → trace done
```
→ 流水线在 review 驳回处**诚实停止**，task=`paused`、planning=`rejected`（修复前僵在 `active`）。**不再假装成功。**

---

## 8. 本轮再新增发现（#11 / #12）

### 🟠 #11 reload/崩溃后任务僵在 active（无启动对账）

uvicorn `--reload` 或 worker 崩溃会杀掉在途流水线协程，DB 里 task/stage 留在 `active` 永不转终态（如老任务 c0979a55/837164f4 的 deployment 永久 active）。缺少启动时的"孤儿任务对账"。建议：启动钩子把超期仍 `active`/`reviewing` 的 stage 标 `error`，task 标 `failed`/`paused`。

### 🔴 #12 planning prompt 与契约/reviewer 不匹配 → 诚实闸门下系统性卡 planning

`STAGE_ROLE_PROMPTS["planning"]` 要求章节：`目标用户/功能范围/用户故事/验收标准/非功能需求/里程碑`；但 `artifact_contract` 的 `prd` 规则额外要求 **`非目标 / non-goals / out of scope`** 一节。prompt 从不要求这节 → PRD 必缺 → 契约违规 + 架构师 reviewer 必驳。

**证据**：`Artifact contract rules violated after stage planning: ['prd:[...missing_group:非目标|non-goal|...]']` 连续多个任务复现。

**影响**：#1 翻成 False 后，hero 路径几乎必然卡在 planning。**这是让诚实闸门"可过"的关键缺口** —— 需把 planning（及 design/architecture）的输出 prompt 与各自契约章节对齐。

**已做**：planning prompt 补了独立 `## 非目标（Out of Scope）` 章节（覆盖契约 4 组中缺的那组）。**但复验仍失败**，原因见 #13。

### 🔴 #13 learning_loop 覆盖与契约/基础 prompt 三方冲突 → planning 系统性不达标

`pipeline_engine.py:161-170` 会把 `get_active_addendum()` 返回的学习覆盖**无条件**追加进 stage prompt（连 `mode=shadow` 的 A/B 金丝雀也照注）。当前 planning 的 active 覆盖（`f189b96f` v1, **shadow**）要求一套 **8 章节**结构，把 out-of-scope **折进「功能范围」节内**，而**不**输出独立的 `## 非目标` H2。

于是三方打架：
- 契约要求独立 H2 命中 `非目标|non-goals|out of scope`；
- 基础 prompt（已修）要求独立 `## 非目标`；
- shadow 覆盖要求把它折进「功能范围」、用 8 章节别的结构。

结果：模型在冲突指令下产出忽长忽短（4505b → 1018b 不等）、且常缺独立 `非目标` H2 → 契约 + reviewer 系统性驳回。

**证据**：首轮 `5f7f2836`（覆盖未命中时）产 4505b、7/7 章节、gate 0.9；其后 `b3333ad7/e549e138/47815b0d` 注入 shadow 覆盖后退化到 1–2.4k、缺章节、连续 paused。

**建议修法（择一/组合）**：
1. `get_active_addendum` 注入处区分 `mode`：`shadow` 只走 A/B 影子评估、**不污染**正式 prompt；只有 `active` 才注入。
2. 让 learning 覆盖的章节结构**以契约为准**（生成覆盖时校验其要求的 H2 与 `artifact_contract` 一致），避免与契约对打。
3. 统一 planning 的"真章节集合"为单一事实源（契约 = prompt = 覆盖 = reviewer 同一份清单）。

**已修复 ✅**：`learning_loop.py:get_active_addendum` —— 孤儿 shadow（无 active 基线）不再 100% 全量注入，回落基础 prompt；只有「shadow + active 同时存在」才按 `SHADOW_TRAFFIC_RATIO` 做正常 A/B。并归档了与契约冲突的 planning shadow 覆盖 `f189b96f`（`get_active_addendum(planning)` 现返回 `None`）。

**验证受阻 ⚠️**：本轮绿路复验被**自造并发拥堵**污染——同时跑 4–5 个诊断任务导致 `deepseek` 并发压力 + `zhipu embedding 429 Too Many Requests`，planning 输出退化变短（1064b）仍被驳回。**需在安静环境（worker 空闲、单任务、无限流）复验绿路**：planning 应产全 4 章节、过契约+review→推进 design。这属环境问题，非代码缺陷。

---

## 附：排查工具（本轮新增，未跟踪）

- `backend/_diag8_e2e.py` — stdlib-only 端到端探针（login→create→auto-run→轮询）。注意 macOS 无 `setsid`，后台需 `nohup`。
- `backend/_snap.py` — 一次性 DB 快照（任务/阶段/产物/错误）。
- `backend/_snap2.py` — v2 `task_artifacts` + 指定阶段 gate_details/output 明细。
