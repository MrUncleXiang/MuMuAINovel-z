"""添加小说流水线运行记录表（sqlite 同步）

Revision ID: b3e9f105
Revises: a2d8b947
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3e9f105"
down_revision: Union[str, None] = "a2d8b947"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "novel_pipelines",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="idle"),
        sa.Column("current_stage", sa.String(30), nullable=False, server_default="idle"),
        sa.Column("current_outline_id", sa.String(36), nullable=True),
        sa.Column("chapter_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("checkpoint_history", sa.JSON(), nullable=False),
        sa.Column("budget_used_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("budget_used_amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_outline_id"], ["outlines.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_novel_pipelines_project"),
    )
    op.create_index("ix_novel_pipelines_project_id", "novel_pipelines", ["project_id"])
    op.create_index("ix_novel_pipelines_status", "novel_pipelines", ["status"])

    op.create_table(
        "pipeline_checkpoints",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("pipeline_id", sa.String(36), nullable=False),
        sa.Column("checkpoint_type", sa.String(20), nullable=False),
        sa.Column("trigger_chapter_number", sa.Integer(), nullable=False),
        sa.Column("chapter_from", sa.Integer(), nullable=True),
        sa.Column("chapter_to", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decision", sa.String(20), nullable=True),
        sa.Column("rollback_to_checkpoint_id", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_id"], ["novel_pipelines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["rollback_to_checkpoint_id"], ["pipeline_checkpoints.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_checkpoints_pipeline_id", "pipeline_checkpoints", ["pipeline_id"],
    )
    op.create_index(
        "idx_pipeline_checkpoints_pipeline_created", "pipeline_checkpoints", ["pipeline_id", "created_at"],
    )

    op.add_column(
        "novel_pipelines",
        sa.Column("current_checkpoint_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_novel_pipelines_current_checkpoint",
        "novel_pipelines", "pipeline_checkpoints",
        ["current_checkpoint_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_novel_pipelines_current_checkpoint", "novel_pipelines", type_="foreignkey",
    )
    op.drop_column("novel_pipelines", "current_checkpoint_id")
    op.drop_index("idx_pipeline_checkpoints_pipeline_created", table_name="pipeline_checkpoints")
    op.drop_index("ix_pipeline_checkpoints_pipeline_id", table_name="pipeline_checkpoints")
    op.drop_table("pipeline_checkpoints")
    op.drop_index("ix_novel_pipelines_status", table_name="novel_pipelines")
    op.drop_index("ix_novel_pipelines_project_id", table_name="novel_pipelines")
    op.drop_table("novel_pipelines")
