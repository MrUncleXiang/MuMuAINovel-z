"""批量生成任务加 task_type（sqlite 同步）

Revision ID: g8c5b936
Revises: e6f3c724
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g8c5b936"
down_revision: Union[str, None] = "e6f3c724"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "batch_generation_tasks",
        sa.Column("task_type", sa.String(20), nullable=False, server_default="batch_generate"),
    )


def downgrade() -> None:
    op.drop_column("batch_generation_tasks", "task_type")
