# Hero Path 端到端断点诊断报告

> 日期: 2026-06-04
> 方法: 用**生产同款代码路径**真实运行,非静态推测
> 结论: 完整流程在到达 codegen 之前就**网络 await 挂死**,生产里表现为"规划中…"冻结 30 分钟后被网关硬超时判失败。

---

## 一、诊断方法(可复现)

驱动与生产完全相同的入口链路:

```
gateway._run_pipeline_background  →  e2e_orchestrator.run_full_e2e
  Phase 1: DAG preamble (e2e_intake: planning → design ∥ architecture)
  Phase 2: CodeGen (Claude Code)
  Phase 3: Build + Test → Fix loop
  Phase 4: Deploy (Vercel/Cloudflare)
  Phase 5: Preview + screenshot + notify
```

- 输入(Hero 句子): `做一个待办事项看板，支持新增、完成、删除任务。`
- 运行环境实测(`/health`):
  - 后端 healthy,PostgreSQL + Redis + crawl4ai 正常
  - LLM provider 配置 5 个,healthy 4 个(qwen / deepseek / google / zhipu),**anthropic unhealthy(熔断)**
  - `claude` CLI / `pnpm` / `node` 均在;**`playwright` Python 包缺失**
  - deploy 平台 1 个(Vercel token 已配)

---

## 二、实测时间线

| 时间 | 实际发生 |
|---|---|
| 0s | 任务建立,进入 `planning` |
| ~2.5 min | planning 阶段 + 子 agent(CEO 评审 / 安全审查 / QA 测试计划)真实跑完,写入 `task_memories` |
| 11:15:38 | 更新 `planning` 的 `cost_ledger`(deepseek-chat,4778 tokens) |
| 11:15:38 → +8 min | **零应用输出。进程 `%CPU 0.0`,中断时栈停在 asyncio `_selector.select()` —— 阻塞在一个无超时的网络 await** |
| 手动中断后查库 | `pipeline_tasks`: `status=active, current_stage_id=planning, last_error=NULL`;`pipeline_stages`: **0 行** |

**核心事实:一个最简单的 todo 跑了 ~10 分钟,只完成"规划",从未到达代码生成 / 构建 / 部署,然后无限期挂起。**

---

## 三、根因(按严重度,均有实证)

### 1. 🔴 编排层无总超时 + 无进度心跳
- 单次 LLM 调用有 `httpx.AsyncClient(timeout=300.0)`(`llm_router.py:630/937`),但**每个阶段串多次调用**(主调用 → self-verify → guardrail → Hermes 监督),阶段间并行。
- 任何一个 provider"接受连接但不回包"即可把整条链拖死,**对外无心跳**。
- 唯一兜底是网关 `GATEWAY_E2E_TIMEOUT` 默认 **1800s(30 分钟)** 硬超时 → 用户侧等同"假死"。

### 2. 🔴 流程从未到达 codegen/build/deploy
- 14 角色 × 多评审 × 可回炉的串行链过长过重,"规划+评审"就耗尽时间。
- 价值出口(可访问 URL)在链条最末端,**用户实际等不到**。

### 3. 🟡 `pipeline_stages` 运行期不落库
- DAG 在内存执行,运行期未写 `pipeline_stages` 行 → 前端/可观测看板**全空**,任务"在干活"却像死了。

### 4. 🟡 静默降级层层叠加
- 实测:`[memory] Embedding via zhipu failed: 429 Too Many Requests` 反复出现(embedding 限流)。
- `anthropic` provider 熔断 unhealthy。
- 单个不致命,但累积成延迟/噪音,且**无任何用户可见提示**。

### 5. 🟡 回炉炸弹
- 安全子 agent 实测返回 `REJECTED REJECT_TO: stage_1` —— 触发回退重跑会成倍放大时间/成本。

### 6. 🟡 Playwright 缺失(后段必断)
- Phase 5/6/7 的浏览器冒烟与部署截图依赖 Playwright Python 包,实测缺失;即便流程能走到后段也会断在这里。

---

## 四、结论:拆神文件解决不了"跑不通"

- "跑不通"的真凶是**运行回路本身**(无超时/无心跳、链太长、永远到不了出口),**不是** `pipeline_engine.py`(4296 行)难维护。
- 把神文件拆成 N 个小文件,流程**照样会卡死在同一个网络 await 上**。
- 拆文件是止"难维护"的血,不是止"跑不通"的血。

---

## 五、建议的止血顺序(供决策,未实施)

1. **运行回路加固(最高优先)**:阶段级总超时 + 进度心跳事件 + 挂死自动判失败(替代 30 分钟假死)。
2. **砍出最小闭环**:把 `e2e_intake` 的 14 角色多评审瘦身为 `planning → codegen → build → preview`,先让**一条路真能跑到 URL**。
3. **降级显式化**:embedding 429 / provider 熔断要降级且**告知用户**,而非静默拖延。
4. **补环境前置检查**:Playwright 等后段依赖在启动时探测,缺失即提前明确报错。
5. **运行期落库 `pipeline_stages`**:让看板真实反映进度。
6. (卫生工程)拆 `pipeline_engine.py` 神文件:在以上稳定后做,降低后续维护爆炸半径。

---

## 附:复现要点

- 入口函数:`backend/app/services/e2e_orchestrator.py::run_full_e2e`
- 默认模板:`DEFAULT_GATEWAY_E2E_DAG_TEMPLATE = "e2e_intake"`
- 网关超时:环境变量 `GATEWAY_E2E_TIMEOUT`(默认 1800)
- 观察手段:运行期 `%CPU 0.0` + asyncio selector 栈 = 阻塞在无超时网络 await
