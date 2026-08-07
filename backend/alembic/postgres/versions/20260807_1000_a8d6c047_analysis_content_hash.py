"""分析任务绑定正式正文版本

Revision ID: a8d6c047
Revises: f7b4a825
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8d6c047"
down_revision: Union[str, None] = "f7b4a825"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analysis_tasks", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column("analysis_tasks", sa.Column("materialized_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_tasks", "materialized_at")
    op.drop_column("analysis_tasks", "content_hash")
