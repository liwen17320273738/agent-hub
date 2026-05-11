# CLI 命令工具链架构设计

## 1. 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Agent Hub CLI                                │
│  /autoplan  /review  /qa  /ship  /retro  /careful  /freeze  /guard  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │    Command Router      │
                    │  (slash_command_router) │
                    └───────────┬───────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐     ┌───────────────┐      ┌───────────────┐
│  Command      │     │  Pipeline     │      │  Skill       │
│  Services     │     │  Engine       │      │  Loader      │
│  (per command)│     │               │      │              │
└───────┬───────┘     └───────┬───────┘      └───────┬───────┘
        │                     │                      │
        └─────────────────────┼──────────────────────┘
                              ▼
                    ┌─────────────────┐
                    │  Memory Layer   │
                    │  (向量检索+历史) │
                    └─────────────────┘
```

## 2. 模块划分

### 2.1 命令服务层 (`backend/app/services/commands/`)

```
commands/
├── __init__.py
├── base.py              # BaseCommand抽象基类
├── autoplan.py          # /autoplan 自动编排
├── review.py            # /review 代码审查
├── qa.py                # /qa 端到端测试
├── ship.py              # /ship 发布管理
├── retro.py             # /retro 回顾分析
├── router.py            # 命令路由调度
└── schemas.py           # Pydantic请求/响应模型
```

### 2.2 命令基类设计

```python
# base.py
class BaseCommand(ABC):
    name: str                           # 命令名称 /autoplan
    description: str                    # 命令描述
    arguments: List[CommandArgument]     # 参数定义
    required_roles: List[str]           # 权限角色

    async def execute(self, ctx: CommandContext) -> CommandResult:
        """执行命令，返回结构化结果"""
        pass

    async def validate(self, args: Dict) -> ValidationResult:
        """验证参数合法性"""
        pass

    async def get_help(self) -> str:
        """返回命令帮助文本"""
        pass
```

## 3. API 设计

### 3.1 命令执行API

```
POST /api/commands/execute
Content-Type: application/json

Request:
{
  "command": "/autoplan",
  "args": {
    "task": "实现用户登录功能",
    "context": {"project_id": "proj-123"}
  },
  "session_id": "sess-xxx"
}

Response (SSE stream):
event: command.started
data: {"command": "/autoplan", "status": "started"}

event: command.progress
data: {"stage": "分解任务", "progress": 30}

event: command.progress
data: {"stage": "依赖分析", "progress": 60}

event: command.completed
data: {"command": "/autoplan", "result": {...}}
```

### 3.2 命令列表API

```
GET /api/commands

Response:
{
  "commands": [
    {
      "name": "/autoplan",
      "description": "自动编排任务",
      "arguments": [...],
      "required_roles": ["developer", "architect"]
    },
    ...
  ]
}
```

## 4. 数据结构

### 4.1 CommandContext

```python
class CommandContext(BaseModel):
    session_id: str
    user_id: str
    workspace_id: str
    arguments: Dict[str, Any]
    metadata: Dict[str, Any]  # 包含项目、仓库等信息
```

### 4.2 CommandResult

```python
class CommandResult(BaseModel):
    command: str
    status: Literal["success", "failed", "partial"]
    output: Any                    # 结构化输出
    artifacts: List[Artifact]      # 产出物
    metrics: ExecutionMetrics      # 执行指标
    errors: List[str]               # 错误列表
```

### 4.3 各命令输出结构

| 命令 | output 结构 |
|-----|-------------|
| /autoplan | `{tasks: List[Task], dag: Dict, estimated_hours: float}` |
| /review | `{findings: List[Finding], score: float, approved: bool}` |
| /qa | `{tests: List[TestResult], coverage: float, passed: bool}` |
| /ship | `{release_notes: str, artifacts: List[str], version: str}` |
| /retro | `{summary: str, metrics: Dict, action_items: List[ActionItem]}` |

## 5. 调用流程

### 5.1 /autoplan 流程

```
用户输入 /autoplan 实现登录功能
         │
         ▼
   CommandRouter.parse("/autoplan", args)
         │
         ▼
   AutoplanCommand.validate(args)
         │
         ▼
   PipelineEngine.create_tasks(task_description)
         │
         ├──► LeadAgent.decompose()     # 任务分解
         │
         ├──► DependencyAnalyzer.analyze()  # 依赖分析
         │
         └──► Estimator.estimate()      # 工时估算
         │
         ▼
   Memory.store_plan()              # 存储计划
         │
         ▼
   返回 TaskDAG + 执行建议
```

### 5.2 /review 流程

```
用户输入 /review --pr=123
         │
         ▼
   CommandRouter.route("/review", args)
         │
         ▼
   ReviewCommand.execute(ctx)
         │
         ├──► GitTool.fetch_pr()       # 获取PR代码
         │
         ├──► CodeAnalyzer.analyze()  # 代码分析
         │
         ├──► LLM.judge()             # AI评审
         │
         └──► SecurityScanner.scan()  # 安全扫描
         │
         ▼
   返回 Findings + 建议
```

## 6. 命令详细设计

### 6.1 /autoplan — 自动编排任务

**参数:**
- `task`: string (必填) - 任务描述
- `constraints`: object (可选) - 约束条件 {deadline, budget, team_size}

**触发流程:**
1. LeadAgent 分解任务为子任务
2. DAG Orchestrator 构建依赖图
3. Estimator 计算工时
4. 返回可执行的任务计划

### 6.2 /review — 代码审查

**参数:**
- `--pr`: number (必填) - PR编号
- `--files`: string[] (可选) - 指定文件
- `-- severity`: low|medium|high (可选) - 过滤严重级别

**触发流程:**
1. GitTool 获取 PR 差异
2. CodeAnalyzer 多维度分析
3. LLM 生成评审意见
4. SecurityScanner 安全检查
5. 汇总评分和结论

### 6.3 /qa — 端到端测试

**参数:**
- `--scope`: full|incremental (可选) - 测试范围
- `--browser`: chromium|firefox (可选) - 浏览器
- `--headless`: boolean (可选) - 无头模式

**触发流程:**
1. TestRunner 发现测试用例
2. BrowserTool 执行 E2E 测试
3. CoverageAnalyzer 计算覆盖率
4. ReportGenerator 生成测试报告

### 6.4 /ship — 发布管理

**参数:**
- `--version`: semver (必填) - 目标版本
- `--artifacts`: string[] (可选) - 产物列表
- `--channel`: stable|beta (可选) - 发布通道

**触发流程:**
1. VersionChecker 验证版本号
2. ArtifactCollector 收集产物
3. ReleaseNotesGenerator 生成更新日志
4. DeployConnector 执行部署
5. NotificationSender 通知相关方

### 6.5 /retro — 回顾分析

**参数:**
- `--sprint`: string (必填) - Sprint ID
- `--metrics`: string[] (可选) - 指标列表

**触发流程:**
1. DataCollector 收集 Sprint 数据
2. MetricsCalculator 计算指标
3. AIAnalyzer 生成分析报告
4. ActionItemExtractor 提取改进项

## 7. 依赖关系

```
CLI Commands
    │
    ├──► Pipeline Engine (dag_orchestrator.py)
    │         │
    │         ├──► Lead Agent (lead_agent.py)
    │         ├──► Memory (memory.py)
    │         └──► Tools (tools/registry.py)
    │
    ├──► Skill Loader (skill_loader.py)
    │         │
    │         └──► Skill Registry (skill_registry.py)
    │
    └──► Observability (observability.py)
              │
              ├──► SSE Emitter
              └──► Trace Recorder
```

## 8. Power Tools (辅助命令)

| 命令 | 用途 | 核心逻辑 |
|-----|------|---------|
| `/careful` | 谨慎模式 | 降低并发，增加验证步骤 |
| `/freeze` | 冻结状态 | 暂停任务，保持上下文 |
| `/guard` | 安全护栏 | 增强权限检查和审批流 |

## 9. 参考实现

- 命令基类参考: `backend/app/services/tools/registry.py` 的 ToolFunc 模式
- Pipeline 集成参考: `backend/app/services/pipeline_engine.py` 的成熟化层
- Skill 机制参考: `backend/app/services/skill_loader.py` 的发现+执行模型
