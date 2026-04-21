"""Backfill design / acceptance / specialist stages for in-flight tasks.

Revision ID: 5f8a9b0c1d2e
Revises: 4e7f8a9b0c1d
Create Date: 2026-04-21 10:00:00.000000

After PIPELINE_TEMPLATES grew from 6 stages to 12 stages (added design,
security-review, legal-review, data-modeling, marketing-launch, finance-review)
and `reviewing` re-bound from CEO to acceptance-agent, existing tasks created
before this change are missing the new stage rows.

This migration:
1. Snapshots the current 15 templates inline (so the migration is immutable
   even if PIPELINE_TEMPLATES drifts later).
2. For every task whose status is NOT in ('done', 'cancelled') and that has
   a `template` value, syncs `pipeline_stages`:
   - inserts any missing template stage as PENDING
   - re-numbers `sort_order` so the new flow is in the right order
   - upgrades `owner_role='orchestrator'` -> 'acceptance' on the reviewing row
   - never touches done/active rows' status/output/timestamps
3. Idempotent: safe to re-run.

Tasks without a template (legacy custom flows) are left untouched.
"""
from __future__ import annotations

import uuid

from alembic import op
from sqlalchemy import text


revision = "5f8a9b0c1d2e"
down_revision = "4e7f8a9b0c1d"
branch_labels = None
depends_on = None


# Snapshot of PIPELINE_TEMPLATES at the time of this migration. Each entry is
# (stage_id, label, owner_role). Order = canonical sort_order.
TEMPLATE_SNAPSHOT: dict[str, list[tuple[str, str, str]]] = {
    "full": [
        ("planning", "需求规划", "product-manager"),
        ("design", "UI/UX 设计", "designer"),
        ("architecture", "架构设计", "architect"),
        ("development", "开发实现", "developer"),
        ("testing", "测试验证", "qa-lead"),
        ("reviewing", "审查验收", "acceptance"),
        ("deployment", "部署上线", "devops"),
    ],
    "parallel_design": [
        ("planning", "需求规划", "product-manager"),
        ("design", "UI/UX 设计", "designer"),
        ("architecture", "架构设计", "architect"),
        ("development", "开发实现", "developer"),
        ("testing", "测试验证", "qa-lead"),
        ("reviewing", "审查验收", "acceptance"),
    ],
    "simple": [
        ("planning", "需求规划", "product-manager"),
        ("development", "开发实现", "developer"),
        ("testing", "测试验证", "qa-lead"),
    ],
    "review_only": [
        ("testing", "测试验证", "qa-lead"),
        ("reviewing", "审查验收", "acceptance"),
    ],
    "adaptive": [
        ("planning", "需求规划", "product-manager"),
        ("design", "UI/UX 设计", "designer"),
        ("architecture", "架构设计", "architect"),
        ("development", "开发实现", "developer"),
        ("testing", "测试验证", "qa-lead"),
        ("reviewing", "审查验收", "acceptance"),
        ("deployment", "部署上线", "devops"),
    ],
    "web_app": [
        ("planning", "需求规划", "product-manager"),
        ("design", "界面 & 组件设计", "designer"),
        ("architecture", "架构设计", "architect"),
        ("development", "前后端开发", "developer"),
        ("testing", "端到端测试", "qa-lead"),
        ("reviewing", "产品验收", "acceptance"),
        ("deployment", "部署上线", "devops"),
    ],
    "api_service": [
        ("planning", "API 需求设计", "product-manager"),
        ("architecture", "接口 & 数据模型", "architect"),
        ("development", "API 实现", "developer"),
        ("testing", "接口测试 & 安全审查", "qa-lead"),
        ("deployment", "部署 & 文档", "devops"),
    ],
    "data_pipeline": [
        ("planning", "数据需求分析", "product-manager"),
        ("architecture", "数据架构设计", "architect"),
        ("development", "ETL / 管道开发", "developer"),
        ("testing", "数据质量验证", "qa-lead"),
        ("reviewing", "数据治理审查", "acceptance"),
    ],
    "bug_fix": [
        ("planning", "问题分析 & 定位", "product-manager"),
        ("development", "修复实现", "developer"),
        ("testing", "回归测试", "qa-lead"),
    ],
    "microservice": [
        ("planning", "服务需求 & 边界定义", "product-manager"),
        ("architecture", "服务架构 & API 契约", "architect"),
        ("development", "服务实现", "developer"),
        ("testing", "单元 + 集成 + 契约测试", "qa-lead"),
        ("reviewing", "服务验收", "acceptance"),
        ("deployment", "容器化部署", "devops"),
    ],
    "fullstack_saas": [
        ("planning", "产品需求 & 商业模式", "product-manager"),
        ("design", "界面 & 组件设计", "designer"),
        ("architecture", "全栈架构 & 技术选型", "architect"),
        ("development", "前后端实现", "developer"),
        ("testing", "全链路测试", "qa-lead"),
        ("security-review", "安全审计", "security"),
        ("reviewing", "产品验收", "acceptance"),
        ("deployment", "云端部署 & CI/CD", "devops"),
    ],
    "mobile_app": [
        ("planning", "移动端需求分析", "product-manager"),
        ("design", "移动端 UI 设计", "designer"),
        ("architecture", "移动架构 & API", "architect"),
        ("development", "移动端开发", "developer"),
        ("testing", "多设备测试 & 性能", "qa-lead"),
        ("security-review", "安全审计", "security"),
        ("reviewing", "App 验收", "acceptance"),
        ("deployment", "商店发布 & 灰度", "devops"),
    ],
    "enterprise": [
        ("planning", "需求规划", "product-manager"),
        ("design", "UI/UX 设计", "designer"),
        ("architecture", "架构设计", "architect"),
        ("development", "开发实现", "developer"),
        ("testing", "测试验证", "qa-lead"),
        ("security-review", "安全审计", "security"),
        ("legal-review", "合规审查", "legal"),
        ("reviewing", "最终验收", "acceptance"),
        ("deployment", "部署上线", "devops"),
    ],
    "growth_product": [
        ("planning", "需求规划", "product-manager"),
        ("design", "UI/UX 设计", "designer"),
        ("architecture", "架构设计", "architect"),
        ("data-modeling", "指标与埋点设计", "data"),
        ("development", "开发实现", "developer"),
        ("testing", "测试验证", "qa-lead"),
        ("reviewing", "产品验收", "acceptance"),
        ("deployment", "部署上线", "devops"),
        ("marketing-launch", "上线营销包", "marketing"),
    ],
    "fintech": [
        ("planning", "需求规划", "product-manager"),
        ("design", "UI/UX 设计", "designer"),
        ("architecture", "架构设计", "architect"),
        ("finance-review", "商业可持续性评估", "finance"),
        ("development", "开发实现", "developer"),
        ("testing", "测试验证", "qa-lead"),
        ("security-review", "安全审计", "security"),
        ("legal-review", "合规审查", "legal"),
        ("reviewing", "最终验收", "acceptance"),
        ("deployment", "灰度部署", "devops"),
    ],
}


def _backfill_sqlite(bind) -> dict[str, int]:
    """SQLite path: select tasks → upsert stages task-by-task."""
    stats = {"tasks_synced": 0, "stages_inserted": 0, "stages_resorted": 0,
             "reviewer_rebound": 0}

    tasks = bind.execute(text(
        "SELECT id, template FROM pipeline_tasks "
        "WHERE template IS NOT NULL AND template != '' "
        "AND status NOT IN ('done', 'cancelled')"
    )).fetchall()

    for row in tasks:
        task_id = row[0]
        template_id = row[1]
        snapshot = TEMPLATE_SNAPSHOT.get(template_id)
        if not snapshot:
            continue

        existing_rows = bind.execute(text(
            "SELECT stage_id, status, sort_order, owner_role "
            "FROM pipeline_stages WHERE task_id = :tid"
        ), {"tid": task_id}).fetchall()
        existing = {r[0]: {"status": r[1], "sort_order": r[2], "owner_role": r[3]}
                    for r in existing_rows}

        for new_sort, (stage_id, label, owner_role) in enumerate(snapshot):
            if stage_id not in existing:
                bind.execute(text(
                    "INSERT INTO pipeline_stages "
                    "(id, task_id, stage_id, label, owner_role, sort_order, status) "
                    "VALUES (:id, :tid, :sid, :label, :role, :sort, 'pending')"
                ), {
                    "id": str(uuid.uuid4()), "tid": task_id, "sid": stage_id,
                    "label": label, "role": owner_role, "sort": new_sort,
                })
                stats["stages_inserted"] += 1
                continue

            existing_row = existing[stage_id]
            if existing_row["sort_order"] != new_sort:
                bind.execute(text(
                    "UPDATE pipeline_stages SET sort_order = :sort "
                    "WHERE task_id = :tid AND stage_id = :sid"
                ), {"sort": new_sort, "tid": task_id, "sid": stage_id})
                stats["stages_resorted"] += 1

            if (stage_id == "reviewing"
                    and existing_row["owner_role"] in (None, "", "orchestrator")
                    and existing_row["status"] in ("pending", "active")):
                bind.execute(text(
                    "UPDATE pipeline_stages SET owner_role = 'acceptance' "
                    "WHERE task_id = :tid AND stage_id = 'reviewing'"
                ), {"tid": task_id})
                stats["reviewer_rebound"] += 1

        stats["tasks_synced"] += 1

    return stats


def _backfill_postgres(bind) -> dict[str, int]:
    """Postgres path: same as sqlite, gen_random_uuid() for ids."""
    stats = {"tasks_synced": 0, "stages_inserted": 0, "stages_resorted": 0,
             "reviewer_rebound": 0}

    tasks = bind.execute(text(
        "SELECT id::text, template FROM pipeline_tasks "
        "WHERE template IS NOT NULL AND template <> '' "
        "AND status NOT IN ('done', 'cancelled')"
    )).fetchall()

    for row in tasks:
        task_id = row[0]
        template_id = row[1]
        snapshot = TEMPLATE_SNAPSHOT.get(template_id)
        if not snapshot:
            continue

        existing_rows = bind.execute(text(
            "SELECT stage_id, status, sort_order, owner_role "
            "FROM pipeline_stages WHERE task_id = :tid::uuid"
        ), {"tid": task_id}).fetchall()
        existing = {r[0]: {"status": r[1], "sort_order": r[2], "owner_role": r[3]}
                    for r in existing_rows}

        for new_sort, (stage_id, label, owner_role) in enumerate(snapshot):
            if stage_id not in existing:
                bind.execute(text(
                    "INSERT INTO pipeline_stages "
                    "(id, task_id, stage_id, label, owner_role, sort_order, status) "
                    "VALUES (gen_random_uuid(), :tid::uuid, :sid, :label, :role, :sort, 'pending')"
                ), {
                    "tid": task_id, "sid": stage_id,
                    "label": label, "role": owner_role, "sort": new_sort,
                })
                stats["stages_inserted"] += 1
                continue

            existing_row = existing[stage_id]
            if existing_row["sort_order"] != new_sort:
                bind.execute(text(
                    "UPDATE pipeline_stages SET sort_order = :sort "
                    "WHERE task_id = :tid::uuid AND stage_id = :sid"
                ), {"sort": new_sort, "tid": task_id, "sid": stage_id})
                stats["stages_resorted"] += 1

            if (stage_id == "reviewing"
                    and existing_row["owner_role"] in (None, "", "orchestrator")
                    and existing_row["status"] in ("pending", "active")):
                bind.execute(text(
                    "UPDATE pipeline_stages SET owner_role = 'acceptance' "
                    "WHERE task_id = :tid::uuid AND stage_id = 'reviewing'"
                ), {"tid": task_id})
                stats["reviewer_rebound"] += 1

        stats["tasks_synced"] += 1

    return stats


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # gen_random_uuid lives in pgcrypto; safe to (re)create
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        stats = _backfill_postgres(bind)
    else:
        stats = _backfill_sqlite(bind)

    print(
        f"[5f8a9b0c1d2e] backfill done: {stats['tasks_synced']} tasks synced, "
        f"{stats['stages_inserted']} stages inserted, "
        f"{stats['stages_resorted']} stages resorted, "
        f"{stats['reviewer_rebound']} reviewing rows rebound to acceptance."
    )


def downgrade() -> None:
    """Best-effort downgrade: removes any PENDING rows for the new stage IDs.

    DOES NOT delete done/active rows (they may carry valuable output) and does
    NOT roll back the reviewing -> acceptance owner_role rebind (harmless).
    """
    bind = op.get_bind()
    new_stage_ids = (
        "design", "security-review", "legal-review",
        "data-modeling", "marketing-launch", "finance-review",
    )
    for sid in new_stage_ids:
        bind.execute(text(
            "DELETE FROM pipeline_stages WHERE stage_id = :sid AND status = 'pending'"
        ), {"sid": sid})
