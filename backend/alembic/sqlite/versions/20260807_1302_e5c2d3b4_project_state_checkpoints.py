"""Add project state checkpoints for SQLite.

Revision ID: e5c2d3b4
Revises: d0a9f37a
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5c2d3b4"
down_revision: Union[str, None] = "d0a9f37a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_state_checkpoints",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("chapter_id", sa.String(36), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("analysis_task_id", sa.String(36), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="valid"),
        sa.Column("invalid_reason", sa.Text(), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_task_id"], ["analysis_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "chapter_id", "content_hash", "analysis_task_id",
            name="uq_project_state_checkpoint_version",
        ),
    )
    op.create_index(
        "idx_project_state_checkpoint_lookup",
        "project_state_checkpoints",
        ["project_id", "chapter_number", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_project_state_checkpoint_lookup", table_name="project_state_checkpoints")
    op.drop_table("project_state_checkpoints")
