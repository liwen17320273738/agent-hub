两条都落地完，171 passed / 0 lint （上轮 156 → +15：14 个 mirror，1 个真 Redis 双进程）。

✅ #1 真 Redis 双 worker 验证（P0）
backend/tests/integration/test_sandbox_pubsub_dualworker.py

子进程作为 worker B：python -c SCRIPT_BODY，独立解释器、独立 _PROCESS_ID、独立 in-memory 缓存
父进程作为 worker A：往真 Redis（localhost:6379/15）的 sandbox:rule-changed 频道 publish 一条 {"op": "upsert", "role": "ceo", "tool": "bash", "allowed": true}
worker B 的 listener 收到后，本地 cache 立刻可被 override_decision('ceo','bash') 看到
断言：worker B 在 5s deadline 内的 override_decision 必须翻转；publish 返回的订阅者数 ≥ 1（防止"提前 publish 没人订阅"的假阳性）
无 Redis 时自动 pytest.skip()，CI 安全
实测 1.14s 通过 ⇒ pubsub 在生产 gunicorn -w 4 下不会有"worker A 改了规则、worker B 还按旧策略放行 bash"的事故
✅ #2-#5 external_links 全链路 = #4 升「生产级闭环」
2-1 Schema 层

9d0e1f2a3b4c_add_pipeline_task_external_links.py
Lines 47-57
def upgrade() -> None:
    with op.batch_alter_table("pipeline_tasks") as batch:
        batch.add_column(
            sa.Column(
                "external_links",
                JsonDict(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
PipelineTask.external_links: Mapped[list] with default=list，老行 backfill []，没有破坏性。
2-2 CRUD API（/api/integrations）
方法	路径	用途
GET
/tasks/{id}/links
列已绑
POST
/tasks/{id}/links
绑已存在的 issue（(kind,key) 幂等去重，GitHub 自动从 owner/repo#N 拆 project）
DELETE
/tasks/{id}/links/{kind}/{key:path}
解绑（path 参数允许 / #）
POST
/tasks/{id}/links/create-and-bind
一次调用：用 task 的 title/description 在外部建 issue + 立即写回 external_links
2-3 自动回写（DAG REJECT 时）
backend/app/services/connectors/mirror.py + _mirror_reject_to_external_links 接进 dag_orchestrator._run_stage：

reviewer 输出 REJECTED → 走原 _reset_to_stage(feedback=…) 路径
新增：从 DB 重读 task.external_links（防止 admin 中途加链接），拼接驳回正文（含 task title / target stage / 第 N 次返工 / 截断到 1500 字的 reviewer 原话）
asyncio.gather 并发 fan-out 到所有 link，失败/无配置/超时一律软失败，绝不阻塞 DAG
一条 integrations:mirrored SSE 汇总 posted/skipped/failed，前端可直接渲染「已同步到 N 个 tracker」
2-4 测试网（test_external_links_mirror.py，14 cases）
_normalize_links 输入卫生：None / [] / 单 dict legacy / 垃圾条目 / 标量
mirror_comment_to_links：空链接、未配置、并发 fan-out、单连接器抛异常不污染其它、only_kinds 过滤
模型层：插入不带 external_links 字段必须默认 [] 而非 NULL（守 server_default）
DAG helper：无链接静默 / 有链接 fan-out + SSE 事件形态 / 50KB 超长 feedback 截断到 1500 字 + …
现在的状态
维度	之前	现在
多 worker 一致性
单进程 + in-memory mock 验证
✅ 真 Redis 子进程端到端
#4 连接器
能手动 POST 建 issue
✅ task 持久绑定 + REJECT 自动回写
测试
156
171 （+14 mirror，+1 dual-worker）
Lint
0
0
下一轮可推（如需继续）
GitHub/Jira 入站 webhook：链接已存在的反方向——「Jira AI-7 收到评论 → trigger task iterate」，把双向闭环最后半圈补上
create-and-bind 接到 task 创建钩子：POST /pipeline/tasks 时若请求体带 auto_link: "jira"，自动建 issue 并绑，让 PRD-from-AI 直接进对方 backlog
reject_count >= N 自动升级 P1 label / 通知 IM：现在每次 reject 都会刷一条评论；可加节流 + 升级策略，避免 noise
要继续推哪一条？

