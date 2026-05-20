# Phase 1：建立 Hero Path E2E 测试

## 目标

先让失败可见，而不是先修所有问题。

本阶段要建立一条能够证明“一句话到交付包”的端到端测试。测试失败时必须指出断在哪个阶段、缺哪个 artifact、哪个证据不存在。

## 输入

- Phase 0 的 Hero Path 定义。
- 当前测试体系：`backend/tests/`
- 当前 Pipeline API 和任务执行入口。
- 当前 artifact / share / deliverables 能力。

## 测试用例

固定一句话：

```text
做一个待办事项看板，支持新增、完成、删除任务。
```

测试应该验证：

- 任务创建成功。
- 每个阶段进入过运行状态。
- 每个关键 artifact 存在。
- 代码目录存在。
- 构建命令被执行过。
- 测试报告包含真实命令输出或明确 mock 标识。
- 分享页或交付包可访问。

## 任务拆分

### 1. 新增 Hero Path E2E 测试文件

已实现：

- `backend/tests/test_hero_delivery_path.py`（无 LLM：`advance` 全阶段 + v2 artifact + share + ZIP）

后续可增强（仍为 Phase 1 范围）：

- 对单个 `advance` 失败输出更细的阶段 id + response body。
- 在 durable state 落地后断言 `input_snapshot` / `failure_reason`。
- 增加「仅跑前 N 个阶段故意失败」的负例用例。

测试可以使用可控模型 fixture 或 mock LLM，但不能绕过真实 pipeline 状态流转。

### 2. 定义阶段断点断言

每个阶段至少断言：

- stage id
- stage status
- input snapshot
- output artifact
- failure reason

### 3. 定义交付包完整度断言

交付包至少包含：

- PRD
- UI spec 或 UI mockup 占位证据
- architecture
- source manifest
- build log
- test report
- preview/deploy artifact
- acceptance result

### 4. 生成自测报告

更新：

- `docs/selftest-report.md`

报告必须说明：

- 运行命令。
- 成功/失败状态。
- 断点阶段。
- 缺失 artifact。
- 下一阶段修复建议。

## 可能涉及文件

- `backend/tests/test_hero_delivery_path.py`
- `backend/tests/conftest.py`
- `backend/app/services/pipeline_engine.py`
- `backend/app/services/dag_orchestrator.py`
- `backend/app/services/task_lifecycle.py`
- `backend/app/api/pipeline.py`
- `docs/selftest-report.md`

## 强制产物

- `backend/tests/test_hero_delivery_path.py`
- Hero Path 自测报告。
- 阶段失败输出样例。

## 验收标准

- 测试不能只检查接口 200。
- 测试失败时能明确指出断在哪个阶段。
- 测试必须验证最终交付包完整度。
- CI 或本地命令能单独运行该测试。

## 风险

- 当前系统可能大量依赖 monkeypatch，真实状态断言会暴露很多失败。
- 初版测试可以允许 mock LLM，但必须保留真实状态流转和 artifact 校验。
- 如果测试过于宽松，会继续制造“看起来通过”的假信号。

## 执行完成标志

当下面命令能稳定给出可解释结果，本阶段完成：

```bash
cd backend && python3 -m pytest tests/test_hero_delivery_path.py -v
```
