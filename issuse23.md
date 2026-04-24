# Issue #23 — 从 LLM Wrapper 到真正的 AI Agent：核心闭环修复

> 日期: 2026-04-24
> 触发: 5步路线图(issuse22)全部完成后，进行数据审计，发现系统**外壳完整、内核空心**
> 定性: **P0 级阻塞** — 不修复这些问题，项目永远停留在"会写作文的 LLM Wrapper"阶段

---

## 一、审计数据（硬事实）

### 1.1 任务执行统计

| 指标 | 数据 | 判定 |
|------|------|------|
| 总任务数 | 80 | — |
| 状态 done | 46 | 看似可观 |
| 有≥4阶段实质内容(>300c) | **仅 10** | 36个"done"任务实际为空壳 |
| reviewing 阶段有内容 | **0** | 验收从未真正执行 |
| deployment 阶段有内容 | **0** | 部署从未真正执行 |
| quality_score > 0 的阶段 | **0** | self_verify 从未回写分数 |
| review_status 被设置过 | **0** | peer review 从未运行 |

### 1.2 Artifact（产物）质量

| 指标 | 数据 | 判定 |
|------|------|------|
| 总 Artifact 数 | 185 | — |
| 有实质内容(>200字符) | **0** | 全部是占位符 |
| 最长 content | 121 字符 | `"这是brief类型工件的内容，用于验证v2工件系统。"` |
| Stage output 回写到 Artifact | **0次** | Stage 有 13K 内容，Artifact 空 |

### 1.3 代码文件落地

| 指标 | 数据 | 判定 |
|------|------|------|
| Workspace 目录存在 | **否** | `/tmp/agent-hub-workspace` 不存在 |
| 任务有 worktree 文件 | **0个** | 80个任务，0个有磁盘文件 |
| Code Extractor 执行过 | **0次** | 代码写了但从未触发 |

### 1.4 最佳案例分析：在线教育直播平台

| 阶段 | 内容量 | 质量评估 | 问题 |
|------|--------|---------|------|
| planning | 2,185c | 有章节、有用户画像 | ✅ 可用 |
| design | 4,879c | 有配色、有组件规范 | ✅ 可用 |
| architecture | 12,947c | 有选型表格、有代码 | ✅ 可用 |
| development | 16,995c | 11个代码块(Python/Vue/SQL) | ⚠️ 代码在 markdown 里，没提取到文件 |
| testing | 8,413c | 自评 "NEEDS WORK ❌" | ⚠️ 发现问题但没有触发重做 |
| reviewing | **0c** | 空 | ❌ 验收 agent 从未被调用 |
| deployment | **0c** | 空 | ❌ 直接标 done |
| quality_score | **全部 0.00** | — | ❌ 从未计算 |

---

## 二、代码生成 / 各角色 / 渠道 / 模型 深度审计

### 2.1 代码生成完整链路

```
用户提交任务
  → pipeline_engine.execute_full_pipeline()
    → 7个阶段循环: planning → design → architecture → development → testing → reviewing → deployment
      → execute_stage(stage_id):
          1. STAGE_ROLE_PROMPTS[stage_id] 取 system prompt
          2. 如果 DB 有 agent.role_card → role_card_builder 动态生成 prompt 替换
          3. llm_chat_with_fallback() → 调 LLM API
          4. LLM 返回 markdown 文本 → 存入 return dict
      → execute_full_pipeline 循环:
          5. result["content"] → stage.output (DB)
          6. write_stage_output() → 写磁盘 markdown (如果 workspace 存在)
          7. write_artifact_v2() → 写 task_artifacts 表 (如果 artifact_store_v2=True)
          8. run_hooks("post", ...) → code_extractor 等 post-hook
```

**关键发现：`execute_stage()` 内部只做 LLM 调用 + memory 存储，不写文件不写 artifact。文件/artifact/hook 全在 `execute_full_pipeline()` 外层循环。DAG 模式和单阶段运行不走这条路径。**

### 2.2 各角色实际执行逻辑

**所有角色都是同一套路：给 LLM 一段 system prompt，返回 markdown 文本。没有任何角色执行真实工具。**

| 角色 | stage_id | agent_key | 实际做了什么 | 用了工具? |
|------|----------|-----------|-------------|----------|
| CEO 总控 | planning | ceo-agent → wayne-ceo | LLM 写 PRD 文本（~2K字符） | ❌ 无工具 |
| 产品经理 | planning | 同上 | 需求文档文本 | ❌ 无工具 |
| UI 设计师 | design | designer-agent → wayne-designer | 设计规范文字描述（配色+组件） | ❌ **没有生成设计图** |
| 架构师 | architecture | architect-agent → wayne-cto | 技术方案 markdown（~13K字符） | ❌ 无工具 |
| 开发者 | development | developer-agent → wayne-developer | markdown 内嵌代码块（~17K） | ❌ **代码没提取到文件** |
| 测试 | testing | qa-agent → wayne-qa | 测试报告文本（~8K） | ❌ **没有运行任何测试** |
| 验收 | reviewing | acceptance-agent → wayne-acceptance | **空（0c）** | ❌ 从未被真正调用 |
| 运维 | deployment | devops-agent → wayne-devops | **空（0c）** | ❌ 从未被真正调用 |
| 安全 | security-review | 有定义 | **不在默认 7 阶段流水线中** | ❌ |

**agent_runtime 有 TOOL_REGISTRY (file_write, bash, git, browser_navigate)，但 execute_stage() 只有当 `AGENT_TOOLS.get(stage_agent_id)` 非空时才走 tool loop。当前所有阶段的 agent 都没有注册 tools → 全部走纯文本 llm_chat_with_fallback()。**

### 2.3 Claude Code 接入审计

| 维度 | 状态 | 代码位置 |
|------|------|---------|
| executor_bridge.py | ✅ 存在 | `backend/app/services/executor_bridge.py` — `execute_claude_code()` subprocess 调 claude CLI |
| claude CLI 安装 | ✅ 已装 | `/Users/wayne/.local/bin/claude` |
| API 端点 | ✅ 可调 | `POST /api/executor/run` → `execute_claude_code()` |
| CodeGen Agent | ✅ 存在 | `POST /api/pipeline/tasks/{id}/codegen` → `CodeGenAgent` → 可选调 Claude CLI |
| **默认流水线集成** | ❌ **未集成** | `execute_stage()` 和 `execute_full_pipeline()` **从不调用** executor_bridge |
| Node 端重复实现 | ✅ | `server/executor/executorBridge.mjs` — 同逻辑的 Node spawn |

**结论：Claude Code 有完整代码 + CLI 都在，但默认 7 阶段流水线完全不调用它。只有手动触发 `/api/executor/run` 或 `/api/pipeline/tasks/{id}/codegen` 时才会用。**

### 2.4 渠道接入审计

#### 配置实际状态（从 .env 读取）

| 渠道 | 必要配置 | 实际值 | 判定 |
|------|---------|-------|------|
| **OpenClaw** | `PIPELINE_API_KEY` | ✅ SET | ✅ **唯一可用入口** |
| **飞书** | `APP_ID` + `APP_SECRET` + `VERIFICATION_TOKEN` + `ENCRYPT_KEY` | APP_ID=✅ SECRET=✅ TOKEN=✅ **ENCRYPT_KEY=❌空** | ⚠️ 配置不完整 |
| **QQ** | `QQ_BOT_ENDPOINT` + `ACCESS_TOKEN` | endpoint=❌空 token=❌空 | ❌ **零配置** |
| **Slack** | `SLACK_BOT_TOKEN` + `SIGNING_SECRET` | 全部 ❌ 空 | ❌ **零配置** |
| **Hermes-Agent** | — | — | ❌ **不存在，从未有代码** |
| **微信小程序** | `WECHAT_MP_*` | 全部 ❌ 空 | ❌ 且只是部署接口，非消息网关 |

#### 各渠道代码 + 路由 + 可用性

| 渠道 | 代码存在 | 路由注册 | 能创建任务? | 能发通知? | 实际验证过? |
|------|---------|---------|-----------|----------|-----------|
| OpenClaw | ✅ `gateway.py` intake/status/approve/reject/revise | `/api/gateway/openclaw/intake` | ✅ 是 | ❌ 无外发 | ✅ plan mode 测试 |
| 飞书 | ✅ webhook + AES 解密 + 卡片发送 | `/api/gateway/feishu/webhook` | ✅ `_clarify_or_create_task()` | ✅ `feishu_im.send_card` | ❌ 从未有真实飞书消息 |
| QQ | ✅ OneBot v11 子集 | `/api/gateway/qq/webhook` | ✅ 同上路径 | ✅ `qq_onebot.send_text` | ❌ 仅 auth 拒绝测试 |
| Slack | ✅ Events API + 签名验证 + 交互 | `/api/gateway/slack/webhook` | ✅ 同上路径 | ✅ `slack.send_message` | ❌ 无测试 |
| Hermes-Agent | ❌ 无代码 | — | — | — | — |
| 微信小程序 | ✅ 部署API(非消息) | `/api/deploy/miniprogram*` | ❌ 不是消息网关 | ❌ | ❌ |

#### 渠道间协调机制

- ❌ **渠道间不互通消息**：A渠道对话 B渠道看不到
- ⚠️ `broadcast_task_event()` 写了跨渠道广播，但 QQ/Slack 没凭证 → 实际只能发飞书（飞书也未验证通）
- 每个渠道独立 → `_clarify_or_create_task()` → `_run_pipeline_background()`

### 2.5 模型接入审计

#### 可用模型

| 模型 | 提供商 | endpoint | 连通性 | 角色 |
|------|-------|---------|--------|------|
| `google/gemma-4-26b-a4b` | 本地 192.168.130.230:1234 | ✅ 200 OK | ✅ | 默认模型（所有阶段） |
| `qwen3.6-35b-a3b-*-distilled` | 本地 192.168.130.230:1234 | ✅ 配置为 `local_llm_model_strong` | ✅ | 规划/架构（需手动指定） |
| `glm-4-flash` | 智谱 API | ✅ 200 OK | ✅ | fallback chain 第2位 |

#### 不可用模型

| 模型 | 原因 |
|------|------|
| OpenAI GPT-4o-mini | `openai_api_key=EMPTY` |
| DeepSeek | `deepseek_api_key=EMPTY` |
| Qwen (阿里云) | `qwen_api_key=EMPTY` |
| Google Gemini | `google_api_key=EMPTY` |
| Anthropic Claude (真 API) | key=SET 但 `base_url=192.168.130.230:1234`（**指向本地 gemma，不是真 Anthropic**） |

#### Fallback Chain（实际生效顺序）

```
1. local → google/gemma-4-26b-a4b      ✅ (主力)
2. zhipu → glm-4-flash                  ✅ (备用)
3. deepseek → deepseek-chat              ❌ (no key)
4. openai → gpt-4o-mini                  ❌ (no key)
5. anthropic → claude-3-5-haiku          ❌ (url指向本地)
6. qwen → qwen-turbo                     ❌ (no key)
7. google → gemini-2.5-flash             ❌ (no key)
```

**实际在用的只有 2 个模型：本地 gemma-4 + 智谱 glm-4-flash。**

---

## 三、根因分析

### 问题 1：所有角色只做文本生成，不执行工具

**现象**: 14个 Agent 角色有 role_card、有 capabilities，但实际全部只做 LLM text completion。

**根因**:
- `execute_stage()` 判断 `AGENT_TOOLS.get(stage_agent_id)` 是否非空来决定走 tool loop 还是纯文本
- 当前所有 seed agent 都**没有注册 tools** → 永远走 `llm_chat_with_fallback()` 纯文本路径
- `agent_runtime.py` 的 TOOL_REGISTRY 有 `file_write`, `bash`, `git`, `browser_navigate` 但没有被任何 stage agent 引用
- Claude Code executor_bridge 存在但流水线不调用

**影响**: "开发者"不能写文件、"测试"不能运行测试、"运维"不能执行部署命令

### 问题 2：Workspace 从未初始化

**现象**: code_extractor 的 `extract_code_blocks()` 依赖 `WORKSPACE_ROOT` 环境变量指向的目录，但该目录从未被创建。

**根因**: 
- `WORKSPACE_ROOT` 默认值 `/tmp/agent-hub-workspace` 在应用启动时没有 `os.makedirs()` 调用
- code_extractor 的 post-stage hook 注册了但因 FileNotFoundError 静默失败
- 没有健康检查验证 workspace 可写

**影响**: 所有任务的代码输出永远锁在 stage.output 的 markdown 文本里

### 问题 3：Stage Output → Artifact 断裂

**现象**: 185 个 Artifact 全是占位符文本，stage.output 里有数万字的真实内容从未写入 artifact 表。

**根因**:
- `pipeline_engine.py` 在 `execute_stage()` 完成后将 LLM 输出存入 `stage.output`
- 但**没有**调用 `create_artifact()` 将内容写入 `task_artifacts` 表
- Artifact 表里的数据来自自测脚本的模拟写入，不是流水线产出

**影响**: 前端 8-tab 视图里 Artifact 全是假数据，用户看不到真正产出

### 问题 4：Reviewing/Deployment 空壳执行

**现象**: reviewing 和 deployment 阶段 status=done 但 output=0c。

**根因**:
- `reviewing` 阶段的 agent 匹配依赖 `owner_role` 字段，但 seed 中 reviewing stage 的 `owner_role` 与 acceptance agent 的角色不匹配
- 可能触发了 LLM 调用但返回空或异常被吞
- `deployment` 阶段逻辑可能直接标记 done（因为没有真实部署目标）

**影响**: "全阶段完成"是假象

### 问题 5：Quality Score 从未回写

**现象**: 所有 stage 的 quality_score = 0.00。

**根因**:
- `self_verify.py` 的 `verify_stage_output()` 返回 `VerifyResult`
- 但 `pipeline_engine.py` 调用后**没有**将 `result.score` 写回 `stage.quality_score`
- 只是将 verify 结果通过 SSE 事件发出，数据没有持久化

**影响**: 无法根据质量分做自动重试/降级决策

### 问题 6：Peer Review 从未运行

**现象**: 所有 stage 的 review_status = NULL。

**根因**:
- peer review 逻辑在 `_run_peer_review()` 中，但调用条件不满足（可能需要特定配置或 agent 匹配失败）
- reviewer_agent 匹配查询可能返回空

**影响**: 无质量门禁，什么内容都能通过

---

## 四、修复计划（6步，按优先级）

### Step ① Workspace 初始化 + Code Extractor 真正落地

**目标**: 让 LLM 生成的代码块提取为真实的 .py/.vue/.ts 文件

**具体修复**:
1. `settings.workspace_root` 当前为空字符串，fallback 到 `<repo>/data/workspace` — 确认该目录存在且可写
2. 应用启动时 `ensure_task_workspace()` 要创建 `worktrees/` 子目录
3. 验证 code_extractor post-hook 在 `execute_full_pipeline()` 中确实被调用（post-hook 只在此路径触发）
4. 添加错误不静默——如果 extract 失败，记录到 stage.last_error
5. 添加 `/api/health/workspace` 端点检查可写性
6. 确保 `ensure_task_workspace()` 在 `execute_stage()` 内不会因异常静默跳过

**验证标准**: 
- 新建任务 → development 阶段完成后 → worktree 目录有真实代码文件
- `ls data/workspace/tasks/TASK-{id}-*/` 有文件
- 文件可通过 `/api/pipeline/tasks/{id}/worktree/files` 读取

### Step ② Stage Output → Artifact 自动回写

**目标**: 每个阶段完成后，将 output 自动存入 task_artifacts 表

**具体修复**:
1. 排查 `write_artifact_v2()` 在 `execute_full_pipeline()` 中的调用是否正确工作（当前 `artifact_store_v2=True`）
2. 确认 `STAGE_TO_ARTIFACT` 映射覆盖全部 7 个阶段
3. 如果 `write_artifact_v2()` 被调用但写入的 content 是空/占位符，修复其参数传递
4. 映射关系: planning→brief+prd, design→ui_spec, architecture→architecture, development→implementation+code_link, testing→test_report, reviewing→acceptance, deployment→deploy_manifest
5. 如已有相同 task_id+stage_id+artifact_type 的 latest 记录，设 `is_latest=False` 后插新版本

**验证标准**:
- 任务完成后 `SELECT artifact_type, length(content) FROM task_artifacts WHERE task_id=X` 每条 >500 字符
- 前端 8-tab 视图显示 LLM 生成的真实 PRD、架构文档、测试报告

### Step ③ Quality Score 回写 + 不达标自动重做

**目标**: self_verify 结果持久化，低分自动触发 retry

**具体修复**:
1. `verify_stage_output()` 返回后，将 `result.score` 写入 `stage.quality_score`（已在 execute_full_pipeline 设 0.8/0.5/0.2 但可能未 commit）
2. 排查 `execute_full_pipeline()` 中 quality_score 赋值后是否 `db.commit()`
3. `result.passed` 为 False 时，若 `stage.retry_count < stage.max_retries`，触发重做
4. 验证完成后更新 `stage.verify_status` 字段
5. 任务完成时计算 `task.overall_quality_score = avg(stages.quality_score)`

**验证标准**:
- 阶段完成后 `SELECT quality_score FROM pipeline_stages WHERE task_id=X` 全部 > 0
- 低质量阶段自动重试（retry_count > 0）
- 任务完成后 overall_quality_score 有真实值

### Step ④ Reviewing 阶段真正执行

**目标**: Acceptance Agent 真正审阅前置阶段产出，给出 PASS/REJECT 决策

**具体修复**:
1. 排查 reviewing stage 的 agent 匹配逻辑，确保 `STAGE_ROLE_PROMPTS["reviewing"]` 的 agent 能正确找到 DB agent
2. 给 reviewing stage 注入前置阶段的 output 摘要作为上下文（通过 `get_context_from_history()`）
3. Acceptance Agent 的 prompt 要求输出结构化审阅：通过/不通过 + 理由
4. REJECT 时触发 REJECT_TO 逻辑（issuse22 Step 5 已实现解析，但从未有输入）
5. 审阅结果写入 stage.output 和 stage.review_status
6. 排查是否 LLM 返回空或异常被吞（`except Exception: pass`）

**验证标准**:
- reviewing stage 完成后 output > 500c
- 输出包含结构化审阅：通过项 / 不通过项 / 最终结论
- review_status = approved 或 rejected

### Step ⑤ Deployment 阶段产出真实内容

**目标**: 生成可操作的部署清单

**具体修复**:
1. Deployment Agent 根据 architecture + development 阶段输出，生成 Dockerfile + docker-compose.yml + 部署说明
2. 部署产物通过 code_extractor 写入 worktree 的 `/deploy/` 目录
3. 部署清单存入 deploy_manifest artifact

**验证标准**:
- deployment stage 完成后 output > 1000c
- worktree 中有 Dockerfile 和 docker-compose.yml
- deploy_manifest artifact 有真实内容

### Step ⑥ Agent 工具执行（从 LLM Wrapper 到真 Agent）

**目标**: 关键角色能调用真实工具，而不只是写作文

**具体修复**:
1. 为 development 阶段 agent 注册 `file_write` + `bash` 工具 → 走 `agent_runtime.execute()` tool loop
2. 为 testing 阶段 agent 注册 `bash` 工具 → 能运行 `pytest` / `npm test`
3. 为 deployment 阶段 agent 注册 `file_write` + `bash` 工具 → 能生成 Dockerfile 并验证
4. 可选: development 阶段集成 `execute_claude_code()` 作为高级代码生成后端
5. 为 tool 执行设置沙箱边界（`sandbox_strict_bash=True` 已有）

**验证标准**:
- development 阶段调用了 file_write 工具，worktree 有 Agent 直接写入的文件
- testing 阶段调用了 bash 工具，日志中有测试命令执行记录
- Agent 工具调用在 trace span 中可观测

---

## 五、执行顺序与依赖

```
Step ① Workspace + Code Extractor        ← 基础：文件能写到磁盘
  ↓
Step ② Stage → Artifact 回写              ← 数据：产物有真实内容
  ↓
Step ③ Quality Score + 自动重做            ← 闭环：质量分驱动流程
  ↓
Step ④ Reviewing 真正执行                  ← 门禁：验收能读到真实产物
  ↓
Step ⑤ Deployment 真实产出                 ← 交付：可操作的部署件
  ↓
Step ⑥ Agent 工具执行                      ← 进化：从写作文到真执行
```

每步完成后**必须通过端到端验证**：创建新任务 → 全流程执行 → 检查数据库+磁盘+前端三方一致。
**验证用 SQL 查询 + 文件检查，不是 HTTP 状态码。**

---

## 六、成功标志

当以下条件**全部**满足时，才能说"这是我们期望的 AI Agent"：

| # | 标志 | 验证方法 | 对应 Step |
|---|------|---------|----------|
| 1 | 任务完成后 worktree 有 ≥5 个真实代码文件 | `ls data/workspace/tasks/TASK-{id}-*/` | ① |
| 2 | task_artifacts 表 content 平均 >2000 字符 | `SELECT avg(length(content)) FROM task_artifacts WHERE task_id=X` | ② |
| 3 | 所有阶段 quality_score > 0 | `SELECT quality_score FROM pipeline_stages WHERE task_id=X` | ③ |
| 4 | reviewing stage output > 500c 且有结构化审阅 | `SELECT length(output) FROM pipeline_stages WHERE stage_id='reviewing'` | ④ |
| 5 | deployment stage 有 Dockerfile 内容 | `SELECT output FROM pipeline_stages WHERE stage_id='deployment'` | ⑤ |
| 6 | overall_quality_score > 0.6 | `SELECT overall_quality_score FROM pipeline_tasks WHERE id=X` | ③ |
| 7 | 前端 8-tab 视图每个 tab 有真实内容可查看 | 人工验收 | ②+① |
| 8 | 低质量阶段自动重做至少发生 1 次 | `SELECT retry_count FROM pipeline_stages WHERE retry_count > 0` | ③ |
| 9 | development 阶段有 tool 调用记录 | trace span 中有 tool_call 事件 | ⑥ |
| 10 | testing 阶段有 bash 命令执行日志 | trace span + stage output 中有命令输出 | ⑥ |

---

## 七、反思

### 之前做错了什么

1. **重框架轻闭环**: 投入大量时间建 Role Card、Skill Upgrade、跨渠道广播、REJECT_TO 解析，但最基础的"文件写到磁盘"都没通
2. **自测是假自测**: 12个项目自测报告"100%通过"，但实际验证的是"API 返回 200"，不是"产出物有价值"
3. **数据不说谎**: 应该在每一步完成后用 SQL 审计真实数据，而不是只看 HTTP 状态码
4. **代码有不等于能用**: Claude Code executor_bridge 写了、渠道 webhook 写了、code_extractor 写了，但没有一个在默认流水线中真正被调用
5. **配置零验证**: 声称接入了飞书/QQ/Slack，但 .env 凭证全是空的，从未有过真实消息

### 这次要不同

1. **每步的验证标准是 SQL 查询 + 文件检查**，不是 API 状态码
2. **不在框架上加新功能**，而是让已有流程真正跑通
3. **一个任务端到端通过后才进入下一步**
4. **先让 1 个渠道真正跑通**（OpenClaw 已最接近），再扩展其他渠道

---

## 八、声称 vs 现实 总表

| 模块 | 声称 | 现实 | 差距 |
|------|------|------|------|
| 代码生成 | Agent 写代码到文件 | LLM 写 markdown，代码锁在文本里 | workspace 未初始化 |
| UI 设计 | 设计师 agent 产出设计稿 | LLM 写了配色文字描述，没有图 | 无设计工具集成 |
| 产品需求 | PRD 文档 | ✅ 有 markdown PRD（可用） | 质量受 gemma-4 限制 |
| 架构方案 | 技术方案 | ✅ 有 markdown 技术文档（可用） | 同上 |
| 测试 | 自动化测试 | LLM 写测试报告文本，没运行任何测试 | 无 bash 工具 |
| 验收 | Agent 审阅打分 | **空壳，从未运行** | agent 匹配/异常吞没 |
| 运维部署 | 部署清单 | **空壳，从未运行** | 同上 |
| 安全审查 | 安全 agent | **不在默认流水线** | 未配置 |
| Claude Code | 已集成运行 | 代码+CLI 都有，**流水线不调用** | 未接入 pipeline |
| 飞书 | 已接入 | 代码有，配置不完整(ENCRYPT_KEY 空) | 从未接收真实消息 |
| QQ | 已接入 | 代码有，**零配置** | endpoint+token 全空 |
| Slack | 已接入 | 代码有，**零配置** | token+secret 全空 |
| OpenClaw | 已接入 | ✅ **唯一真正可用的入口** | — |
| Hermes-Agent | 已接入 | **不存在，从未有代码** | 幽灵集成 |
| Artifact | 8-tab 展示 | 185条全是 ≤121字符占位符 | 未回写 stage output |
| 质量评分 | 自动评分 | **全部 0.00** | 未持久化 |
| 模型 | 多模型 fallback | 只有 gemma-4 + glm-4-flash 可用 | 5/7 provider 无 key |

---

> 上一个 Issue: [#22 系统全面诊断](./issuse22.md)
> 关联 Issues: [#19 深度诊断](./issuse19.md) | [#20 Path A 路线图](./issuse20.md) | [#21 Artifact 架构](./issuse21.md)
