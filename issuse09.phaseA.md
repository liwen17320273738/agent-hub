Day 1-2 完成 ✅
交付物（4 个新文件 + 3 个改动）
文件	行数	用途
src/services/workflowBuilder.ts
304
序列化 + 拓扑校验 + 模板转换（纯函数，零 Vue 依赖，方便后续单测）
src/components/builder/AgentStageNode.vue
156
Vue Flow 自定义节点（emoji + role pill + model pill + badges）
src/components/builder/StageConfigDrawer.vue
220
右侧抽屉配置面板（含 stage_id 校验）
src/views/WorkflowBuilder.vue
422
主视图（画布 + 工具栏 + JSON 预览）
src/router/index.ts
+5
加 /workflow-builder 路由
src/App.vue
+5
sidebar 入口（"AI 军团流水线" 下面）
package.json
+4
Vue Flow 全家桶
已实现能力（超出 Day 1-2 计划，提前覆盖了 Day 3-5）
✅ Day 1 全套

Vue Flow + Background + MiniMap + Controls 都已挂上
/workflow-builder 路由可达
加载 sidebar 看到 "Workflow Builder" 入口
自动从 /api/pipeline/templates 拉真实模板，下拉切换即可加载
✅ Day 2 全套

自定义节点（depth 自动布局 + role emoji + 高亮选中 + 红框警告）
连线 = depends_on，实时拓扑检环（红 banner + 红边框）
重复 stage_id 也实时检测（DAG orchestrator 这种会静默吞掉，必须防）
右侧抽屉编辑：stage_id / label / role 下拉 / 模型覆盖 / 质量阈值 slider / reject 策略 / 失败策略 / 人工审批
localStorage 自动持久化（250ms 防抖，拖节点不会一秒写 60 次）
JSON 导入/导出 / 后端 DAG JSON 实时预览 + 复制（可直接 POST 到 /pipeline/tasks）
✅ Day 3-5 已蹭到的

自动布局按钮（按拓扑深度重排）
删除阶段（抽屉里有 danger 按钮）
清空画布
一键加载 11 个内置模板（full / web_app / api_service / fullstack_saas / mobile_app / enterprise / fintech…）
工程质量
Lint: 0 错误（6 个新/改动文件全过）
Build: pnpm build 成功，WorkflowBuilder 单独 chunk 237 KB / gzip 78 KB（懒加载，不影响首屏）
TypeScript: 全文件严格类型，BuilderNode / BuilderEdge / WorkflowDoc 三个核心类型驱动整套数据流
关键设计决策（值得记一下）
Vue Flow 节点 ≠ 后端 stage — 故意用两套 ID（Vue Flow 的 id 是随机字符串，data.stageId 才是后端用的稳定 ID）。原因：用户重命名 stage_id 时不需要重画整张图。

builderToStages() 是纯函数 — 不依赖 Vue / Pinia / 任何全局状态，可以在 D11 写一个 tests/unit/test_workflow_builder.test.ts 把"环检测 / 重复 ID / 模板还原"全单测掉。

templateToBuilder() 自动按拓扑深度排版 — 第一次打开 builder 不会看到一坨重叠的节点，直接是 planning → design → development → ... 的左到右流。

data.warning 由父级注入 — 节点组件不知道全图，但能根据父级算出的"是否在环里"自动改色。这是 React Flow 推荐的 pattern，Vue Flow 一样。

没有写"Run"按钮 — 故意把 Day 6（"运行" → POST /pipeline/tasks + SSE 订阅）单独拉出来。先把 builder UX 调到能录 demo，再接执行——避免一次改太多东西不好排查。

接下来你可以怎么验
make dev   # 或者 pnpm dev:full
打开 http://localhost:5200/#/workflow-builder —

默认应该看到 "完整 SDLC" 模板的 7 个节点排成左到右
拖一个节点的右把手到另一个节点的左把手 → 多一条 dep
拖出环 → 顶部红 banner，相关节点红框
点节点 → 右侧抽屉
点 "查看 JSON" → 预览能直接喂后端的 {template: "custom", stages: [...]}
我建议的下一步（Day 3-5 升级路径）
按价值/工作量排：

任务	约耗时	收益
A 加 "Run" 按钮 → 真实 POST /pipeline/tasks 跑起来
半天
demo 视频核心镜头
B SSE 订阅 → 节点状态实时高亮（running/done/failed 三态）
1 天
demo 视频杀手镜头
C 加 6 个 unit test（environment/cycle/dup/import/export/template）
半天
测试覆盖 + 帮 launch 文背书
D 加左侧 stage palette（拖拽到画布就能新建）
半天
比 "新增阶段按钮" 显著更"workflow builder"感
E 后端 /api/workflows CRUD（保存到数据库，不止 localStorage）
1.5 天
Day 5 计划项
我的建议执行顺序：A → B → D → C → E。A+B 加起来 1.5 天，能直接录 demo GIF（"我画 workflow → 点 Run → 节点逐个变绿 → 输出展开"），这是 launch post 第一张图。

要继续吗？告诉我跑哪条（A / B / D / C / E）或者按 A→B 的组合一起做。

A → B → D → C → E 全链路完成，验证通过。

最终验证结果
检查项	结果
pnpm build
✅ 通过（含 TS 类型检查），WorkflowBuilder chunk 250KB / gzip 83KB
pnpm vitest run
✅ 7/7 通过（workflowBuilder.spec.ts）
backend/tests/unit (pytest)
✅ 160/160 通过（含新增 webhook dedup / escalation cross-worker / dedup primitives）
本轮交付清单（A→B→D→C→E）
A — Run 按钮闭环
后端 PipelineTask 新增 custom_stages JSONB 列（迁移 a0b1c2d3e4f5）
dag_orchestrator.execute_dag_pipeline 接受 custom_stages override
pipeline.create_task / dag_run / resume_task_dag 透传 custom DAG
前端 WorkflowBuilder.vue 加「运行」按钮 + 任务创建对话框
B — SSE 实时染色
复用现有 /api/pipeline/tasks/{id}/events SSE
AgentStageNode 按 run-{status} 上色（running/done/failed/rejected/awaiting/skipped）+ 状态 pill + 错误 tooltip
D — 左侧 Stage Palette
新 StagePalette.vue：8 个角色预设可拖入画布
自定义 MIME application/x-agenthub-stage，落点用 vueFlow.project() 校正坐标
C — 单元测试
新 vitest.config.ts + services/__tests__/workflowBuilder.spec.ts，7 个用例覆盖空图/重复 ID/环检测/round-trip/JSON 导入导出/snake_case 转换
E — 服务端 Workflow CRUD
新 Workflow 模型 + 迁移 b1c2d3e4f5a6_add_workflows_table
新 app/api/workflows.py（GET/POST/GET-by-id/PATCH/DELETE，按 org_id 多租户隔离，复用 get_pipeline_auth）
新前端 services/workflowsApi.ts + Builder 内「保存 / 打开 / 删除」对话框
现状
Workflow Builder 现已具备 可拖拽 → 可保存 → 可运行 → 可实时观测 的最小闭环，加上后端 custom DAG 执行 + 多租户持久化。完全可对外作为 GA 候选演示。

下一步建议（按之前 issuse08.md 路线）：

写英文 launch post + 录 60s demo GIF
跑 SWE-Bench Lite baseline（后端约 1 周）
再决定是否拆出 "AI Issue Resolver" 垂直产品
需要我接着任何一项就告诉我。