# Phase 6：真实测试与浏览器验证

## 目标

测试报告必须来自真实命令和浏览器证据。

QA Agent 不能只写测试计划或测试总结，它必须运行构建、运行测试、打开页面、截图、记录 console error。

## 输入

- Phase 4 的黄金代码模板。
- Phase 3 的 Artifact Contract。
- 当前 QA Agent / Playwright / browser MCP 能力。
- 当前 task workspace。

## QA 执行流程

```text
/qa
  -> 确认 source_manifest.json 存在
  -> npm install / pnpm install
  -> npm run build
  -> npm test 或模板定义命令
  -> 启动 preview server
  -> Playwright 打开页面
  -> 截图
  -> 收集页面文本
  -> 收集 console error
  -> 生成 qa_result.json 和 test_report.md
```

## 任务拆分

### 1. 定义模板命令

每个黄金模板必须定义：

- install command
- build command
- test command
- preview command

### 2. 运行真实命令

QA 阶段必须记录：

- command
- exit code
- stdout 摘要
- stderr 摘要
- duration

### 3. 浏览器 smoke

使用 Playwright 或 browser MCP：

- 打开 preview URL。
- 等待页面稳定。
- 截图。
- 抽取页面文本。
- 收集 console errors。

### 4. 失败路由

如果失败：

- build 失败：退回 Developer。
- test 失败：退回 Developer。
- 页面打不开：退回 Developer 或 DevOps，按失败原因区分。
- console error：标记风险，严重时退回 Developer。

## 可能涉及文件

- `backend/app/services/pipeline_engine.py`
- `backend/app/services/executor_bridge.py`
- `backend/app/services/task_workspace.py`
- `backend/app/services/artifact_writer.py`
- `backend/app/services/tools/browser.py`
- `backend/tests/test_hero_delivery_path.py`
- `src/components/task/FailureCard.vue`

## 强制产物

- `build.log`
- `test.log`
- `browser_screenshot.png`
- `console_errors.json`
- `qa_result.json`
- `test_report.md`

## 验收标准

- 测试报告包含命令、退出码、日志摘要。
- 截图 artifact 存在。
- 页面打不开时明确退回开发阶段。
- console error 不为 0 时标记风险。
- 没跑命令不能标记 QA 通过。

## 风险

- 本地依赖安装耗时可能拉长任务时间。
- 浏览器环境缺失会导致 QA 阻断，需要资源体检。
- 若继续允许 mock 测试报告，会削弱本阶段价值。

## 执行完成标志

当 QA Agent 的测试报告能追溯到真实命令和真实截图，本阶段完成。
