# Issue #22 — 系统全面诊断：渠道、模型、MCP/Skills/Rules 接入真实状态

> 日期: 2026-04-23
> 触发: 用户质疑 "飞书/QQ/OpenClaw/Hermes-Agent/Claude Code 有验证接入？模型怎么接入的？MCP/Skills/Rules 使用了吗？"

---

## 一、渠道接入状态（Gateway）

### 总表

| 渠道 | 代码存在 | 路由注册 | 端到端测试 | 实际可用 | 结论 |
|------|---------|---------|-----------|---------|------|
| **飞书** | ✅ 完整 handler | `/api/gateway/feishu/webhook` | ❌ 仅 token guard 测试 | ⚠️ 需要公网隧道 + 飞书配置 | **未验证** |
| **QQ (OneBot)** | ✅ OneBot v11 子集 | `/api/gateway/qq/webhook` | ❌ 仅 403 测试 | ⚠️ 需要 NapCat/go-cqhttp | **未验证** |
| **OpenClaw** | ✅ REST + 计划模式 | `/api/gateway/openclaw/intake` | ⚠️ plan mode 有测试 | ✅ HTTP 可达 (400 = 参数校验) | **部分验证** |
| **Slack** | ✅ Events API | `/api/gateway/slack/webhook` | ❌ 无测试 | ✅ URL verification 通过 (200) | **未验证** |
| **OpenAI 兼容** | ✅ chat/completions | `/v1/agent-hub/chat/completions` | ❌ 无测试 | ✅ 可达 (200) | **部分验证** |
| **Hermes-Agent** | ❌ 无任何代码 | — | — | — | **不存在** |
| **Claude Code** | ✅ 执行器（非网关） | executor_bridge.py | ❌ 依赖 CLI 安装 | ⚠️ 取决于本地 claude CLI | **未验证** |
| **微信小程序** | ✅ 部署 API（非消息网关） | `/api/deploy/miniprogram` | ❌ 无测试 | ⚠️ 需要 appid/secret/key | **未验证** |

### 各渠道详情

#### 1. 飞书（Feishu）
- **代码**: `gateway.py` 飞书 webhook、`feishu_event.py` AES 解密/token 验证、`feishu_im.py` 外发消息/互动卡片
- **消息流**: POST → 解密 → token 验证 → 提取消息 → 意图识别(计划/反馈/新任务) → 创建 pipeline task → 后台执行
- **问题**: 仅有 token 缺失时 503/403 的测试。没有任何模拟飞书真实 event 的集成测试。.env 中 `FEISHU_APP_ID`/`FEISHU_APP_SECRET` 已填写，但从未有日志证明实际接收过飞书消息
- **协调机制**: 与其他渠道共享 `_clarify_or_create_task` → `_run_pipeline_background` 通路，但 **渠道间不互通**，无跨渠道消息转发

#### 2. QQ (OneBot v11)
- **代码**: `gateway.py` QQ webhook、`qq_onebot.py` 外发消息
- **消息流**: POST (OneBot JSON) → Bearer 认证 → 提取 text/user_id → 同 Feishu 后续路径
- **问题**: 仅有 auth 拒绝测试。`QQ_BOT_ENDPOINT` / `QQ_BOT_ACCESS_TOKEN` 在 .env 中 **未配置**

#### 3. OpenClaw
- **代码**: `gateway.py` REST intake + plan approve/reject/revise、`openai_compat.py` OpenAI 格式桥接
- **消息流**: POST /intake → Bearer(PIPELINE_API_KEY) 认证 → 创建 task → pipeline 后台执行
- **问题**: plan mode 有功能测试（`test_gateway_plan_mode.py`），但 **未验证真实 LLM 执行结果**
- **状态**: 技术上可达，是目前最接近"能用"的渠道

#### 4. Hermes-Agent
- **代码**: 项目中 **零代码**。grep hermes 无任何结果
- **结论**: **完全不存在**。仅在 GitHub fork 列表中出现

#### 5. Claude Code
- **不是网关渠道**，而是代码执行器
- **代码**: `executor_bridge.py` 调用 `claude` CLI 子进程、`codegen_agent.py` 编排
- **问题**: 不在 pipeline `execute_stage` 主流程中。是 E2E orchestrator 的独立步骤
- **前提**: 需要本地安装 `claude` CLI 且设置 `EXECUTOR_ALLOWED_DIRS`

### 渠道间协调机制
**不存在。** 所有渠道共享相同的后端处理函数（`_clarify_or_create_task`、`_run_pipeline_background`），但：
- 飞书任务不知道 QQ 在做什么
- 没有跨渠道消息路由/广播
- 没有统一的会话管理
- 每个渠道独立创建 pipeline task，互不感知

---

## 二、模型接入状态

### Provider 配置

| Provider | API Key | 可用模型 | 实际状态 |
|----------|---------|---------|---------|
| **智谱 (Zhipu)** | ✅ 已配置 | glm-4-plus, glm-4-flash | ✅ 可用（但有速率限制 1302） |
| **Anthropic** | ✅ 已配置 | claude-opus-4, claude-sonnet-4 | ❌ key 实际指向 code.ppchat.vip 代理，代理返回 401 "令牌不可用" |
| **DeepSeek** | ❌ 空 | deepseek-chat | ❌ 不可用 |
| **OpenAI** | ❌ 空 | gpt-4.5, gpt-4o, gpt-4o-mini | ❌ 不可用 |
| **Google** | ❌ 空 | gemini-2.5-pro, gemini-2.5-flash | ❌ 不可用 |
| **Qwen** | ❌ 空 | qwen-plus, qwen-turbo | ❌ 不可用 |
| **本地 LLM** | ⚠️ 指向 code.ppchat.vip | google/gemma-4-26b-a4b | ❌ 代理 key 失效 (401) |

### 实际可用模型
**仅智谱 glm-4-flash / glm-4-plus**，且受免费账户速率限制（错误码 1302/1303）。

### 模型选择机制（planner_worker.py）
```
PLANNING 层: glm-4-plus → claude-opus → gpt-4.5 → deepseek-chat → gemini-2.5-pro
EXECUTION 层: glm-4-flash → claude-sonnet → gpt-4o → deepseek-chat  
ROUTINE 层: glm-4-flash → deepseek-chat → gpt-4o-mini → qwen-plus
```
- 根据角色/阶段选择 tier → 从对应 tier 的模型列表中选第一个有 key 的 provider
- 当前实际效果：**所有阶段都只能选 glm-4-flash 或 glm-4-plus**

### Fallback 机制（llm_router.py）
- `chat_completion_with_fallback` 最多尝试 3 个 provider
- 可重试条件: 402/408/429/500/502/503/504 + "rate limit"/"quota"/"insufficient balance" 等关键词
- 401/403 **不重试**（视为 key 错误）
- **当前问题**: fallback chain (deepseek→openai→anthropic→qwen→zhipu→google) 中只有 zhipu 有 key，等于 **没有 fallback**

### 自测时的模型使用
**自测脚本没有调用任何 LLM。** 12 个项目全是手动 advance + 手写假内容，完全绕开了模型调用。

### 处理建议（模型不可用时应该做什么）
当前系统 **确实有** 降级和 fallback 代码，但因为只配了 1 个 provider，机制形同虚设。需要：
1. 至少配置 2-3 个 provider key 才能让 fallback 生效
2. cost_governor 的降级模型列表全部依赖有 key 的 provider
3. 速率限制下应该有排队/等待机制，而不是直接报错

---

## 三、MCP / Skills / Plugins / Rules 使用状态

### Skills（技能系统）

| 项目 | 状态 |
|------|------|
| 技能定义 | ✅ 45 个 skill 已加载（DB + 文件系统） |
| 分类映射 | ✅ STAGE_SKILL_MAP 将阶段映射到技能类别 |
| Pipeline 注入 | ⚠️ 仅作为 system_prompt 文本追加，不是独立执行 |
| 技能执行 | ❌ `execute_skill` 仅在 Skills API 可用，Pipeline 不调用 |

**Pipeline 中 Skills 的实际效果**:
- planning 阶段匹配 `["product", "analysis", "prd", "general"]` 类别的 skill
- 匹配到的 skill prompt 被 **追加到 system_prompt 末尾**
- 但 **不是独立调用技能**，只是给 LLM 更多上下文文字
- 例如 `prd-expert` skill 的 prompt 会追加到 CEO Agent 的 system prompt

### MCP（Model Context Protocol）

| 项目 | 状态 |
|------|------|
| MCP 客户端 | ✅ `mcp_client.py` 支持 HTTP/SSE/Streamable |
| MCP 服务器管理 | ⚠️ API 路由 404（可能未注册或路径问题） |
| Pipeline 中使用 MCP | **❌ 完全没有接入** |
| Agent run 中使用 MCP | ✅ `/api/agents/{id}/run` 可加载 MCP tools |

**关键问题**: Pipeline 的 `execute_stage` **不加载任何 MCP 工具**。MCP 仅在独立的 Agent run API 中可用。这意味着：
- Planning 阶段不能调用外部搜索 MCP
- Development 阶段不能调用 GitHub MCP 创建 repo
- Testing 阶段不能调用任何外部测试工具
- 每个阶段都是 "纯文本生成"，不能执行任何外部操作

### Plugins（插件）

| 项目 | 状态 |
|------|------|
| Plugin 模型 | ✅ `AgentPlugin` DB 表存在 |
| Plugin API | ✅ Agent API 可返回 plugin 信息 |
| Plugin 运行时 | **❌ 不存在**。Pipeline 中无任何 plugin 调用代码 |

### Rules / Guardrails（规则 / 护栏）

| 项目 | 状态 |
|------|------|
| Guardrails | ✅ `evaluate_guardrail` 在 `execute_stage` 中调用 |
| 实际效果 | ⚠️ 大多数阶段 action 不匹配任何规则，走 auto_approve |
| 特殊阶段 | `security-review` 强制 REQUIRE_REVIEW |
| Agent Rules (DB) | ❌ Pipeline 不读取 `AgentRule` 表 |
| 沙盒规则 | ✅ `sandbox_overrides.py` 控制工具白名单，但仅限 tool 执行路径 |

### Tool 使用（Agent 工具调用）

| 项目 | 状态 |
|------|------|
| Agent 工具定义 | ✅ 14 个 Agent 共 184+ 个工具（file_read/write, bash, git, browser, test 等） |
| Pipeline 中工具调用 | ⚠️ **只有当 AGENT_TOOLS 非空时才启用** tool loop |
| MCP 工具在 Pipeline | **❌ 不传入** |
| 代码执行 | ✅ `executor_bridge.py` 可调用 claude CLI，但不在 pipeline 主流程 |

---

## 四、核心问题总结

### A. 渠道接入（飞书/QQ/OpenClaw 等）
1. **代码写了，但从未验证过端到端** — 没有一个渠道有完整的 "消息进 → Agent 处理 → 结果回" 的测试证明
2. **Hermes-Agent 根本不存在** — 零代码
3. **渠道间无协调** — 各自独立创建任务，互不知晓
4. **Claude Code 是执行器不是网关** — 不在 pipeline 主流程中

### B. 模型接入
1. **6 个 Provider 只配了 1 个能用的 (智谱)** — Anthropic key 实际失效，其余全空
2. **Fallback 机制存在但形同虚设** — 只有 1 个 provider 时无法 fallback
3. **自测完全没调用 LLM** — 12 个项目用假数据跑的
4. **速率限制直接报错** — 没有排队/等待/重试间隔机制

### C. MCP / Skills / Rules
1. **MCP 完全没接入 Pipeline** — 代码有但没连起来
2. **Skills 只是 prompt 文字追加** — 不是独立能力执行
3. **Plugins 是空壳** — DB 有表，运行时无调用
4. **Rules 大多走 auto_approve** — 没有实质性的阶段控制

### D. 整体架构断裂
```
期望:  渠道消息 → Agent调度 → 调用MCP/Skills/Tools → 生成真实产物 → 评审 → 回复
实际:  渠道消息 → 创建task → LLM生成文本 → 存markdown → 结束
```

---

## 五、要修什么（优先级排序）

### P0: 让系统能"跑通"
1. **修复模型接入**: 至少配置 2 个可用 provider (zhipu + deepseek/qwen)
2. **验证飞书接入**: 用 ngrok 隧道 + 真实飞书 bot 跑一次 "消息 → 任务 → 回复" 全链路
3. **Pipeline 接入 MCP**: `execute_stage` 加载 agent 对应的 MCP tools，让 Agent 能调用外部工具

### P1: 让 Agent "做事"
4. **Skills 变为可执行**: 不仅追加 prompt，而是在阶段完成后调用 `execute_skill` 生成标准产物
5. **开发阶段接入代码执行**: Development stage 调用 `codegen_agent` 或 `executor_bridge`，在 worktree 中创建真实代码文件
6. **测试阶段调用 test_execute**: Testing stage 用 QA Agent 的 `test_execute` 工具运行实际测试

### P2: 让产物"可见"
7. **每个阶段产出写入文件**: planning → `PRD.md`、design → `DESIGN.md`、architecture → `ARCHITECTURE.md`
8. **前端展示真实文件**: 在 8-Tab 交付视图中直接预览 markdown / 代码文件
9. **评审闭环**: Reviewer 产出后触发 review → approve/reject → v2 循环

### P3: 渠道联通
10. **渠道验证**: 逐一验证飞书/QQ/Slack 端到端
11. **跨渠道通知**: 任务状态变更广播到所有已配置渠道
12. **移除幽灵集成**: Hermes-Agent 从文档中移除

---

## 六、自测项目应该怎么做（正确的方式）

之前 12 个项目的自测是 **API 管道测试**，不是 **业务验证**。正确的自测应该是：

```
1. 通过飞书/OpenClaw 发送 "开发一个考勤系统"
2. 系统自动创建 pipeline task
3. CEO Agent 用真实 LLM 生成 PRD，写入 PRD.md 文件
4. Designer Agent 生成 UI 规范，调用 browser_screenshot 工具截图
5. Architect Agent 生成架构文档，调用 file_write 创建目录结构
6. Developer Agent 调用 codegen + bash 工具，在 worktree 创建代码框架
7. QA Agent 调用 test_execute 运行测试，输出测试报告
8. Reviewer Agent 评审所有产出，给出 APPROVE/REJECT
9. DevOps Agent 生成 Dockerfile + CI/CD 配置
10. 结果通过飞书/渠道返回给用户
11. 用户可以在 UI 的 8-Tab 视图中查看所有真实产物
```

每一步都应该有 **真实文件产出**，而不是 markdown 文本存在 stage output 里。

---

## 七、从 Fork 项目中学到什么（提取强项 → 补自己短板）

> 深度研究了 coze-studio、agency-agents-zh、gstack、hermes-agent、oh-my-claudecode、superpowers、everything-claude-code 7 个项目

### 对照表：别人做了什么 vs 我们缺什么

| 维度 | 别人怎么做的 | agent-hub 现状 | 差距 | 要学的 |
|------|------------|---------------|------|--------|
| **Agent 定义** | agency-agents-zh: 211个角色，每个有人格/使命/规则/工作流/交付物模板/成功指标 | 14 个 agent，只有 name + tools 列表，无人格、无工作流、无交付物模板 | **巨大** | 每个 Agent 需要完整的角色卡：人格 + 规则 + 工作流 + 输出模板 |
| **Skills 框架** | gstack: YAML frontmatter(name/version/allowed-tools/触发描述) + 分阶段流程 + 硬性门禁 + 学习日志 | 45个skill只有prompt文本，无版本、无门禁、无学习 | **大** | Skill 需要 frontmatter 元数据 + 阶段流程 + 完成条件 |
| **Skill 路由** | superpowers: "先查技能再行动"强制规则，harness 启动时加载元数据按意图匹配 | skill_marketplace 按 category 粗粒度匹配，追加到 prompt 了事 | **中** | 执行前强制 skill 路由步骤 |
| **多 Agent 协调** | oh-my-claudecode: plan→PRD→exec→verify→fix 五阶段流水线，每阶段有验证清单 | DAG 有阶段但无验证清单，verify 依赖 LLM 自评不可靠 | **大** | 每阶段需要明确的验证检查项（build/test/lint/functional） |
| **Agent 成长** | hermes-agent: 技能自动创建/自我改进 + FTS5会话搜索 + 用户画像持续更新 | memory.py 存储/检索，但无自动技能创建，无会话搜索 | **大** | 添加技能生命周期：创建→使用→改进→版本化 |
| **工作流引擎** | coze-studio: Canvas JSON → 编译为内部 Schema → 统一执行器(sync/async/stream/resume) + 节点适配器模式 | pipeline_engine 硬编码阶段列表，dag_orchestrator 有拓扑排序但无 resume/checkpoint | **大** | 用节点适配器模式重构，支持 resume/checkpoint |
| **插件/工具** | coze-studio: OpenAPI 3 描述 + manifest JSON 注册，workflow 也是 tool（workflow-as-tool） | Plugin DB 有表无运行时，MCP client 有但 pipeline 不加载 | **巨大** | Plugin = OpenAPI spec + runtime handler；MCP 接入 pipeline |
| **模型管理** | coze-studio: 抽象 ChatModel 接口 + per-provider builder + admin 管理 instance (DB) | 硬编码 provider endpoints + .env keys | **中** | 模型实例 DB 化，admin 可管理 |
| **记忆/状态** | oh-my-claudecode: .omc/ 控制面/数据面分离，artifact descriptor(kind/path/hash/producer) | stage output 存 DB text 字段，无结构化 artifact 描述 | **中** | Artifact 需要结构化描述符 |
| **安全** | everything-claude-code: AgentShield 扫描 + hook 级 secret 检测 + MCP 审计日志 | guardrails 基础审批流 + sandbox 白名单 | **中** | 添加 secret 检测 + MCP 操作审计 |
| **Handoff 机制** | agency-agents-zh: NEXUS 协议，标准化 handoff 模板(sender/receiver/context/acceptance criteria) | 阶段之间通过 previous_outputs dict 传递，无标准化格式 | **大** | 标准化 Agent 交接协议 |
| **Rules 写法** | gstack: per-skill allowed-tools + 硬性门禁(HARD GATE) + 学习日志写入 | guardrails 仅 action 匹配，大多数 auto_approve | **大** | 每个阶段需要硬性规则 + 工具白名单 |

### 具体可提取复用的模式

#### 1. 从 agency-agents-zh 提取：Agent 角色卡标准格式

```markdown
# {角色名} Agent

## 人格
- 身份与记忆: ...
- 性格特征: ...

## 核心使命
1. 主要职责
2. 次要职责

## 关键规则（必须遵循）
- 规则 1: ...
- 规则 2: ...

## 工作流程
1. 第一步 → 产出: ...
2. 第二步 → 产出: ...

## 交付物模板
```markdown
## {文档类型}
### 概述
### 详细内容
### 验收标准
```

## 协作委托
- 遇到 X 时 → delegate_to_agent("architect", "需要架构评审", context)
- 遇到 Y 时 → delegate_to_agent("security", "需要安全审查", context)

## 成功指标
- 指标 1: ...
- 指标 2: ...
```

**落地方式**: 改造 `backend/app/agents/seed.py`，为每个 Agent 增加完整的角色卡字段（persona/mission/rules/workflow/output_template/success_metrics），存入 `AgentDefinition` 表。

#### 2. 从 gstack 提取：Skill YAML 元数据标准

```yaml
name: prd-expert
version: 2.1.0
description: |
  当用户需要撰写产品需求文档、分析用户故事、定义验收标准时调用此技能。
  适用于 planning 阶段的 CEO/Product Agent。
allowed-tools:
  - web_search
  - file_write
  - delegate_to_agent
preamble-tier: standard
trigger-stages:
  - planning
completion-criteria:
  - 包含至少 5 条用户故事
  - 每条用户故事有对应验收标准
  - 包含非功能需求章节
  - 包含风险评估章节
```

**落地方式**: 扩展 `Skill` 模型，增加 `version`/`allowed_tools`/`trigger_stages`/`completion_criteria` 字段。`skill_marketplace.py` 的 `get_skills_for_stage` 改用 `trigger_stages` 精确匹配。

#### 3. 从 oh-my-claudecode 提取：阶段验证清单

```python
STAGE_VERIFICATION = {
    "planning": {
        "checks": ["has_user_stories", "has_acceptance_criteria", "has_milestones"],
        "min_sections": 5,
        "required_sections": ["目标用户", "功能范围", "用户故事", "验收标准", "里程碑"],
    },
    "design": {
        "checks": ["has_design_tokens", "has_page_layouts", "has_component_list"],
        "min_sections": 4,
        "required_sections": ["设计Token", "核心页面布局", "组件清单", "交互流程"],
    },
    "architecture": {
        "checks": ["has_tech_stack", "has_data_model", "has_api_design"],
        "min_sections": 5,
        "required_sections": ["技术选型", "数据模型", "API设计", "前端架构", "实现路线图"],
    },
    "development": {
        "checks": ["has_code_files", "has_project_structure", "builds_successfully"],
        "file_checks": True,  # 检查 worktree 中是否有真实文件
    },
    "testing": {
        "checks": ["has_test_cases", "has_execution_result", "coverage_report"],
        "execution_required": True,  # 必须有实际执行记录
    },
}
```

**落地方式**: 在 `self_verify.py` 中增加结构化验证，不仅依赖 LLM 自评，还做硬性检查（必备章节、最小长度、文件存在性）。

#### 4. 从 coze-studio 提取：Plugin = OpenAPI Spec 模式

```python
# 当前: Plugin 只是 DB 记录
# 改造: Plugin 关联 OpenAPI spec，运行时可调用

class PluginRuntime:
    def __init__(self, spec_url: str, auth: dict):
        self.spec = load_openapi_spec(spec_url)
        self.tools = self._extract_tools()
    
    def _extract_tools(self) -> list:
        """将 OpenAPI paths 转换为 LLM tool definitions"""
        tools = []
        for path, methods in self.spec.paths.items():
            for method, operation in methods.items():
                tools.append({
                    "name": operation.operation_id,
                    "description": operation.summary,
                    "parameters": self._schema_to_params(operation),
                })
        return tools
    
    async def execute(self, tool_name: str, args: dict) -> str:
        """实际调用 OpenAPI 端点"""
        ...
```

**落地方式**: `AgentPlugin` 表增加 `openapi_spec_url` 字段，`plugin_runtime.py` 解析 spec 生成 tools，注入 `AgentRuntime`。

#### 5. 从 superpowers 提取：强制 Skill 路由

```python
# 在 execute_stage 的最开始，强制走 skill 路由
async def _skill_preflight(db, stage_id, task_description):
    """superpowers 模式：先查技能再行动"""
    matching_skills = await get_skills_for_stage(db, stage_id, role="")
    if matching_skills:
        # 不是追加到 prompt，而是作为独立执行步骤
        for skill in matching_skills:
            if skill.get('execution_mode') == 'pre_stage':
                # 阶段开始前执行：如 research-first 搜索背景资料
                context = await execute_skill(db, skill['id'], task_description)
                # 搜索结果注入到 user message 中作为参考资料
                ...
            elif skill.get('execution_mode') == 'post_stage':
                # 阶段完成后执行：如验证产出格式、写入文件
                ...
```

**落地方式**: 在 `pipeline_engine.py` 的 `execute_stage` 中，阶段执行前后各加一个 skill hook 点。

#### 6. 从 hermes-agent 提取：Agent 学习循环

```python
# 任务完成后，从 review feedback 自动提炼学习
async def extract_learning(task_id, stage_id, feedback):
    """hermes 模式：从评审反馈中自动创建/改进技能"""
    if feedback.get("type") == "REJECT":
        # 被拒绝的产出 → 分析原因 → 生成改进建议
        learning = {
            "stage": stage_id,
            "pattern": "当被要求..., 应该..., 而不是...",
            "confidence": 0.6,
            "source_task": task_id,
        }
        await store_learning(learning)
        # 累计相同 pattern 的 learning 达到阈值 → 自动生成 skill
        if await count_similar_learnings(learning["pattern"]) >= 3:
            await auto_create_skill(learning)
```

**落地方式**: 扩展 `learning_loop.py`，在 review reject 时提取 pattern，累积后自动创建 skill。

---

## 八、落地优先级（基于学习成果重排）

### 执行顺序（按依赖链排，下层不通上层白搭）

```
                    ┌─────────────────────┐
            Level 5 │  渠道验证 + 评审闭环   │  ← 飞书/QQ 端到端
                    └──────────┬──────────┘
                    ┌──────────┴──────────┐
            Level 4 │  Agent 角色卡 + 学习    │  ← 人格/规则/交付物模板
                    └──────────┬──────────┘
                    ┌──────────┴──────────┐
            Level 3 │  产出写真实文件 + 验证   │  ← PRD.md / 代码文件 / 测试报告
                    └──────────┬──────────┘
                    ┌──────────┴──────────┐
            Level 2 │  Pipeline 接入工具执行   │  ← MCP + Skills hook + tool loop
                    └──────────┬──────────┘
                    ┌──────────┴──────────┐
            Level 1 │  模型可靠运行           │  ← 至少2个Provider + 重试机制
                    └─────────────────────┘
```

### Step ① 模型可靠运行（2-3天）✅ 已完成

> 没模型什么都跑不了。当前只有智谱且有速率限制。

**任务清单**:
1. ✅ 配置公司服务器双模型 Provider：
   - `google/gemma-4-26b-a4b` — Execution/Routine 层（通用生成）
   - `qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled@q6_k` — Planning 层（推理蒸馏，架构/审查）
   - 服务器 `192.168.130.230:1234` (LM Studio)，10个可用模型
2. ✅ llm_router 已有 429 速率限制重试（`_RATE_LIMIT_BACKOFFS = [2.0, 4.0, 8.0]`，`chat_completion_with_retry`）
3. ✅ 应用启动时 `probe_all_providers()` 后台探测（改为非阻塞，不阻塞启动）
4. ✅ unhealthy provider 优雅降级：`execute_stage` 用 `get_provider_health()` 过滤
5. ✅ `planner_worker.py` TIER_MODELS 重排：local → zhipu → deepseek → cloud
6. ✅ 修复 `reasoning_content` 字段提取（`_extract_openai_message_text` 已处理回退）
7. ✅ 修复 Context 超限：`MAX_PREV_OUTPUT_CHARS` 1500→800，适配 LM Studio 上下文窗口
8. ✅ 修复 `infer_provider` 将 qwen* 模型名误路由到云端问题（强模型 probe 显式传 api_url）
9. ✅ pipeline_engine 用 `resolved_provider` 判断 local，不仅依赖 `tier == "local"`

**E2E 验证结果 (zhipu 单模型)**:
| 阶段 | 状态 | 产出 | LLM质量分 |
|------|------|------|-----------|
| planning | ✅ done | 2,185c | 0.5 |
| design | ✅ done | 4,879c | 0.4 |
| architecture | ✅ done | 12,947c | 0.6 |
| development | ✅ done | 16,995c | 0.5 |
| testing | ✅ done | 8,413c | 0.1 |
| reviewing | ✅ done | 0c | - |
| deployment | ✅ done | 0c | - |
| **总计** | | **45,419c** | **0.721** |

**E2E 验证结果 (local 双模型)**:
| 阶段 | 模型 | 产出 |
|------|------|------|
| planning | qwen-reasoning (强) | **6,092c** |
| design | gemma-4 (标准) | **7,337c** |
| architecture | 进行中... | ~10min/stage |
| **总计(2阶段)** | | **13,429c** |

**对比**: Local 双模型 planning 产出 6092c vs zhipu 2185c = **2.8x 更丰富**

**发现的问题**（进入 Step② 后修复）:
- quality gate 对 testing 阶段阈值过严 (score=0.1 就 blocked) → 需调优
- pipeline resume 在 `failed` 状态时需手动修复 → 需改进 resume 容错
- LM Studio 默认 context window 偏小 → 建议在 LM Studio 设置 `n_ctx >= 16384`
- 思维链模型推理较慢 (~1min/stage for 26B, ~2min for 35B) → 可接受

### Step ② Pipeline 接入工具执行 ✅ 已完成 (2026-04-24)

> 没工具 Agent 只能说不能做。这是"文本生成器"和"AI Agent"的分水岭。

**任务清单**:
1. ✅ `execute_stage` 加载 Agent 对应的 MCP tools（从 DB `AgentMcp` 读取）
2. ✅ `execute_stage` 传入 `dynamic_tools` + `dynamic_handlers` 给 `AgentRuntime`
3. ✅ Development 阶段接入 `file_write`/`bash` 工具 + **代码提取器后处理**
4. ✅ Testing 阶段接入 `test_execute` 工具 + **测试验证 hook**
5. ✅ 添加 Skill pre_stage/post_stage hook 点

**核心实现**:

| 模块 | 文件 | 说明 |
|------|------|------|
| 代码提取器 | `backend/app/services/code_extractor.py` | 从 LLM markdown 输出解析 ` ```lang:path ` 代码块，写成真实文件 |
| 阶段钩子 | `backend/app/services/stage_hooks.py` | pre/post hook 注册机制 + 3 个内置 hook |
| Pipeline集成 | `backend/app/services/pipeline_engine.py` | MCP加载 + 沙箱指向worktree + hook调用 |
| AgentRuntime修复 | `backend/app/services/agent_runtime.py` | 本地模型正确传 api_url |
| 模型路由修复 | `backend/app/services/planner_worker.py` | preferred_model 返回 provider 字段 |

**E2E 验证结果** (task: Step2测试：Python计算器CLI):

```
Pipeline stages: planning → design → architecture → development → testing → reviewing → deployment
Tool loop 触发: ✅ delegate_to_agent 被调用 (3842 chars)
代码提取器: ✅ 4 个文件提取成功:
  - src/config/settings.py (566B) — 配置常量和颜色
  - src/src/engine/parser.py (2.4KB) — AST安全表达式解析器
  - src/src/persistence/history_manager.py (1.4KB) — 历史记录管理
  - src/src/ui/terminal.py (1.4KB) — 终端交互界面
测试验证hook: ✅ has_code_blocks=True, content_length=6686
文档产出: 01-prd.md(5.6K), 02-ui-spec.md(6.9K), 04-impl.md(15K), 05-test.md(10K), 07-ops.md(7.6K)
```

**发现并修复的问题**:
- qwen-strong 模型被 `infer_provider` 误路由到 Dashscope（cloud）→ 修复 `resolve_model` 返回 provider 字段 + AgentRuntime 判断本地模型传 api_url
- `max_steps` 从 5 提升到 8，给工具循环更多回合
- Development system prompt 增加代码块格式要求，确保提取器能识别

### Step ③ 产出写真实文件 + 结构化验证 ✅ 已完成 (2026-04-24)

> 用户要看到东西，不是 DB 里的 text 字段。

**任务清单**:
1. ✅ 每阶段完成后将 output 写入 worktree 真实文件
2. ✅ 每阶段硬编码验证清单（必备章节、最小长度、代码块数、测试用例数、用户故事数）
3. ✅ 前端 8-Tab 视图直接预览 worktree 文件内容（源码文件可点击浏览）
4. ✅ 标准化 Artifact descriptor：`{ kind, path, content_hash, producer, version }`

**核心实现**:

| 模块 | 文件 | 说明 |
|------|------|------|
| 验证增强 | `self_verify.py` | 新增 design 阶段、code_blocks/code_files/test_cases/user_stories 4 个新检查 |
| Artifact 描述符 | `task_artifact.py` | 新增 `content_hash` 字段 |
| Artifact 写入 | `artifact_writer.py` | 计算 SHA256 hash、设置 `storage_path` |
| Worktree API | `backend/app/api/worktree.py` | `GET /tasks/{id}/worktree`(文件树) + `GET /tasks/{id}/worktree/{path}`(内容) |
| 代码浏览器 | `TaskCodeTab.vue` | 全新改版：显示源码文件列表、点击预览、文档状态、汇总统计 |
| 文档 Fallback | `TaskDocTab.vue` | 当 DB 无内容时自动从 worktree 读取真实文件 |

**E2E 验证** (task: Step2测试：Python计算器CLI):

```
Worktree API 返回:
  total_files: 21
  total_src_files: 12 (含 calculator_engine.py, parser.py, app.py, terminal.py 等)
  docs: 7/8 有内容 (PRD 5.7KB, UI 7KB, Arch 17.6KB, Impl 17KB, Test 10.5KB, Accept 6KB, Ops 7.8KB)
  文件内容 API: ✅ 返回完整代码 (hash 验证通过)
```

### Step ④ Agent 角色卡 + Skill 升级（2-3天）

> 从"能做"到"做得好"。

**任务清单**:
1. 14 个 Agent 加完整角色卡（人格/使命/规则/工作流/交付物模板/成功指标）
2. 45 个 Skill 加 YAML frontmatter（version/trigger_stages/completion_criteria/allowed_tools）
3. skill_marketplace 改用 trigger_stages 精确匹配
4. 学习循环：reject pattern 累积 → 自动创建/改进 skill

**完成标志**: Agent 产出符合交付物模板格式，质量可量化评估

### Step ⑤ 渠道验证 + 评审闭环（2-3天）

> 打通入口和反馈环。

**任务清单**:
1. 飞书 ngrok 隧道 + 真实 bot 跑 "消息→任务→全流程→回复" 完整链路
2. 评审闭环：Reviewer reject → 自动重做 + rejection feedback 注入 prompt
3. 跨渠道通知：任务状态变更广播到所有已配置渠道
4. 移除 Hermes-Agent 幽灵集成

**完成标志**: 飞书发消息 → 看到 8-Tab 全部真实产出 → 可评审打回重做
