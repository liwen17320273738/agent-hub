# 外部项目接入方案 — Agent Hub

> 日期: 2026-06-03
> 范围: OpenClaw / DeerFlow / Hermes-agent

---

## 一、总览

当前 Agent Hub 已经编写了与外部项目的对接代码，但均处于"代码已写好但未实际部署运行"的状态：

| 项目 | 对接代码 | 实际运行 | 状态 |
|------|----------|----------|------|
| **OpenClaw** | `api/gateway.py` — 完整 intake + Plan 审批流 | ❌ 无 OpenClaw 实例调用 | 🔴 预留代码 |
| **DeerFlow** | `services/tools/deerflow_tool.py` — 3 个 agent 工具 | ❌ 无本地 DeerFlow 实例 | 🔴 预留代码 |
| **Hermes Oversight** | `services/hermes_oversight.py` — 6 维监督评分 | ✅ pipeline 中自动执行 | 🟢 已集成 |

本文档说明如何将这三个项目**真正跑起来**，以及接入后的实质效果。

---

## 二、OpenClaw 接入

### 2.1 现状

已有代码：

```
POST /gateway/openclaw/intake          # 接收 OpenClaw 的 intake 请求
POST /gateway/openclaw/status          # 健康检查
POST /gateway/openclaw/plans/{s}/{u}/approve  # 审批 Plan
POST /gateway/openclaw/plans/{s}/{u}/reject   # 驳回 Plan
POST /gateway/openclaw/plans/{s}/{u}/revise   # 修改 Plan
```

Gateway 中已有对 OpenClaw 的完整支持：
- `OpenClawIntakeRequest` — 接收任务标题/描述/source/消息ID
- `planMode` — 支持 Plan 暂停 -> 审批 -> 执行流程
- `autoFinalAccept` — 可选自动验收（跳过人工审批）
- `_require_openclaw_secret()` — 基于 `GATEWAY_OPENCLAW_SECRET` 的认证
- 所有 Plan 审批端点已实现

配置中已有：
```python
# config.py
gateway_openclaw_secret: str = ""  # 当前为空
```

### 2.2 接入方案

#### 步骤 1：配置 OpenClaw 环境变量

```bash
# 设置 OpenClaw 网关密钥
export GATEWAY_OPENCLAW_SECRET="your-openclaw-secret-key"
```

#### 步骤 2：在 OpenClaw 中配置 Agent Hub Gateway

在 OpenClaw 的 skills 配置中添加一个自定义 skill，通过 HTTP POST 调用 Agent Hub 的 Gateway API：

```yaml
# OpenClaw skill: agent-hub-gateway
name: "Agent Hub Gateway"
description: "将任务提交到 Agent Hub 进行 AI 交付"
actions:
  - type: http
    method: POST
    url: "https://your-agent-hub.com/api/gateway/openclaw/intake"
    headers:
      Authorization: "Bearer ${GATEWAY_OPENCLAW_SECRET}"
    body:
      title: "${task.title}"
      description: "${task.description}"
      source: "openclaw"
      userId: "${user.id}"
      messageId: "${message.id}"
      planMode: true
```

OpenClaw 用户发送 `帮我做一个落地页` → OpenClaw 调 Agent Hub API → Agent Hub 返回 Plan（方案预览链接） → OpenClaw 用户点"Approve" → Agent Hub 执行 pipeline → 部署 → 返回可访问链接。

#### 步骤 3：打通 Plan 审批的回传通知

OpenClaw 调 `POST /gateway/openclaw/plans/openclaw/{userId}/approve` 后，Agent Hub 开始执行 pipeline。但 OpenClaw 需要知道 pipeline 完成。

**方案**：在 `services/sse.py` 中为 OpenClaw 添加一个回调端点，或让 Agent Hub 在 pipeline 完成时通知 OpenClaw：

```python
# services/notify/openclaw_notify.py
async def notify_openclaw_completion(task_id: str, result_url: str):
    """Pipeline 完成后回调 OpenClaw"""
    webhook_url = settings.openclaw_completion_webhook
    if not webhook_url:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(webhook_url, json={
            "taskId": task_id,
            "status": "completed",
            "resultUrl": result_url,
        })
```

#### 步骤 4：可选 — 让 OpenClaw 当"频道中继"

OpenClaw 已经支持 10+ 消息频道。部署 OpenClaw 实例后，用户可以从**任何 OpenClaw 支持的频道**（WhatsApp、Telegram、微信等）发送消息 → OpenClaw 中继到 Agent Hub → pipeline 执行 → 结果回传原频道。

### 2.3 接入后的实质效果

| 维度 | 当前 | 接入后 |
|------|------|--------|
| **消息渠道** | 飞书、QQ | 飞书、QQ + **WhatsApp、Telegram、Discord、Signal、微信、Slack 等 10+ 渠道** |
| **Plan 审批** | 飞书卡片点按钮 | **任意 IM 平台**发消息确认 |
| **用户触达** | 必须用户主动打开 Agent Hub | 主动推送到用户的日常聊天工具 |
| **24/7 运行** | pipeline 执行完即结束 | OpenClaw 常驻运行，监控任务状态、提醒验收、自动重试 |
| **社区技能** | 自研 10+ 个 agent | 可复用 **5700+ OpenClaw 社区技能**（邮件、日历、爬虫等） |

**一句话效果**：用户在任何聊天工具发一句话 → Agent Hub 交付上线 → 结果推回聊天窗口。

---

## 三、DeerFlow 接入

### 3.1 现状

已有代码：

```python
# services/tools/deerflow_tool.py
deerflow_delegate()        # 委托任务到 DeerFlow
deerflow_list_skills()     # 查询 DeerFlow 技能
deerflow_list_models()     # 查询 DeerFlow 模型
```

3 个工具已注册到全局 TOOL_REGISTRY，所有 12 个 agent 角色都已配置对 `deerflow_delegate` 的访问权限。

但当前：
- 无 `DEERFLOW_URL` 环境变量配置
- 无 `config.py` 配置项
- pipeline 核心路径不依赖它
- 需要额外部署一个 DeerFlow 实例（Docker）

### 3.2 接入方案

#### 步骤 1：本地 Docker 部署 DeerFlow

DeerFlow 2.0 是字节跳动开源产品，Docker 一键启动。在 `docker/docker-compose.yml` 中添加 DeerFlow 服务：

```yaml
# docker-compose.yml 新增
services:
  # ... 现有服务 ...

  deerflow:
    image: bytedance/deerflow:latest
    ports:
      - "2026:2026"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - DEERFLOW_SANDBOX_ENABLED=true
    volumes:
      - deerflow_data:/app/data
    restart: unless-stopped

volumes:
  deerflow_data:
```

然后设置环境变量：

```bash
export DEERFLOW_URL="http://localhost:2026"
```

#### 步骤 2：在 config.py 中添加配置项

```python
# config.py 新增
deerflow_url: str = "http://localhost:2026"
deerflow_gateway_url: str = ""
deerflow_langgraph_url: str = ""
deerflow_sandbox_enabled: bool = True
```

#### 步骤 3：在 pipeline_engine.py 中添加 DeerFlow 作为备用执行引擎

当前 `execute_stage()` 的 Layer 4（LLM 调用）执行的是自研 `AgentRuntime`。新增一个可选路径：

```
execute_stage() Layer 4 中：
  if stage_id in ("planning", "design", "architecture") and deerflow_available:
      # 用 DeerFlow 执行深度分析（有 sandbox 隔离 + sub-agent 能力）
      result = await deerflow_delegate({"message": prompt, "mode": "pro"})
  else:
      # 保持自研 AgentRuntime
      result = await agent_runtime.execute()
```

**关键改动位置**：`pipeline_engine.py` 的 `execute_stage()` 函数中 Layer 4 部分（约第 3400-3600 行），在调用 `AgentRuntime` 之前增加 DeferFlow 路由判断：

```python
# --- Layer 4: LLM Call ---
# 新增：如果 DeerFlow 可用且阶段适合，走 DeerFlow
if _deerflow_available and stage_id in _DEERFLOW_CANDIDATE_STAGES:
    prompt = _build_deerflow_prompt(role_prompt, user_content, previous_outputs)
    deerflow_result = await deerflow_delegate({"message": prompt, "mode": "pro"})
    # 解析结果，提取 content + 文件产出
    content = _extract_deerflow_content(deerflow_result, stage_id)
    files_rel = _extract_deerflow_files(deerflow_result, stage_id)
else:
    # 原有自研 AgentRuntime 逻辑
    ...
```

#### 步骤 4：可选 — 用 DeerFlow 的 Docker sandbox 替换自研 worktree

DeerFlow 的 sandbox 是 Docker 容器隔离的，比 Agent Hub 当前自研的 `task_workspace.py`（文件系统 worktree）+ `bash` tool（无容器隔离）安全得多。

在 `services/task_workspace.py` 中新增 DeerFlow sandbox 模式：

```python
# 当 DeerFlow sandbox 启用时，代码执行走 DeerFlow 容器
# 而不是本地文件系统
if settings.deerflow_sandbox_enabled:
    sandbox = DeerflowSandbox(settings.deerflow_url)
    # 代码写入 DeerFlow 沙箱 → 编译 → 测试 → 提取结果
else:
    # 当前自研 worktree
    worktree = TaskWorkspace(task_id)
```

### 3.3 接入后的实质效果

| 维度 | 当前 | 接入后 |
|------|------|--------|
| **子 agent 能力** | 自研 `delegate_to_agent`（简单） | **DeerFlow 的 LangGraph sub-agent**（带规划器 + 记忆 + 工具） |
| **代码执行安全** | 本地文件系统（无隔离） | **Docker sandbox 隔离**（安全、可回滚、可清理） |
| **深度研究能力** | Crawl4AI 抓取 → agent 分析 | DeerFlow 的深度研究管线（网页 + 代码 + 推理 + 报告） |
| **上下文工程** | 自研 `context_compactor.py` | DeerFlow 的上下文窗口管理 + 压缩策略 |
| **Agent 记忆** | 自研 3 层记忆系统 | DeerFlow 的长期记忆 + 向量索引（可作为备用） |

**最直接的效果**：agent 在 pipeline 中遇到需要"深度研究"的任务时，不再是简单 `web_search` + 手写分析，而是委托给 DeerFlow 的完整 sub-agent 管线来处理，结果更可靠、代码执行更安全。

**具体场景**：
- **规划阶段**：用户说"做个电商站"，DeerFlow 搜索竞品、产出需求文档
- **开发阶段**：代码构建遇到复杂编译错误，DeerFlow 开启 sub-agent 逐层排查
- **安全审查**：DeerFlow 运行安全扫描工具并生成报告

---

## 四、Hermes 借鉴方案

### 4.1 现状

Agent Hub 已有 `hermes_oversight.py`——这是一个自研的 6 维监督评分器，与 NousResearch/hermes-agent（53k⭐）没有直接代码关系。

当前 Hermes Oversight 的作用：
- 在 pipeline 每阶段执行完后运行（Layer 11）
- 聚合 6 个监督维度的分数
- 输出 PASS / REQUEST_CHANGES / BLOCK

**它不存在"不运行"的问题，已经正常工作了。**

### 4.2 可以借鉴的：反思循环（Reflection Loop）

NousResearch/hermes-agent 真正有价值的设计模式是它的"反思 → 改进"循环：

```
Hermes Agent 的核心循环：
  1. 执行任务（调用 LLM）
  2. 反思执行结果（"这次做得好/不好在哪里"）
  3. 提取经验教训
  4. 写入长期记忆
  5. 下次类似任务时回忆这些经验
```

Agent Hub 的 `learning_engine.py`（`_extract_success_patterns`）已经在做类似的事——统计段落数、代码块数、表格数等表层指标。但 Hermes 的反思是**语义级别的**（"这次遗漏了安全性评估"），不是一个数代码块的 regex。

#### 改进方案：在 learning_engine 中添加 LLM 驱动的反思

当前 `_extract_success_patterns()` 的方法：

```python
def _analyze_content_structure(self, content: str) -> List[Dict]:
    # 只做 regex 级别的分析
    section_count = content.count("## ")
    code_blocks = content.count("```") // 2
    table_count = content.count("| ---")
    ...
```

改进为 LLM 驱动的语义反思：

```python
# 新增: learning_engine.py
async def _reflect_on_task(
    self, db, task_id, role, stage_id, content, quality_score, success
) -> Dict:
    """
    LLM 驱动的反思循环。
    让一个"反思 agent"评估刚刚完成的任务，提取语义级别的经验教训。
    """
    reflection_prompt = f"""
你是一个经验丰富的 {role}。评估以下任务的执行质量：
1. 哪些方面做得好？
2. 哪些方面可以改进？
3. 遗漏了哪些关键内容？
4. 如果重做一次，你会改变什么？
5. 给这个任务打分（0-10）

任务内容：{content[:2000]}
"""
    reflection = await llm_chat_with_fallback(
        messages=[{"role": "user", "content": reflection_prompt}],
        model="gpt-4o-mini",  # 用小模型，便宜
    )
    
    # 将反思结果中的经验教训提取为结构化记忆
    learnings = _parse_reflection(reflection)
    await self._store_learning(db, {
        "role": role,
        "stage_id": stage_id,
        "task_id": task_id,
        "learnings": learnings,
        "quality_score": quality_score,
        "success": success,
    })
    
    return learnings
```

在 `learn_from_task()` 方法中调用：

```python
async def learn_from_task(self, db, ..., content, success, ...):
    # 现有的表层分析
    patterns = await self._extract_success_patterns(...)
    
    # 新增：LLM 驱动的深度反思
    if success or quality_score < 0.5:  # 成功时学经验，失败时学教训
        reflections = await self._reflect_on_task(
            db, task_id, role, stage_id, content, quality_score, success
        )
        patterns.extend(reflections)
```

### 4.3 改进后的实质效果

| 维度 | 当前 | 改进后 |
|------|------|--------|
| **学习深度** | 统计标题数、代码块数 | **语义层面理解"这次做得好在哪、差在哪"** |
| **经验质量** | "好结构：5 个章节" | **"遗漏了数据模型定义，下次应该在架构阶段包含 ER 图"** |
| **跨任务改进** | 只增不减的模式计数 | **每次反思更新到角色 prompt 中，agent 越用越好** |
| **计算成本** | 免费（regex） | 每次反思 ~100 tokens（gpt-4o-mini，~0.015 美分/次） |

### 4.4 实施优先级：低

Hermes 改进不涉及"部署新服务"或"写新 API"，属于渐进的代码优化。建议放在 OpenClaw 和 DeerFlow 之后做。

---

## 五、实施路线图

### Phase 1：开启动态（0.5 天）

| 项目 | 操作 | 时间 |
|------|------|------|
| **OpenClaw** | 设置 `GATEWAY_OPENCLAW_SECRET` | 5 分钟 |
| **DeerFlow** | docker-compose 加 deerflow 服务 + 设置 `DEERFLOW_URL` | 30 分钟 |
| **Hermes** | 无需操作（已运行） | — |

### Phase 2：打通核心链路（2 天）

| 项目 | 操作 | 时间 |
|------|------|------|
| **OpenClaw** | 部署 OpenClaw 实例 → 配置 agent-hub-gateway skill → 验证 end-to-end | 1 天 |
| **DeerFlow** | config.py 加配置项 → pipeline_engine.py 中加 DeerFlow 路由 → 测试代理执行 | 1 天 |
| **Hermes** | learning_engine.py 添加反思循环 → 写测试 | 1 天（可选） |

### Phase 3：深度集成（3-5 天，可选）

| 项目 | 操作 | 
|------|------|
| **OpenClaw** | 添加 pipeline 完成回调 → 多频道测试 |
| **DeerFlow** | 用 DeerFlow sandbox 替换自研 worktree → 评估安全效果 |
| **Hermes** | 反思积累的经验自动注入到 agent prompt 中 |

---

## 六、smolagents 接入

### 6.1 概述

| 项目 | Stars | 定位 | 语言 |
|------|-------|------|------|
| **smolagents** | 27.6k ⭐ | 极简 Agent 框架（Hugging Face） | Python |

**核心设计**：Agent 输出 **Python 代码** 而非 JSON tool calls。LLM 生成 `result = search("xxx")` 这样的代码，框架执行它，把 stdout 作为下一轮观测。

对比当前的 tool calling：
```
当前（OpenAI function calling）:
  {"name": "web_search", "arguments": {"query": "xxx"}}
  → 框架解析 JSON → 调函数 → 结果截断 8000 字符

smolagents CodeAgent:
  result = web_search("xxx")
  print(result)
  → 框架执行 Python → 变量可复用 → 无截断限制
```

### 6.2 对你的项目有什么帮助

#### 直接有用的：CodeAgent 代码执行模式

你的 `agent_runtime.py` 当前的核心限制：

| 当前问题 | smolagents 的做法 | 可借鉴 |
|----------|-------------------|--------|
| 工具结果截断 8000 字符 | 代码执行，变量存在内存中，无截断 | 改进你的 `_truncate_tool_result()` |
| 多步工具调用需反复请求 LLM | 一次代码片段可调用多个工具、循环、条件判断 | **减少 30%+ LLM 调用次数** |
| 工具间数据传递靠 message history | 变量复用：`data = search("x"); result = analyze(data)` | **减少 token 消耗** |
| JSON tool calling 格式固定 | `@tool` 装饰器定义函数即可 | 简化工具注册 |

在 smolagents 的 GAIA 基准测试中，CodeAgent 比传统 JSON tool-calling 高了 **44.2% → 减少 30% 的 LLM 调用次数**。原因很简单：一次代码生成可以执行多个工具调用、循环和条件分支，不需要反复请求 LLM。

#### 有针对性的：sandbox 执行

smolagents 支持 `LocalPythonExecutor`（AST 解析 + import 白名单）和远程 sandbox（E2B、Docker、Modal）。你的 `qa_executor.py` 和 `codegen_agent.py` 已经在跑子进程编译代码，但缺少 py 代码执行的安全隔离。

### 6.3 接入方案

#### 方案 A（推荐）：借模式，不借代码

不 pip install smolagents，而是在你的 `agent_runtime.py` 中借鉴代码执行模式：

```python
# 当前：agent_runtime.py 的 ReAct 循环
# 每次 tool call 都走 LLM → 解析 JSON → 执行 → 截断结果
response = await chat_completion(messages, tools=tool_defs)
for tc in response.tool_calls:
    result = execute_tool(tc.function.name, json.loads(tc.function.arguments))
    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:8000]})

# 可选改进：增加"代码执行模式"（类似 CodeAgent）
# 在某些阶段（如 planning、testing），让 agent 输出 Python 代码
# 在 sandbox 中执行，支持多步骤组合
code = "result = web_search('竞品分析'); print(result)"
sandbox_result = await execute_python_in_sandbox(code)
messages.append({"role": "tool", "content": sandbox_result})
```

**代码改动位置**：
- `agent_runtime.py` —— 新增 `_execute_code_action()` 方法
- `services/tools/` —— 新增一个 `python_sandbox` 工具（基于 `LocalPythonExecutor` 或 Docker）

#### 方案 B（激进）：用 smolagents 替换部分 tool calling

在某些阶段（如 planning 需要大量搜索和分析），直接用 smolagents 的 CodeAgent 替代自研 AgentRuntime：

```python
from smolagents import CodeAgent, LiteLLMModel

# 在 pipeline 的 planning 阶段使用
planning_agent = CodeAgent(
    tools=[web_search, browser_extract, file_read],
    model=LiteLLMModel(model_id="gpt-4o"),
    max_steps=15,
)
result = planning_agent.run("研究竞品X的定价策略，输出报告")
```

### 6.4 接入后的实质效果

| 维度 | 当前 | 参考 smolagents 后 |
|------|------|--------------------|
| 工具调用次数 | 每个工具一个 LLM 请求 | 一次代码执行多个工具 |
| 中间结果 | 截断 8000 字符 | 变量在内存中完整保留 |
| 复杂逻辑 | 需 agent 多次循环 | Python 天然支持循环/条件 |
| 代码执行安全 | 无 sandbox | AST 白名单 / Docker 沙箱 |

**一句话**：减少 30% LLM 调用次数，中间结果不再被截断。

### 6.5 建议：不直接接入，提取设计模式

和 LangChain 一样，smolagents 的代码模式可以作为参考但**不需要 pip install**。最好的做法是：

> 在你的 `agent_runtime.py` 中增加"代码执行模式"作为 tool calling 的补充，而不是完全替换。

这样你的 agent 在需要时可以生成 Python 代码（多个工具组合 + 循环），而不是每次只能调一个 JSON tool。

优先级：**P2**（先做 OpenClaw 和 DeerFlow 之后再考虑）。

---

## 七、Claude Agent SDK 接入

### 7.1 概述

| 项目 | Stars | 定位 | 语言 |
|------|-------|------|------|
| **Claude Agent SDK** | ~1.5k ⭐ | Anthropic 官方 Agent SDK | Python / TypeScript |

**核心**：Claude Agent SDK 是 Claude Code 背后相同的 agent 循环、工具系统和上下文管理作为可调用的库。支持 `query()` 单次调用或 `ClaudeSDKClient` 持续对话。

内置工具：Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch, Skill, Subagent

### 7.2 对你项目的价值

你的项目已经重度依赖 Anthropic 模型（Claude Code CLI 用于代码生成，Claude API 用于某些 LLM 调用）。Claude Agent SDK 是 **最贴近你现有技术栈** 的外部框架。

#### 有价值的点

| Claude Agent SDK 能力 | 你的现状 | 价值 |
|----------------------|----------|------|
| **同进程 MCP Server** | `services/mcp_bridge.py` 自研 | SDK 的开箱即用 MCP 更成熟 |
| **Skills 文件系统** | skills/ 目录 + skill_loader.py | 借鉴其自动发现机制 |
| **Subagent** | `delegate_to_agent` 自研 | SDK 的 subagent 带完整生命周期 |
| **生命周期 Hooks** | 自研 `stage_hooks.py` | SDK 的 PreToolUse / SessionStart 回调 |
| **权限控制** | 自研 `mcp_tool_allowed()` + ROLE_TOOL_WHITELIST | SDK 的 PermissionMode 更精细 |
| **session 管理** | 自研 | SDK 的 ClaudeSDKClient 多轮对话 |

#### 具体改动

**场景**：用 Claude Agent SDK 替换 `executor_bridge.py` 中的 Claude Code CLI subprocess 调用。

当前 `executor_bridge.py`（约第 34-80 行）：
```python
# 当前：启动 Claude Code CLI 子进程
proc = await asyncio.create_subprocess_exec(
    "claude", "-p", prompt,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

改进为 Claude Agent SDK 的同进程调用：
```python
# 使用 Claude Agent SDK 替代子进程
from claude_agent_sdk import query

async for msg in query(
    prompt,
    options=ClaudeAgentOptions(
        allowedTools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        permissionMode="acceptEdits",
        mcpServers=[{"name": "agent-hub-tools", "url": "http://localhost:8000/mcp"}],
    ),
):
    if msg.type == "message":
        result = msg.content
```

**优势**：
- 不需要子进程，降低资源开销
- 支持流式输出（逐 token）
- 可集成 MCP 工具
- 权限控制比自研更细粒度

### 7.3 接入方案

#### 步骤 1：pip install

```bash
pip install claude-agent-sdk
```

#### 步骤 2：替换 executor_bridge 的核心调用

`backend/app/services/executor_bridge.py` 中，将启动 Claude Code CLI 子进程的逻辑替换为 SDK `query()`。

#### 步骤 3：可选 — 用 Agent SDK 替换 codegen_agent 的 LLM 调用

`codegen_agent.py` 中，代码生成阶段的 LLM 调用从自研 `chat_completion` 切换到 SDK，获得更精细的生成控制和流式反馈。

### 7.4 风险

| 风险 | 等级 | 说明 |
|------|------|------|
| **只支持 Claude 模型** | 🟡 | SDK 只能调 Anthropic，不能用于 OpenAI/DeepSeek 等其他 provider |
| **2026 年 6 月 15 日起单独计费** | 🟡 | 按 token 计费（Pro $20/月信用额），超量后需手动开启 overflow |
| **新项目，API 可能变化** | 🟡 | 1.5k⭐，还比较新 |

### 7.5 接入后的实质效果

| 维度 | 当前 | 接入后 |
|------|------|--------|
| **Claude Code 集成** | 子进程启动 CLI | **同进程 SDK 调用**，资源开销更低 |
| **流式输出** | 不支持 | 支持逐 token 流式 |
| **MCP 集成** | 自研桥接 | SDK 原生 MCP 支持 |
| **权限控制** | 自研 whitelist | SDK 5 种 PermissionMode |
| **技能系统** | 自研 SKILL.md 加载 | SDK 自动发现 skills |

### 7.6 建议：P1，但不着急

你的 `executor_bridge.py` 已经可以正常工作（启动 Claude Code CLI 子进程）。SDK 切换不改变功能，只改进实现方式——更稳定、更可控。

**优先做 OpenClaw 和 DeerFlow**，SDK 优化可以放在后面。

---

## 八、CrewAI 接入

### 8.1 概述

| 项目 | Stars | 定位 | 语言 |
|------|-------|------|------|
| **CrewAI** | 52.7k ⭐ | 角色多 Agent 编排 | Python |

**核心**：Agent 有 role / goal / backstory，组合成 Crew，通过 sequential 或 hierarchical 流程执行任务。

### 8.2 对你项目的价值

CrewAI 的**角色模型**和你的 14-role agent 体系高度相似：

```
你的 14 个 agent                CrewAI 的对应
─────────────────────           ────────────────────
Agent-cto                        Agent(role="CTO", goal="技术评审")
Agent-developer                   Agent(role="Developer", goal="编码")
Agent-qa                         Agent(role="QA", goal="测试验证")
agent_bus.py pub/sub             Process.hierarchical（管理 agent 协调）
DAG 模板（"web_app": [...]）     Crew(tasks=[...], process=Process.sequential)
```

### 8.3 有价值的模式：YAML 配置 Agent

CrewAI 允许用 YAML 文件定义 agent：

```yaml
# config/agents.yaml
research_agent:
  role: "高级研究员"
  goal: "深入研究{ topic }并输出全面报告"
  backstory: "你有 10 年行业研究经验..."
  allow_delegation: false
```

你的 `agents/seed.py` 目前用硬编码 dict 定义 agent 角色和工具白名单。改用 YAML 后：

| 当前（seed.py） | 改进（YAML 配置） |
|---|---|
| 修改角色需改代码 | 修改角色只需改 YAML |
| 新增角色需 PR | 新增角色只需添加 YAML 文件 |
| 12 个角色写在一个文件中 | 每个角色一个 YAML 文件，清晰 |

### 8.4 有价值的模式：Flow 状态管理

CrewAI 推荐在生产环境使用 `Flow` 作为入口：

```python
class AgentHubFlow(Flow):
    @start()
    def planning(self):
        return Crew(agents=[pm], tasks=[plan_task]).kickoff()

    @router(planning)
    def should_proceed(self):
        if self.state.plan_approved:
            return "development"
        return "revise"

    @start()
    def development(self):
        return Crew(agents=[dev], tasks=[build_task]).kickoff()
```

这比你的 `execute_dag_pipeline()` 函数更结构化。**借鉴点**：用装饰器标记阶段入口和路由，而不是在函数体内 if/else。

### 8.5 接入方案：不接入代码，提取设计模式

**CrewAI 不需要 pip install**。借鉴它的几个设计模式就够了：

#### 借鉴 1：YAML 化 agent 定义

创建 `skills/public/agents/` 目录，每个 agent 一个 YAML：

```yaml
# skills/public/agents/developer.yaml
role: "Developer"
goal: "实现高质量的代码"
backstory: "你是一名全栈工程师..."
tools:
  - file_read
  - file_write
  - bash
  - delegate_to_agent
  - deerflow_delegate
```

然后增加一个简单的 YAML 加载器，替代 `agents/seed.py` 中的硬编码。

#### 借鉴 2：Flow 装饰器模式

在你的 `dag_orchestrator.py` 中，借鉴 CrewAI 的装饰器风格：

```python
# 当前：execute_dag_pipeline() 内 if/else 判断阶段状态
# 改进：装饰器标记
@dag_stage("planning", depends_on=[])
async def planning(ctx):
    return await execute_stage(db, task_id, "planning", ...)

@dag_stage("design", depends_on=["planning"])
async def design(ctx):
    return await execute_stage(db, task_id, "design", ..., 
                                previous_outputs={"planning": ctx.results["planning"]})
```

#### 借鉴 3：CrewAI 的记忆系统分层

CrewAI 的 3 层记忆（短期 ChromaDB、长期 SQLite、上下文组装）和你类似，但它的上下文自动注入（agent 不需要知道怎么查记忆）值得借鉴。你的 `memory.py` + `learning_engine.py` 的注入逻辑可以简化。

### 8.6 接入后的实质效果

| 维度 | 当前 | 参考 CrewAI 后 |
|------|------|----------------|
| **Agent 定义** | Python dict 硬编码 | **YAML 文件配置**，可热加载 |
| **DAG 调度** | `execute_dag_pipeline()` 函数体内 if/else | **装饰器标记** + 自动拓扑排序 |
| **记忆注入** | 手动调 `get_context_from_history()` | **自动上下文组装** |

### 8.7 建议：P3，低优先级

CrewAI 的模式借鉴涉及**重构 agent 定义系统**，不是直接加功能。建议在 agent 数量从 12 个增长到 20+ 时再考虑 YAML 化。现在保持现状。

---

## 九、完整对比表

| 项目 | 对你的帮助 | 接入方式 | 优先级 | 预期效果 |
|------|-----------|----------|--------|----------|
| **OpenClaw** | 新增 10+ 消息渠道 | 部署实例 → 调 Gateway API | **P0** | 微信/Telegram 等发需求 |
| **DeerFlow** | Sandbox + sub-agent | Docker 部署 → pipeline 集成 | **P0** | 深度研究 + 安全执行 |
| **Claude Agent SDK** | 替代 Claude CLI 子进程 | pip install → 替换 executor_bridge | **P1** | 同进程调用，资源更低 |
| **smolagents** | 代码执行模式 | 提取设计模式改 agent_runtime | **P2** | 减少 30% LLM 调用 |
| **CrewAI** | YAML agent 定义 + 装饰器调度 | 提取设计模式 | **P3** | 可热加载 agent 配置 |
| **Hermes 反思** | 语义级学习 | 改 learning_engine | **P2** | agent 越用越好 |

## 十、核心结论

```
P0 (立即做) → OpenClaw + DeerFlow
  └─ 代码已写，只差部署运行

P1 (短期) → Claude Agent SDK
  └─ 替换 executor_bridge 子进程

P2 (中期) → smolagens 模式 + Hermes 反思
  └─ 改善 agent 效率和自学习

P3 (远期) → CrewAI 模式
  └─ 重构 agent 定义系统
```

### OpenClaw 风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| OpenClaw 已被 OpenAI 收购，项目走向不确定 | 🟡 | 它保持了开源+模型无关，短期无风险；后续可考虑自研最小 IM 桥接 |
| 增加一个外部依赖进程 | 🟢 | Docker 管理，出问题不影响 pipeline 主进程 |

### DeerFlow 风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 多一个进程 = 多一个故障点 | 🟡 | Docker restart=unless-stopped；pipeline 中走 DeerFlow 失败可 fallback 到自研 AgentRuntime |
| DeerFlow 需要额外的 LLM API key 配额 | 🟡 | 控制只对"深度研究"阶段走 DeerFlow，普通阶段仍走自研 |
| DeerFlow 2.0 和项目现有的 `deerflow_tool.py` API 兼容性 | 🟢 | CDD 代码已经对接 LangGraph API，DeerFlow 2.0 的 API 向后兼容 |

### Hermes 风险

无（纯代码改进，不改架构）

---

## 七、核心结论

```
上线 OpenClaw → 用户从任意 IM 发需求 → 推到用户的聊天窗口
上线 DeerFlow → agent 能处理复杂深度研究 + sandbox 安全执行
改进 Hermes   → agent 越用越好，从"会做"到"擅长"
```

**最值得立即做**：OpenClaw（已有完整 Gateway API 等着被调用）和 DeerFlow（已有 `deerflow_tool.py` + Docker 一键部署）。两个都是"代码已写好，只差跑起来"的状态。

**Hermes** 不紧急，现有的 `hermes_oversight.py` 已经在工作了。反思循环的改进是锦上添花。
