"""添加封面分辨率配置列

Revision ID: d5e2b613
Revises: a7c3e912
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e2b613"
down_revision: Union[str, None] = "a7c3e912"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("cover_image_size", sa.String(20), nullable=False, server_default="auto"),
    )


def downgrade() -> None:
    op.drop_column("settings", "cover_image_size")
