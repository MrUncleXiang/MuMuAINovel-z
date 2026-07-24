"""添加 LLM 服务配置、任务路由和调用日志（SQLite）

Revision ID: 74d19be2
Revises: 3a08fc61773f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "74d19be2"
down_revision: Union[str, None] = "3a08fc61773f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("protocol", sa.String(20), nullable=False, server_default="openai"),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key", sa.String(1000)),
        sa.Column("default_model", sa.String(150)),
        sa.Column("models", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_ai_provider_configs_user_name"),
    )
    op.create_index("ix_ai_provider_configs_user_id", "ai_provider_configs", ["user_id"])
    op.create_index("idx_ai_provider_configs_user_enabled", "ai_provider_configs", ["user_id", "enabled"])

    op.create_table(
        "ai_usage_routes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("usage_type", sa.String(50), nullable=False),
        sa.Column("provider_config_id", sa.String(36), sa.ForeignKey("ai_provider_configs.id", ondelete="SET NULL")),
        sa.Column("model", sa.String(150)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "usage_type", name="uq_ai_usage_routes_user_usage"),
    )
    op.create_index("ix_ai_usage_routes_user_id", "ai_usage_routes", ["user_id"])

    op.create_table(
        "ai_call_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("task_trace_id", sa.String(36)),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("project_id", sa.String(36)),
        sa.Column("chapter_id", sa.String(36)),
        sa.Column("usage_type", sa.String(50), nullable=False, server_default="default"),
        sa.Column("provider_config_id", sa.String(36), sa.ForeignKey("ai_provider_configs.id", ondelete="SET NULL")),
        sa.Column("provider_name", sa.String(100)),
        sa.Column("protocol", sa.String(20), nullable=False),
        sa.Column("requested_model", sa.String(150)),
        sa.Column("actual_model", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("request_mode", sa.String(30), nullable=False),
        sa.Column("is_stream", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retry_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_from_config_id", sa.String(36)),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("prompt_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_token_ms", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("finish_reason", sa.String(100)),
        sa.Column("error_type", sa.String(100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    for name, columns in (
        ("ix_ai_call_logs_request_id", ["request_id"]),
        ("ix_ai_call_logs_task_trace_id", ["task_trace_id"]),
        ("ix_ai_call_logs_user_id", ["user_id"]),
        ("ix_ai_call_logs_project_id", ["project_id"]),
        ("ix_ai_call_logs_chapter_id", ["chapter_id"]),
        ("ix_ai_call_logs_usage_type", ["usage_type"]),
        ("ix_ai_call_logs_provider_config_id", ["provider_config_id"]),
        ("ix_ai_call_logs_actual_model", ["actual_model"]),
        ("ix_ai_call_logs_status", ["status"]),
        ("ix_ai_call_logs_created_at", ["created_at"]),
        ("idx_ai_call_logs_user_created", ["user_id", "created_at"]),
        ("idx_ai_call_logs_project_created", ["project_id", "created_at"]),
        ("idx_ai_call_logs_provider_model", ["provider_config_id", "actual_model"]),
    ):
        op.create_index(name, "ai_call_logs", columns)


def downgrade() -> None:
    op.drop_table("ai_call_logs")
    op.drop_table("ai_usage_routes")
    op.drop_table("ai_provider_configs")
