已有项目接入功能 — 改动汇总
1. 数据层 (Model + Migration)
backend/app/models/pipeline.py — PipelineTask 新增 repo_url（Git 仓库地址）和 project_path（本地/克隆后的路径）两个字段
backend/alembic/versions/e5f6a7b8c9d0_add_project_binding_fields.py — 对应数据库 migration（已执行）
2. 项目绑定服务 (全新)
backend/app/services/project_binding.py — 核心逻辑：
clone_and_bind(repo_url) — git clone 到 sandbox/projects/ 目录，自动注册到白名单
validate_and_bind(project_path) — 校验本地路径安全性并注册
get_project_context(project_path) — 扫描项目结构、关键文件、检测技术栈，生成 Markdown 摘要供 LLM 使用
3. API 层
backend/app/api/pipeline.py — 6 处更新：
CreateTaskRequest 增加 repo_url / project_path 可选字段
任务创建逻辑自动 clone 或 validate
auto-run、run-stage、dag-run、resume、e2e 端点全部传递 project_path
E2ERequest 增加项目绑定字段
4. Pipeline 引擎
backend/app/services/pipeline_engine.py — execute_stage 和 execute_full_pipeline 接收 project_path，将项目上下文注入 LLM prompt
backend/app/services/dag_orchestrator.py — execute_dag_pipeline 透传 project_path
5. E2E Orchestrator
backend/app/services/e2e_orchestrator.py — 识别已有项目：
Phase 1（设计）时将项目上下文拼入 description
Phase 2（代码生成）跳过 scaffold，直接在已有目录操作
6. CodeGen Agent
backend/app/services/codegen/codegen_agent.py — generate_from_pipeline 新增 existing_project_dir 参数，有值时跳过脚手架
7. Sandbox
backend/app/services/tools/sandbox.py — resolve_safe_path 扩展为支持多个白名单目录，add_allowed_dir() 注册外部项目路径
8. 前端
src/agents/types.ts — PipelineTask 增加 repoUrl / projectPath
src/services/pipelineApi.ts — createTask 和 mapTask 支持新字段
src/stores/pipeline.ts — store 透传
src/views/PipelineDashboard.vue — 创建任务对话框新增「关联已有项目」区域（新建 / Git 仓库 / 本地目录三选一）
src/views/PipelineTaskDetail.vue — 任务详情显示 Git URL / 本地路径标签
使用方式
前端：创建任务时选择「Git 仓库」或「本地目录」，填入地址即可。

API：

# Git 仓库
curl -X POST /api/pipeline/tasks \
  -d '{"title":"添加暗色模式","repo_url":"https://github.com/user/repo.git"}'
# 本地项目
curl -X POST /api/pipeline/tasks \
  -d '{"title":"重构数据库层","project_path":"/home/Agent/my-project"}'
# E2E 一键执行
curl -X POST /api/pipeline/e2e \
  -d '{"title":"加缓存","repo_url":"https://github.com/user/repo.git"}'
