"""initial schema

Revision ID: 6ff59fe0db1e
Revises: 
Create Date: 2026-04-15 10:58:33.634922
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = '6ff59fe0db1e'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'orgs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id'), nullable=False),
        sa.Column('email', sa.String(320), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(100)),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    op.create_table(
        'agents',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('title', sa.String(100)),
        sa.Column('icon', sa.String(50)),
        sa.Column('color', sa.String(20)),
        sa.Column('description', sa.Text),
        sa.Column('system_prompt', sa.Text),
        sa.Column('quick_prompts', sa.JSON),
        sa.Column('category', sa.String(20)),
        sa.Column('pipeline_role', sa.String(50), nullable=True),
        sa.Column('capabilities', sa.JSON),
        sa.Column('preferred_model', sa.String(100), nullable=True),
        sa.Column('max_tokens', sa.Integer),
        sa.Column('temperature', sa.Float),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('sort_order', sa.Integer, default=0),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    op.create_table(
        'skills',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('category', sa.String(50)),
        sa.Column('description', sa.Text),
        sa.Column('version', sa.String(20)),
        sa.Column('author', sa.String(100)),
        sa.Column('prompt_template', sa.Text),
        sa.Column('input_schema', sa.JSON),
        sa.Column('output_schema', sa.JSON),
        sa.Column('config', sa.JSON),
        sa.Column('tags', sa.JSON),
        sa.Column('rules', sa.JSON),
        sa.Column('hooks', sa.JSON),
        sa.Column('plugins', sa.JSON),
        sa.Column('mcp_tools', sa.JSON),
        sa.Column('enabled', sa.Boolean, default=True, nullable=False),
        sa.Column('is_builtin', sa.Boolean, default=False, nullable=False),
        sa.Column('sort_order', sa.Integer, default=0),
        sa.Column('install_count', sa.Integer, default=0),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_skills_category', 'skills', ['category'])

    op.create_table(
        'model_providers',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('models_url', sa.String(500)),
        sa.Column('chat_url', sa.String(500)),
        sa.Column('api_key_encrypted', sa.Text),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('config', sa.JSON),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    op.create_table(
        'conversations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id'), nullable=False),
        sa.Column('agent_id', sa.String(100)),
        sa.Column('title', sa.String(500)),
        sa.Column('messages', sa.JSON),
        sa.Column('summary', sa.Text, nullable=True),
        sa.Column('revision', sa.Integer, default=0),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_conversations_org_id', 'conversations', ['org_id'])
    op.create_index('ix_conversations_agent_id', 'conversations', ['agent_id'])

    op.create_table(
        'agent_skills',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('agent_id', sa.String(100), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('skill_id', sa.String(100), sa.ForeignKey('skills.id', ondelete='CASCADE'), nullable=False),
        sa.Column('config', sa.JSON),
        sa.Column('enabled', sa.Boolean, default=True, nullable=False),
    )
    op.create_index('ix_agent_skills_agent_id', 'agent_skills', ['agent_id'])

    op.create_table(
        'agent_rules',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('agent_id', sa.String(100), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('rule_type', sa.String(50)),
        sa.Column('content', sa.Text),
        sa.Column('priority', sa.Integer, default=0),
        sa.Column('enabled', sa.Boolean, default=True, nullable=False),
    )
    op.create_index('ix_agent_rules_agent_id', 'agent_rules', ['agent_id'])

    op.create_table(
        'agent_hooks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('agent_id', sa.String(100), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('hook_type', sa.String(50)),
        sa.Column('handler', sa.Text),
        sa.Column('config', sa.JSON),
        sa.Column('enabled', sa.Boolean, default=True, nullable=False),
    )
    op.create_index('ix_agent_hooks_agent_id', 'agent_hooks', ['agent_id'])

    op.create_table(
        'agent_plugins',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('agent_id', sa.String(100), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('plugin_type', sa.String(50)),
        sa.Column('config', sa.JSON),
        sa.Column('version', sa.String(20)),
        sa.Column('enabled', sa.Boolean, default=True, nullable=False),
    )
    op.create_index('ix_agent_plugins_agent_id', 'agent_plugins', ['agent_id'])

    op.create_table(
        'agent_mcps',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('agent_id', sa.String(100), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('server_url', sa.String(500)),
        sa.Column('tools', sa.JSON),
        sa.Column('config', sa.JSON),
        sa.Column('enabled', sa.Boolean, default=True, nullable=False),
    )
    op.create_index('ix_agent_mcps_agent_id', 'agent_mcps', ['agent_id'])

    op.create_table(
        'token_usage',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('agent_id', sa.String(100), nullable=True),
        sa.Column('provider', sa.String(50)),
        sa.Column('model', sa.String(100)),
        sa.Column('prompt_tokens', sa.Integer, default=0),
        sa.Column('completion_tokens', sa.Integer, default=0),
        sa.Column('total_tokens', sa.Integer, default=0),
        sa.Column('cost_usd', sa.Float, default=0.0),
        sa.Column('latency_ms', sa.Integer),
        sa.Column('endpoint', sa.String(50)),
        sa.Column('metadata_extra', sa.JSON),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_token_usage_org_id', 'token_usage', ['org_id'])
    op.create_index('ix_token_usage_user_id', 'token_usage', ['user_id'])
    op.create_index('ix_token_usage_agent_id', 'token_usage', ['agent_id'])

    op.create_table(
        'pipeline_tasks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('source', sa.String(20)),
        sa.Column('source_message_id', sa.String(200), nullable=True),
        sa.Column('source_user_id', sa.String(200), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('current_stage_id', sa.String(50)),
        sa.Column('created_by', sa.String(200)),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id'), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    op.create_table(
        'pipeline_stages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('task_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage_id', sa.String(50), nullable=False),
        sa.Column('label', sa.String(100)),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('owner_role', sa.String(100)),
        sa.Column('output', sa.Text, nullable=True),
        sa.Column('sort_order', sa.Integer, default=0),
        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
    )
    op.create_index('ix_pipeline_stages_task_id', 'pipeline_stages', ['task_id'])

    op.create_table(
        'pipeline_artifacts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('task_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('artifact_type', sa.String(50)),
        sa.Column('name', sa.String(200)),
        sa.Column('content', sa.Text),
        sa.Column('stage_id', sa.String(50)),
        sa.Column('metadata_extra', sa.JSON),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_pipeline_artifacts_task_id', 'pipeline_artifacts', ['task_id'])

    op.create_table(
        'task_memories',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('task_id', sa.String(200)),
        sa.Column('stage_id', sa.String(50)),
        sa.Column('role', sa.String(100)),
        sa.Column('title', sa.String(500)),
        sa.Column('content', sa.Text),
        sa.Column('content_hash', sa.String(64), unique=True),
        sa.Column('summary', sa.Text),
        sa.Column('tags', sa.JSON),
        sa.Column('quality_score', sa.Float),
        sa.Column('token_count', sa.Integer),
        sa.Column('embedding_model', sa.String(100)),
        sa.Column('metadata_extra', sa.JSON),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_task_memories_task_id', 'task_memories', ['task_id'])

    op.create_table(
        'learned_patterns',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('pattern_type', sa.String(50)),
        sa.Column('role', sa.String(100)),
        sa.Column('stage_id', sa.String(50)),
        sa.Column('description', sa.Text),
        sa.Column('example_task_ids', sa.JSON),
        sa.Column('frequency', sa.Integer, default=0),
        sa.Column('confidence', sa.Float, default=0.0),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('learned_patterns')
    op.drop_table('task_memories')
    op.drop_table('pipeline_artifacts')
    op.drop_table('pipeline_stages')
    op.drop_table('pipeline_tasks')
    op.drop_table('token_usage')
    op.drop_table('agent_mcps')
    op.drop_table('agent_plugins')
    op.drop_table('agent_hooks')
    op.drop_table('agent_rules')
    op.drop_table('agent_skills')
    op.drop_table('conversations')
    op.drop_table('model_providers')
    op.drop_table('skills')
    op.drop_table('agents')
    op.drop_table('users')
    op.drop_table('orgs')
