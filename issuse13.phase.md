# Issuse 13 · Phase 1 · 30 天「先能打仗」单次执行参考

> **目的**：把 `issuse13.md` 第七章「30 天 5 大致命修补」转成一份**自包含、可直接执行**的 phase 文档。
> **单次执行原则**：每个任务都给出文件锚点 + 改动要点 + 验收条件 + 测试命令 + 回滚路径，无需再回头查上下文。
> **范围**：7 个 P0/P1 任务，工作量合计 ≈ 5 个工作日。
> **执行顺序**：T1 → T2 → T3 → T4 → T5 → T6 → T7（T2/T3 可并行）。
> **退出条件**：所有任务 `pytest` + `pnpm build` 全绿，且新增冒烟脚本 `scripts/smoke_phase1.sh` 通过。

---

## 总览

| 序 | 任务 | 优先级 | 文件锚点 | 工作量 | 风险 |
|---|---|---|---|---|---|
| T1 | Plan/Act 双模式 | 🔴 P0 | `gateway.py` + `clarifier.py` + 新建 `plan_card.py` | S (0.5d) | 改 IM 入口语义 |
| T2 | 修 AgentRuntime memory task_id bug | 🔴 P0 | `agent_runtime.py:184` | XS (0.5h) | 改默认 fallback |
| T3 | Browser 工具落地（Playwright headless） | 🔴 P0 | `tools/browser_tool.py` + `tools/registry.py` | M (1d) | Playwright 依赖体积 |
| T4 | Container 沙箱 v1（Docker per task） | 🔴 P0 | `tools/docker_sandbox.py` + `tools/bash_tool.py` | M (1d) | Docker daemon 依赖 |
| T5 | Cost Governor 预算上限 + 自动降级 | 🟠 P1 | `cost_governor.py` + `llm_router.py` | S (0.5d) | 阈值需调优 |
| T6 | DAG 路径补 peer-review + human-gate | 🟠 P1 | `dag_orchestrator.py:333-343` | S (0.5d) | 与线性 pipeline 行为对齐 |
| T7 | 完成 issuse12 Wave 5（IM ↔ final_accept 闭环） | 🔴 P0 | `gateway.py` / `e2e_orchestrator.py` / `notify/dispatcher.py` | M (1d) | 状态机分流 |

---

## T1 · Plan/Act 双模式

> **价值**：IM 进来先发"方案卡 → 用户 approve → 才跑 e2e"。**翻车率↓80%**。当前问题：飞书一句话进来直接全跑，恶意/模糊需求成本极高。

### 改动点

**1. 新增 `backend/app/services/notify/plan_card.py`**

```python
"""Plan card builder — sends interactive approval card before running e2e."""
from __future__ import annotations
from typing import Any, Dict

def build_plan_card(task_id: str, title: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Build feishu interactive card with two buttons: approve / reject.

    plan: {summary, stages: [...], estimated_minutes, estimated_cost_usd}
    """
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🗺️ 执行方案待审 · {title}"},
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": plan["summary"]}},
            {"tag": "div", "fields": [
                {"is_short": True, "text": {"tag": "lark_md",
                    "content": f"**阶段数**\n{len(plan['stages'])}"}},
                {"is_short": True, "text": {"tag": "lark_md",
                    "content": f"**预估时长**\n{plan['estimated_minutes']} min"}},
                {"is_short": True, "text": {"tag": "lark_md",
                    "content": f"**预估成本**\n${plan['estimated_cost_usd']:.2f}"}},
            ]},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "✅ 批准执行"},
                 "type": "primary", "value": {"action": "plan_approve", "task_id": task_id}},
                {"tag": "button", "text": {"tag": "plain_text", "content": "❌ 拒绝/重新澄清"},
                 "type": "danger", "value": {"action": "plan_reject", "task_id": task_id}},
            ]},
        ],
    }
```

**2. 修改 `backend/app/api/gateway.py`**

- 在 `_run_pipeline_background` 之前插入 `_send_plan_card` 阶段
- 引入新状态 `awaiting_plan_approval`（DB enum 已有 `awaiting_approval` 可复用）
- 用户回 "批准/approve/lgtm" → 解锁 → 走原 e2e；回 "拒绝/重新" → 调 clarifier 多轮澄清

**3. Webhook 按钮回调路由**

在 `gateway.py` 飞书 action 路由里增加：
```python
if action == "plan_approve":
    await _resume_after_plan_approval(task_id)
elif action == "plan_reject":
    await _trigger_clarifier(task_id)
```

**4. 配置开关**

`config.py` 增加：
```python
plan_act_mode_enabled: bool = True   # IM 入口默认开启
plan_act_skip_for_internal: bool = True  # web dashboard 创建的不弹卡
```

### 验收

- [ ] 飞书发"做个 todo app" → 收到方案卡（不立即跑）
- [ ] 点"批准" → 跑完整 e2e，状态从 `awaiting_plan_approval` → `running`
- [ ] 点"拒绝" → clarifier 反问 1-2 轮
- [ ] web dashboard 创建任务不受影响（`plan_act_skip_for_internal=true`）
- [ ] 单测：`backend/tests/test_plan_card.py`（≥5 cases：build / approve / reject / skip / state machine）

### 回滚

`config.plan_act_mode_enabled = False` 即关闭，零代码回滚。

---

## T2 · 修 AgentRuntime memory task_id bug

> **价值**：修一个 1 行 bug，让 3 层 memory 系统真的"跨任务复用"生效。**XS 工作量、巨大杠杆**。

### Bug 现场

```184:194:backend/app/services/agent_runtime.py
        effective_task_id = task_id or self.task_id or self.agent_id
        await store_memory(
            db,
            task_id=effective_task_id,
            stage_id="agent-execution",
            role=self.agent_id,
            title=task[:200],
            content=final_output,
            quality_score=0.8 if verification.overall_status.value == "pass" else 0.5,
        )
```

**问题**：`task_id` 缺省时 fallback 到 `self.agent_id`，导致所有"匿名调用"被错记成"agent_id 这条 task"，跨任务检索时把 agent 自己的所有历史输出全捞回来 → memory 失效。

### 改法

```python
        effective_task_id = task_id or self.task_id
        if not effective_task_id:
            # 显式标注为非任务关联，使用专用 sentinel
            effective_task_id = f"__agent_chat__:{self.agent_id}"
        await store_memory(
            db,
            task_id=effective_task_id,
            ...
        )
```

并在 `memory.py` 的 `get_context_from_history` 里：跳过 `__agent_chat__:*` 命名空间作为"任务上下文"——只在显式查询单聊时拉。

### 验收

- [ ] 新 task 跑完，memory 表里 `task_id` 是真 task UUID，不是 agent slug
- [ ] 跨任务查询：`SELECT count(*) FROM task_memories WHERE task_id NOT LIKE '__agent_chat__:%'` 能区分
- [ ] 单测：`backend/tests/test_agent_runtime_memory.py`（验证 fallback 路径）

### 回滚

恢复一行即可。

---

## T3 · Browser 工具（Playwright headless）

> **价值**：解锁所有 web 类任务（市调、爬数据、E2E 测试、登录后台）。当前 `tools/browser_tool.py` 已有骨架但未注册到 registry。

### 改动点

**1. 依赖**

`backend/requirements.txt` 增加：
```
playwright==1.47.0
```
首次安装后执行：
```bash
python -m playwright install chromium --with-deps
```

**2. 完善 `backend/app/services/tools/browser_tool.py`**

确保 4 个工具齐全（issuse04-phase3 已起头）：
- `browser_open(url)` — 抓取标题+正文
- `browser_screenshot(url)` — 全页 PNG（base64 data URL，限 2MB）
- `browser_extract(url, selectors[])` — CSS 选择器批量取文本
- `browser_click_flow(steps[])` — goto → click → wait → extract（覆盖 SPA）

**全局保护**：
- 30s 单步超时
- 域名黑名单（默认拦 `127.0.0.1` / `169.254.*` / `localhost` / `0.0.0.0`，可配 `BROWSER_ALLOW_LOOPBACK=true` 解开）
- User-Agent 标识 `AgentHub-Browser/1.0`
- `--headless --disable-gpu --no-sandbox`（容器内）

**3. 注册到 `tools/registry.py`**

```python
try:
    from .browser_tool import BROWSER_TOOLS
    _TOOLS.extend(BROWSER_TOOLS)
except ImportError:
    logger.warning("Playwright not installed; browser tools disabled")
```

**4. 绑定到合适的 agent**

`backend/app/agents/seed.py` 的 `AGENT_TOOLS`：
- `Agent-product` 增加 `browser_open` / `browser_extract`（竞品调研）
- `Agent-qa` 增加 `browser_click_flow`（E2E 测试）
- 新建 `data-analysis` agent 已绑则忽略

### 验收

- [ ] `python -m playwright install chromium` 成功
- [ ] 单测 `backend/tests/test_browser_tool.py`：mock 一个 httpbin.org 抓取 ≥3 cases
- [ ] 端到端：让 Agent-product agent 用 browser_open 抓 example.com → 成功返回 title
- [ ] 域名黑名单单测：访问 169.254.169.254 必拒
- [ ] 软导入：未装 Playwright 时系统不崩

### 回滚

注释 registry.py 的 `BROWSER_TOOLS` 注册即可。

---

## T4 · Container 沙箱 v1（Docker per task）

> **价值**：关闭 host RCE 大门。当前 `bash_tool.py` 直接 subprocess 跑 host，issuse04-phase3 已起 `docker_sandbox.py` 骨架，本次任务**确保启用**。

### 改动点

**1. 配置默认值**

`backend/app/config.py`：
```python
sandbox_use_docker: bool = True   # 改为默认 True
sandbox_docker_image: str = "agenthub/sandbox:latest"
sandbox_memory_limit: str = "1g"
sandbox_cpu_limit: float = 1.0
sandbox_network: str = "none"
```

**2. 镜像**

新建 `docker/sandbox.Dockerfile`：
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl jq build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    requests pytest playwright \
    && playwright install chromium --with-deps
WORKDIR /workspace
```

`Makefile` 增加 `make sandbox-build`：
```makefile
sandbox-build:
	docker build -f docker/sandbox.Dockerfile -t agenthub/sandbox:latest .
```

**3. 完善 `tools/bash_tool.py` 的拦截链**

确认 28 条黑名单已在（issuse04-phase3 已加），新增：
- `cd /` 显式拦截（不止 `rm -rf /`）
- `mount` / `umount`
- `iptables` / `ufw`
- 拒绝时**绝不静默回落到 host**（这是 P0-1 的精髓）

**4. 启动检查**

`app/main.py` lifespan 增加：
```python
if settings.sandbox_use_docker:
    if not _docker_available():
        logger.error("SANDBOX_USE_DOCKER=true but docker daemon not reachable")
        if settings.environment == "production":
            raise RuntimeError("Docker required in production")
        logger.warning("Falling back to subprocess sandbox (DEV ONLY)")
```

### 验收

- [ ] `make sandbox-build` 成功，镜像 ≤ 800MB
- [ ] 跑 `bash_tool` 命令 `ls /` → 容器内执行，看到的是 `/workspace` 而非 host
- [ ] 危险命令矩阵单测 `backend/tests/test_bash_tool_security.py`：6/6 拦截
- [ ] 容器无网络：`curl https://example.com` 必失败（除非 `BASH_ALLOW_NETWORK=true`）
- [ ] 文件写入只在 `/workspace`，host 路径无副作用

### 回滚

`SANDBOX_USE_DOCKER=false` 即可，**仅供 dev**。生产禁止回滚。

---

## T5 · Cost Governor 预算上限 + 自动降级

> **价值**：防止恶意/失控用户烧光预算。`cost_governor.py` 已存在但只做 token 估算，本次补**预算硬阈值 + 降级链**。

### 改动点

**1. `backend/app/services/cost_governor.py` 增加**

```python
@dataclass
class TaskBudget:
    task_id: str
    max_usd: float
    consumed_usd: float = 0.0

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.max_usd - self.consumed_usd)

    @property
    def exhausted(self) -> bool:
        return self.consumed_usd >= self.max_usd


async def check_and_consume(task_id: str, estimated_usd: float) -> tuple[bool, str]:
    """Returns (allowed, reason). 超 80% 触发降级建议；超 100% 拒绝。"""
    budget = await _load_budget(task_id)
    if budget.consumed_usd + estimated_usd > budget.max_usd:
        return False, f"budget exceeded: {budget.consumed_usd:.2f}/{budget.max_usd:.2f}"
    if budget.consumed_usd + estimated_usd > 0.8 * budget.max_usd:
        return True, "downgrade_recommended"
    return True, "ok"
```

**2. 配置**

```python
# config.py
default_task_budget_usd: float = 5.0   # 单 task 默认上限
budget_downgrade_threshold: float = 0.8  # 超 80% 触发自动降级
```

**3. `llm_router.py` 集成**

在 `chat_completion_with_fallback` 入口处：
- 调 `check_and_consume(task_id, estimated)` 
- 若 `reason == "downgrade_recommended"` → 自动从 fallback 链选**便宜模型**（deepseek-v3 优先于 claude-sonnet）
- 若 `allowed == False` → 抛 `BudgetExceededError`，pipeline 暂停为 `paused_budget`

**4. SSE 事件**

新增：
- `task:budget-warning`（80% 触发）
- `task:budget-exhausted`（100% 触发）
- `task:provider-downgraded-by-budget`

**5. API**

`POST /pipeline/tasks/{id}/budget` — 临时增加预算（需鉴权）

### 验收

- [ ] mock 一个 task budget=$0.10 → 跑 GPT-4 必触发 downgrade → 切 deepseek
- [ ] mock budget=$0 → 立即返回 paused_budget，不发 LLM 请求
- [ ] 单测 `backend/tests/test_cost_governor.py`（≥6 cases）
- [ ] SSE 三个事件能在 dashboard 看到

### 回滚

`default_task_budget_usd = 999999` 实际等于关闭。

---

## T6 · DAG 路径补 peer-review + human-gate

> **价值**：当前 IM 触发的 E2E 走的是 DAG，**反而比手动 dashboard 路径质量低**（线性 pipeline 有 peer-review，DAG 没有）。issuse11 残留痛点。

### 改动点

**1. `backend/app/services/dag_orchestrator.py:333-343`**

在每个 stage 完成后，参照 `pipeline_engine.py:1010-1047` 的逻辑：
- 调 `_run_peer_review(stage, output)` 
- 失败 → reject + reset 到 `_extract_rejection_feedback`（issuse07-phase01 已有此函数）
- 成功 → 调 `quality_gates.evaluate` → 失败阻断、暂停 awaiting_approval
- 检测到 `human_gate=true` 的 stage → 暂停等批准

**2. 抽公共函数**

把 `pipeline_engine.py:1010-1047` 与 DAG 共用部分提取到 `services/quality_loop.py`：

```python
async def run_quality_loop(
    db, task, stage, output, *, peer_review=True, quality_gate=True, human_gate=False
) -> tuple[QualityVerdict, dict]:
    """共享 self-verify → peer-review → quality-gate → human-gate 流水。"""
    ...
```

线性 pipeline 和 DAG 都改用此函数。

### 验收

- [ ] DAG 跑一个故意写错的 stage → 触发 peer-review reject
- [ ] DAG 跑一个 `human_gate=true` 的 stage → 暂停 awaiting_approval
- [ ] 端到端等价测试 `backend/tests/test_dag_quality_parity.py`：
  - 同一份输出，DAG 与 pipeline_engine 的 verdict 一致
- [ ] 199 现有 tests 全绿（无回归）

### 回滚

恢复 `dag_orchestrator.py` 改动，`quality_loop.py` 留作 dead code。

---

## T7 · 完成 issuse12 Wave 5（IM ↔ final_accept 闭环）

> **价值**：把"飞书发任务 → 自动跑 → 我点确认 → 自动上线"链路最后 3 个断点接通。当前 `issuse12.phase.md` 为空。

### 6 个子任务（直接复用 issuse12.md 的 G1-G6）

#### G1 · e2e_orchestrator 暂停 deploy（2h）
**文件**：`backend/app/services/e2e_orchestrator.py`
**改法**：调 `execute_dag_pipeline` 后判断 `task.status == "awaiting_final_acceptance"`，是则**不再继续**进 codegen → build → deploy；返回 `{"ok": True, "paused_for_acceptance": True}`。

#### G2 · final_accept 触发后续部署（2h）
**文件**：`backend/app/api/pipeline.py` 的 `final_accept_task` endpoint
**改法**：accept 成功后调 `BackgroundTask` 触发 `run_e2e_after_acceptance(task_id)`（codegen → build → deploy 那段）。新增此函数到 `e2e_orchestrator.py`。

#### G3 · 飞书 awaiting_final_acceptance 模板（3h）
**文件**：`backend/app/services/notify/dispatcher.py` + `notify/feishu_im.py`
**改法**：
- 新增事件类型 `awaiting_final_acceptance` 模板
- interactive card 带"接受/打回"双按钮 + 任务摘要 + 综合质量分（来自 `task.overall_quality_score`）
- 复用 T1 的 plan_card 模式

#### G4 · 飞书 webhook 加 final_accept/final_reject 路由（2h）
**文件**：`backend/app/api/gateway.py` 飞书 action handler
**改法**：
```python
if action == "final_accept":
    await final_accept_task(task_id, ...)
elif action == "final_reject":
    await final_reject_task(task_id, reason=value.get("reason"), ...)
```

#### G5 · _FEEDBACK_KEYWORDS 分流（2h）
**文件**：`backend/app/services/feishu_event.py`（或 `gateway.py:101`）
**改法**：
- 「通过/上线/lgtm/accept/approve」→ `final_accept_task`
- 「重做/改/打回/reject」→ `final_reject_task` 或 stage rework
- 当前所有词都走旧 `feedback_loop.process_feedback` → 状态机错乱

#### G6 · auto_final_accept 字段开关（30min）
**文件**：`backend/app/api/gateway.py` `OpenClawIntakeRequest` schema
**改法**：暴露 `auto_final_accept: bool` 字段
- 企业默认 `False`（必须人工验收）
- demo 默认 `True`（一句话演示用）
- 通过 `settings.gateway_default_auto_final_accept` 控制

### 验收（端到端）

- [ ] 飞书发"做个登录页" → 收到 plan_card（T1）→ 批准
- [ ] 跑完 7 阶段 → 收到 awaiting_final_acceptance 卡片（带质量分）
- [ ] 点"接受" → 触发 deploy → 收到 deploy 完成通知
- [ ] 点"打回" 并附原因 → 状态回 development，不 deploy
- [ ] 端到端测试 `backend/tests/test_im_final_acceptance.py`（已存在，补全）

### 回滚

`gateway_default_auto_final_accept = True` 退回旧行为（自动跑完直接 deploy）。

---

## 全局测试 / 验收

### 冒烟脚本（新建）

`scripts/smoke_phase1.sh`:
```bash
#!/bin/bash
set -e
echo "=== Phase 1 smoke test ==="

# 1. 后端测试
cd backend && python3 -m pytest tests/ -v -k "plan_card or agent_runtime_memory or browser_tool or bash_tool_security or cost_governor or dag_quality_parity or im_final_acceptance"

# 2. 前端构建
cd .. && pnpm build

# 3. 现有 199 tests 不回归
cd backend && python3 -m pytest tests/ -v --ignore=tests/integration

# 4. Docker 沙箱镜像
make sandbox-build

# 5. 启动一次健康检查
cd .. && make dev &
sleep 10
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:5200/ -o /dev/null
make stop

echo "=== ALL GREEN ==="
```

### 退出条件

| 指标 | 目标 | 命令 |
|---|---|---|
| 后端单测全绿 | 0 失败 | `cd backend && pytest tests/ -v` |
| 新增测试 ≥ 30 cases | 见各 T 验收 | `pytest tests/test_plan_card.py tests/test_agent_runtime_memory.py tests/test_browser_tool.py tests/test_bash_tool_security.py tests/test_cost_governor.py tests/test_dag_quality_parity.py tests/test_im_final_acceptance.py` |
| 前端构建无错 | exit 0 | `pnpm build` |
| Lint 干净 | 0 warning | `make lint` |
| 沙箱镜像可建 | exit 0 | `make sandbox-build` |
| 飞书端到端验收 | 4/4 步骤通过 | 见 T7 验收清单 |

---

## 执行顺序与并行度

```
Day 1 上午: T2（XS, 30 min） + 启动 T3 Playwright install
Day 1 下午: T4 Docker 镜像构建 + bash_tool 拦截清单
Day 2 全天: T1 Plan/Act 双模式（含 plan_card + 状态机）
Day 3 全天: T7 Wave 5 G1-G4
Day 4 上午: T7 G5-G6
Day 4 下午: T5 Cost Governor
Day 5 全天: T6 DAG 路径补齐 + 全量回归 + 冒烟
```

**并行机会**：
- T2 / T3 / T4 互不干扰，可三人并行
- T1 / T7 都改 gateway.py，**必须串行**（T1 先，T7 后，避免 merge 冲突）
- T5 / T6 相对独立，可并行

---

## 风险登记

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Playwright 安装失败 / 镜像>1GB | 中 | T3 阻塞 | 软导入 + chromium-only |
| Docker daemon 不可用 / 性能差 | 中 | T4 体验差 | dev 模式自动 fallback |
| 飞书 interactive card 审核 | 低 | T1/T7 上线慢 | 先用文本模板兜底 |
| Cost Governor 误杀正常 task | 中 | 用户体验差 | 默认 $5 上限 + UI 一键加预算 |
| DAG / pipeline 行为差异 | 高 | 现有 199 tests 回归 | T6 抽公共函数 + parity test |
| memory bug 修完产生数据迁移 | 低 | 历史数据 stale | 不动历史，只影响新写入 |

---

## 一句话目标

> **5 天后**，Agent-Hub 主链路从「自动化产线」变成「**有计划、有沙箱、有眼睛、有预算、有验收**」的初代军团；issuse13 列出的 4 件硬骨头中 **3 件落地**（沙箱、浏览器、Eval 留待 90 天），剩下 1 件（真·多 agent 委派）进入 Phase 2 准备阶段。
