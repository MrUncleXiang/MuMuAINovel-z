"""新增项目创作配置（sqlite 同步）

Revision ID: d0a9f37a
Revises: b9e7d158
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0a9f37a"
down_revision: Union[str, None] = "b9e7d158"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_creation_configs",
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )


def downgrade() -> None:
    op.drop_table("project_creation_configs")
