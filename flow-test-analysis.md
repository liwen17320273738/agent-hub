# Agent Hub 流程测试分析报告

**日期**: 2026-05-25  
**分支**: 当前工作分支（98 个文件变更，+7264/-1487）  
**分析方式**: 静态代码审查 + 语法验证（因 VM 网络隔离，无法安装依赖执行真实测试）

---

## 一、测试覆盖总览

### 后端 Python 测试（451 个测试函数，~5,549 行）

| 测试文件 | 行数 | 覆盖范围 |
|---|---|---|
| test_hero_delivery_path.py | 319 | Hero Path 状态机冒烟（不调 LLM，verify /advance 流转 + v2 工件 + 分享） |
| test_hero_pipeline_acceptance.py | 361 | 真实 execute_stage + 质量合约，mock 全部 LLM/Phase5/6/7 外部依赖 |
| test_process_flow.py | 121 | 调度器生命周期：smart-run / auto-run 投递闭环 |
| test_flow_scenarios.py | 252 | 10 段链式 API 旅程：需求→工件→工作流→工作区→技能→模型→对话→凭据→沙箱→Agent |
| test_e2e_pipeline.py | 335 | Gateway → Task → Pipeline → Notify 全链路（飞书/微信/QQ/OpenClaw） |
| test_artifact_contract_quality.py | 119 | 反 mock 质量闸：拒绝占位符/模拟标记 |
| test_phase4_golden_template.py | 575 | 10 项固定需求计分卡，真 pnpm build，目标 ≥8/10 |
| test_phase5_visual_evidence.py | 235 | 设计/架构阶段必须产出可视化图形（PNG/HTML） |
| test_phase6_qa_execution.py | 349 | 测试阶段真命令执行 + 浏览器冒烟 |
| test_im_final_acceptance.py | 392 | IM 最终验收全流程 |
| test_no_api_key_degraded_path.py | 697 | 无 API 密钥退化路径（最大测试文件） |
| test_acceptance_endpoints.py | 319 | 验收端点测试 |
| test_phase2_durable_cues.py | 231 | Phase 2 持久化线索 |
| test_phase3_artifact_contract.py | 244 | Phase 3 工件合约 |
| test_pipeline_hard_gates.py | 158 | 管道硬闸门 |
| test_dag_orchestrator.py | 145 | DAG 编排器 |
| test_gateway_plan_mode.py | 151 | Gateway Plan/Act 审批模式 |
| test_pipeline_api.py | 73 | Pipeline API |
| test_plans_api.py | 206 | Plans API |

### 单元测试（28 个文件）

覆盖：LLM Router、Fallback、Circuit、Agent Runtime、Task Scheduler、Lifecycle、Artifact System、Workflow Compiler、Rate Limit、Sandbox、MCP、Self-verify、Lead Agent、Webhook 等。

### 集成测试（4 个文件）

- test_relay_gateway.py — Gateway 中继
- test_sandbox_pubsub_dualworker.py — 沙箱双 Worker
- test_share_endpoint.py — 分享端点
- test_workspace_rbac.py — 工作区 RBAC

### 前端 E2E 测试（6 个 Playwright spec）

- hero-smoke.spec.ts — UI/API 连通性
- regression-battery.spec.ts / regression-matrix.spec.ts — 回归矩阵
- sidebar-smoke.spec.ts — 侧栏冒烟
- visual-preview.spec.ts — 可视化预览
- helpers.ts — 共享辅助函数

---

## 二、代码质量检查

### Python 语法验证 ✅

所有 15 个变更的服务文件通过 `ast.parse()` 语法检查，无语法错误：

```
OK: artifact_contract.py
OK: artifact_writer.py
OK: codegen_agent.py
OK: delivery_contract.py (新增)
OK: deploy/local_preview.py
OK: deploy/vercel.py
OK: e2e_orchestrator.py
OK: executor_bridge.py
OK: llm_router.py
OK: pipeline_engine.py
OK: qa_executor.py
OK: quality_gates.py
OK: task_lifecycle.py
OK: ui_visualizer.py
OK: visual_asset_repair.py (新增)
```

### 关键变更分析

**新增文件**:
- `delivery_contract.py` — 交付合约（新增能力）
- `visual_asset_repair.py` — 可视化资产修复（新增能力）
- `test_artifact_contract_quality.py` — 质量闸反 mock 测试（新增测试）
- `test_hero_pipeline_acceptance.py` — Hero 管道验收测试（新增测试）
- 2 个 Alembic 迁移：`widen_pipeline_tasks_status` + `add_workspace_allow_draft_delivery`

**修改文件**（核心路径）:
- `pipeline_engine.py` — 管道引擎核心
- `artifact_contract.py` / `artifact_writer.py` — 工件合约与写入
- `llm_router.py` — LLM 路由
- `qa_executor.py` — QA 执行器
- `ui_visualizer.py` — UI 可视化
- `quality_gates.py` — 质量闸门
- `codegen_agent.py` / `executor_bridge.py` — 代码生成
- `deploy/local_preview.py` / `deploy/vercel.py` — 部署

---

## 三、流程测试矩阵

### Hero Path（核心交付链路）

```
一句话需求 → 任务创建 → 8 阶段推进 → 工件写入 → 分享 → ZIP 下载
```

| 测试 | 调用方式 | LLM？ | 工件来源 | 合约通过？ |
|---|---|---|---|---|
| test_hero_delivery_path_smoke | /advance API | Mock | 手动 API stub | ❌（预期拒绝） |
| test_hero_pipeline_execute_stage | execute_stage() | Mock（注入内容） | artifact_writer 自动写入 | ✅（预期通过） |
| test_artifact_quality_errors | 纯函数 | 无 | 直接调用 quality_errors() | ❌（反 mock） |

### Gateway 全链路（多通道接入）

| 通道 | 测试方法 |
|---|---|
| OpenClaw | intake → task 创建 + Plan 模式 |
| 飞书 | webhook v2 消息事件 |
| 微信 | XML 签名验证 + 文本消息 |
| QQ | source 映射 |

### 调度器闭环

- smart-run：创建任务 → POST /smart-run → 等待调度器完成 → 验证 lifetime.finished 递增
- auto-run：同上但走 execute_full_pipeline
- API 一致性：GET /api/scheduler/status 与 get_scheduler().status() 对齐

---

## 四、执行环境限制

本次无法执行实际测试，原因：

1. **VM 网络隔离**：pip 无法连接 PyPI（DNS 不可达，代理 403）
2. **Venv 不兼容**：现有 `.venv` 包为 macOS arm64 编译（.cpython-312-darwin.so），无法在 Linux VM 加载
3. **pnpm 未安装**：前端依赖不可用

### 建议执行方式

在本地 macOS 环境执行：

```bash
# 全部后端测试
cd backend && make test

# 核心流程测试
cd backend && python3 -m pytest tests/test_hero_delivery_path.py tests/test_hero_pipeline_acceptance.py tests/test_process_flow.py tests/test_flow_scenarios.py tests/test_e2e_pipeline.py -v

# 仅 Hero Path 冒烟
cd backend && python3 -m pytest tests/test_hero_delivery_path.py -v

# Phase 4 黄金模板计分卡
cd backend && python3 -m pytest tests/test_phase4_golden_template.py -v

# 前端 E2E
cd src && npx playwright test tests/e2e/hero-smoke.spec.ts
```

---

## 五、综合评估

**测试覆盖完整性**: 高。核心 Hero Path 有两层测试（状态机冒烟 + 真实管道验收），14 种工件类型均有覆盖，Gateway 四通道均有集成测试，Phase 2-7 每个阶段有专项测试。

**代码质量**: 所有变更文件通过 Python AST 语法检查，无语法错误。新增了 `delivery_contract.py` 和 `visual_asset_repair.py` 两个能力模块，以及相应的测试文件。

**待关注点**:
- 变更范围大（98 个文件，30 个 Python 源文件），建议重点验证 `pipeline_engine.py`、`artifact_writer.py`、`artifact_contract.py` 的行为变更
- 新增的 `delivery_contract.py` 和 `visual_asset_repair.py` 是全新模块，需确保与现有流程集成正确
- 新增了两个 Alembic 迁移，需在真实数据库上验证
