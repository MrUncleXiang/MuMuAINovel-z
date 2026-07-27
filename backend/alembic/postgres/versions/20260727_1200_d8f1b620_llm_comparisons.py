"""添加多 LLM 候选比较表

Revision ID: d8f1b620
Revises: c7d2a410
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8f1b620"
down_revision: Union[str, None] = "c7d2a410"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_comparison_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", sa.String(36)),
        sa.Column("usage_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("prompt_snapshot", sa.Text(), nullable=False),
        sa.Column("parameters_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("adopted_candidate_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.CheckConstraint("target_type IN ('chapter', 'outline', 'analysis')", name="ck_llm_comparison_batches_target_type"),
        sa.CheckConstraint("status IN ('draft', 'queued', 'running', 'completed', 'partial_failed', 'failed', 'adopted')", name="ck_llm_comparison_batches_status"),
    )
    for name, columns in (
        ("ix_llm_comparison_batches_user_id", ["user_id"]),
        ("ix_llm_comparison_batches_project_id", ["project_id"]),
        ("ix_llm_comparison_batches_target_type", ["target_type"]),
        ("ix_llm_comparison_batches_target_id", ["target_id"]),
        ("ix_llm_comparison_batches_usage_type", ["usage_type"]),
        ("ix_llm_comparison_batches_status", ["status"]),
        ("idx_llm_comparison_batches_user_created", ["user_id", "created_at"]),
        ("idx_llm_comparison_batches_target", ["target_type", "target_id"]),
    ):
        op.create_index(name, "llm_comparison_batches", columns)

    op.create_table(
        "llm_comparison_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("provider_config_id", sa.String(36)),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("protocol", sa.String(20), nullable=False),
        sa.Column("model", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_text", sa.Text()),
        sa.Column("output_data", sa.JSON()),
        sa.Column("error_type", sa.String(100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("ai_call_log_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("adopted_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["batch_id"], ["llm_comparison_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_config_id"], ["ai_provider_configs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ai_call_log_id"], ["ai_call_logs.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('pending', 'running', 'success', 'failed')", name="ck_llm_comparison_candidates_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_llm_comparison_candidates_attempt_count"),
        sa.UniqueConstraint("batch_id", "provider_config_id", "model", name="uq_llm_comparison_candidate_selection"),
    )
    for name, columns in (
        ("ix_llm_comparison_candidates_batch_id", ["batch_id"]),
        ("ix_llm_comparison_candidates_provider_config_id", ["provider_config_id"]),
        ("ix_llm_comparison_candidates_status", ["status"]),
        ("idx_llm_comparison_candidates_batch_status", ["batch_id", "status"]),
    ):
        op.create_index(name, "llm_comparison_candidates", columns)


def downgrade() -> None:
    op.drop_table("llm_comparison_candidates")
    op.drop_table("llm_comparison_batches")
