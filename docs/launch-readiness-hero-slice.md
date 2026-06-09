# Hero 切片上市闸门（A + C 合并）

> 周期：2 周（2026-06-05 起）  
> 对外叙事：**一句话 → 90 秒内出 PRD 方案 → 用户确认 → 可访问 demo + 分享链接**  
> 对内愿景不变：14 角色 Agent 军团；本阶段只打穿一条可卖路径。

---

## 1. 切片范围（路线 A）

### 做

| 阶段 | 产出 | 验收 |
|------|------|------|
| planning | PRD（含非目标） | gate ≥ 0.7，≤ **90s** |
| design | UI 规范 + mockup | 有 PNG/HTML 其一 |
| development | 可编译前端 | `source_manifest` + `build_log` |
| deployment | 预览 URL | health=healthy + screenshot |

### 不做（本阶段冻结）

- 新 agent / 新 stage / learning loop 实验
- 14 角色全开 + 复杂 DAG 模板
- 「取代整家公司」对外 pitch（保留对内）

---

## 2. 量化目标（路线 C 闸门）

| 指标 | 目标 | 测量方式 |
|------|------|----------|
| planning 墙钟 | **≤ 90s**（stretch 60s） | `scripts/hero_baseline.py` |
| 单任务 LLM 调用数（planning） | **≤ 3** | backend log `llm-fallback] trying` |
| gate 诚实 | failed → `paused`/`rejected`，非 `done` | DB `quality_gate_status` |
| 任务 cost 可见 | span `cost_usd` > 0 或 Redis ledger 有记录 | observability / task detail |
| 孤儿任务 | 重启后 `active` 无运行进程 → **`failed`** | startup orphan scan |
| embedding 429 | 不再拖慢 stage（circuit 降级） | log 429 计数/分钟 |
| SQL echo | 默认关闭 | `sql_echo=false` |
| 前端体感 | SSE 有 stage/agent 事件（P1） | 任务详情页非静态 |

---

## 3. P0 执行清单（本周）

- [x] 剥离阶段内 delegation（消除 4.5min planning fanout）
- [x] `force_continue` 默认 `false` + 诚实终态
- [x] `sql_echo` 独立于 `debug`
- [x] embedding 429 circuit breaker（fail-fast，不重试风暴）
- [x] `cross_stage_verify` 除零修复（#10）
- [x] 启动时 mid-run 孤儿 → `failed`（裸 `active` 新建任务不误杀）
- [x] `scripts/hero_baseline.py` 单任务基线
- [x] token 用量写入 `TokenUsage` 表（有 org/user 时）
- [x] 关闭流水线 Ruflo enrichment（`ruflo_pipeline_enrich=false`）
- [x] `run-stage` 落库 gate/verify + 成功后 `task.status=active`

---

## 3.1 基线实测（2026-06-05）

| 轮次 | planning 耗时 | 结果 | 说明 |
|------|---------------|------|------|
| 修复前 | **175s** | 假绿 | Ruflo MCP `memory_store` 阻塞 120s + delegation fanout |
| 去 Ruflo 后 | **35s** | stage=done 但 task=failed | 孤儿扫描误杀 + run-stage 未写 gate |
| 诚实闸门 | **43s** | overall_pass（诚实 paused） | gate=0.717→`blocked`：作者是 CEO 评审模板，产出非 PRD（2/7 章节） |
| **当前** | **58.7s** | **gate=passed 0.82 ✅** | planning 作者改 PM（PRD 模板），章节 7/7 对齐，task=active 继续流转 |

命令：`SCHED_MAX_CONCURRENT=1 python3 scripts/hero_baseline.py --stage planning`  
产物：`docs/hero-baseline-latest.json`

---

## 4. P1（第二周）

- SSE 流式 UI（任务详情页实时进度）
- peer review 轻量化为打分（非完整 agent）
- development 契约 #9（codegen 必写 manifest）
- 自动化回归：`hero_baseline` 进 CI nightly

---

## 5. 基线复验命令

```bash
# 确保无并发诊断任务；单 worker 安静环境
export SCHED_MAX_CONCURRENT=1
cd backend && python3 ../scripts/hero_baseline.py --stage planning
```

输出写入 `docs/hero-baseline-latest.json`（分钟数、token、gate、pass/fail）。

---

## 6. Go / No-Go（2 周末）

**Go** 当且仅当连续 **3 次** 干净基线满足：

1. planning ≤ 90s  
2. gate = passed 或 honest pause（非 force 假绿）  
3. 无 delegation fanout（log 无 planning 阶段 Agent-cto/designer 子执行）

否则继续 P0，不对外 demo。
