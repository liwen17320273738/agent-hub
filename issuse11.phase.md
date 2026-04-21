收尾总结
本次新增（D 任务的最后冲刺 + 测试 / 构建）
后端

backend/app/api/pipeline.py：补 Any 到 typing 导入（修复 Pydantic 解析 Dict[str, Dict[str, Any]] 失败的 class-not-fully-defined 报错）
backend/tests/test_acceptance_endpoints.py（新增 12 个测试）覆盖：
quality-gate-config GET 形状 / PUT 持久化 / 阈值校验 / 鉴权
final-accept 成功路径 / 幂等 / 状态机校验 / 鉴权
final-reject 仅暂停 / 带重启重置下游 / 未知阶段 400 / 必填原因
用 monkeypatch 把 emit_event 桩成 no-op，避免 Redis 单例跨 event-loop 的 "Event loop is closed" 污染
前端

src/services/pipelineApi.ts：补 finalAcceptTask / finalRejectTask 客户端
src/components/pipeline/FinalAcceptanceModal.vue（新建）：双 Tab 终点 modal —— 接受（带备注） / 打回（必填原因 + 可选重启阶段下拉），与 restartableStages 计算属性配合自动剔除哨兵节点
src/views/PipelineTaskDetail.vue：
顶部插入「🏁 交付完成 · 等待最终验收」横幅（带 radial pulse 动效），优先级高于 paused/failed
接入 FinalAcceptanceModal，对外暴露 openFinalAcceptance('accept' | 'reject')
SSE 监听增加 pipeline:awaiting-final-acceptance：自动停 spinner、弹 6 秒 warning toast、刷新质量报告
时间线标签字典补 🏁 等待最终验收
全绿验证
pnpm build ✅ 2.75s，零报错
pnpm test ✅ 7/7
pytest tests/test_acceptance_endpoints.py tests/test_pipeline_api.py tests/test_dag_orchestrator.py tests/test_self_verify.py ✅ 35/35
ReadLints 全部干净
全套交付一览
任务	内容	关键产物
F
质量门禁阈值前端可配
quality_gate_config JSONB 列、get/put quality-gate-config API、QualityGateConfigDrawer.vue
C
门禁详情面板重做
QualityGatePanel.vue（圆环 + 维度色块 + 分组检查 + 建议）
B
self-heal 可视化
DAG 节点 🔁×N 徽章 + before/after diff 抽屉 + stage:rework/pipeline:dag-branch SSE 增强字段
E
审批 SLA 指示
useApprovalSLA.ts composable、SLA 胶囊（已等 X min / ⚠️ 接近超时 / ⏰ 严重超时）+ critical 级别 toast
D
最终验收终点
awaiting_final_acceptance 状态 + 5 列迁移、final-accept/final-reject API（含背景 DAG 重跑）、终点横幅 + 双 Tab modal
迁移已应用，线性引擎和 DAG 编排都已对称地引入新终点状态——线性走 pipeline_engine.py、DAG 走 dag_orchestrator.py，行为完全一致。