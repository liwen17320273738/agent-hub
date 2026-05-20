# Phase 4：固定代码生成黄金模板

## 目标

先让一种项目稳定成功。

开发阶段不能继续追求任意技术栈、任意结构、任意部署方式。商业级 MVP 要先让 Vue/Vite 小应用稳定生成、构建、测试、预览。

## 输入

- Phase 3 的 Artifact Contract。
- Developer Agent 能力栈。
- 当前 CodeGenAgent / Claude Code 执行链路。
- 当前任务 workspace / artifact writer。

## 黄金模板

第一版建议只支持：

- Vue 3
- Vite
- TypeScript
- Element Plus 或轻量自研组件
- 静态单页应用
- 本地 preview server
- 后端默认不做，除非任务明确需要 API

## Developer Agent 执行模式

Developer Agent 应使用：

- Claude Code / Cursor Agent / Codex 类执行器写真实文件。
- DeepSeek V4 / Claude Sonnet 做错误诊断和规划。
- ECC / Superpowers / gstack 作为 Claude Code 增强 Profile。
- GitHub、filesystem、commands、browser、context7 MCP。

执行顺序：

```text
/code
  -> 读取 spec.md、file_plan.json、acceptance_criteria.json
  -> 挂载 claude-code-enhanced profile
  -> OpenSpec 检查需求是否冻结
  -> Superpowers 匹配技能和规则
  -> Claude Code 写真实文件
  -> after_write hook 执行 format / lint / typecheck
  -> build-error-resolver 修复构建错误
  -> 生成 source_manifest.json、implementation.md、build.log
  -> 进入 /qa
```

## 任务拆分

### 1. 准备干净模板

模板必须可独立运行：

- install
- build
- test
- preview

### 2. 限制写入范围

开发阶段只允许修改：

- `src/`
- `public/`
- `package.json`
- `vite.config.ts`
- 测试文件

需要修改其他文件必须由 Architect 或 Orchestrator 批准。

### 3. 强制执行命令

生成后必须运行：

- install
- build
- test

### 4. 自动修复

失败后：

- 把错误日志交给 Developer Agent。
- 最多自动修复 2 次。
- 仍失败则阻断，并展示真实日志。

### 5. 生成 source manifest

必须记录：

- 新增文件。
- 修改文件。
- build command。
- run command。
- test command。

## 可能涉及文件

- `backend/app/services/pipeline_engine.py`
- `backend/app/services/executor_bridge.py`
- `backend/app/services/codegen_agent.py`
- `backend/app/services/task_workspace.py`
- `backend/app/services/artifact_writer.py`
- `backend/app/agents/seed.py`
- `backend/tests/test_hero_delivery_path.py`
- `src/` 黄金模板相关目录

## 强制产物

- 黄金模板目录或模板生成器。
- Developer Agent Claude Code 增强 Profile。
- `source_manifest.json`
- `build.log`
- `implementation.md`

## 验收标准

- 10 个固定简单应用需求，至少 8 个能完整构建成功。
- 每个交付都有源码 manifest。
- 每个交付都有 build log。
- 没有构建通过就不能进入部署阶段。

## 风险

- Claude Code 执行环境不稳定会影响成功率。
- 模板过于自由会导致构建失败率上升。
- 模板过于死板会限制产品体验，但 MVP 阶段应优先稳定。

## 执行完成标志

当 Developer Agent 能连续生成并构建多个 Vue/Vite 小应用，本阶段完成。
