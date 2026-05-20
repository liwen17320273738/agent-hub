-- Agent Hub 测试数据清理脚本
-- 使用方式（在服务器上执行）：
--   sudo -u postgres psql -d agenthub -f /opt/agent-hub/scripts/cleanup-test-data.sql
--
-- 注意：保留系统数据（users、orgs、workspaces、agents、skills、artifact_type_registry）

BEGIN;

-- 1. 工件（v2）
DELETE FROM task_artifacts;

-- 2. 遗留工件（v1）和阶段
DELETE FROM pipeline_artifacts;
DELETE FROM pipeline_stages;
DELETE FROM stage_run_logs;

-- 3. 核心任务
DELETE FROM pipeline_tasks;

-- 4. 记忆和知识
DELETE FROM task_memories;
DELETE FROM learned_patterns;
DELETE FROM learning_signals;
DELETE FROM prompt_overrides;
DELETE FROM knowledge_collections;

-- 5. 对话
DELETE FROM agent_messages;
DELETE FROM conversations;

-- 6. 代码索引
DELETE FROM code_chunks;

-- 7. Token 用量
DELETE FROM token_usage;

-- 8. 可观测性
DELETE FROM span_records;
DELETE FROM trace_records;
DELETE FROM audit_logs;
DELETE FROM approval_records;
DELETE FROM feedback_records;

-- 9. Eval 数据
DELETE FROM eval_results;
DELETE FROM eval_runs;
DELETE FROM eval_cases;
DELETE FROM eval_datasets;

-- 10. 工作流
DELETE FROM workflows;

-- 11. 积分（relay）
DELETE FROM relay_api_keys;

-- 12. 沙箱规则
DELETE FROM sandbox_rules;

-- ⚠️ 以下系统数据会保留，不需要删除：
--   - orgs            （默认组织）
--   - users           （admin 用户）
--   - workspaces      （默认工作区）
--   - workspace_members
--   - agents          （系统 Agent 定义）
--   - agent_skills    （Agent 技能绑定）
--   - agent_rules
--   - agent_hooks
--   - agent_plugins
--   - agent_mcps
--   - skills          （内置技能）
--   - artifact_type_registry（工件类型注册）
--   - model_providers
--   - credentials

COMMIT;

-- 清理后检查
SELECT '清理完成！以下为剩余数据概览：' AS "";
SELECT table_name, (xpath('/row/c/text()', query_to_xml('SELECT count(*) FROM ' || table_name, TRUE, FALSE, '')))[1]::text AS row_count
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
ORDER BY table_name;
