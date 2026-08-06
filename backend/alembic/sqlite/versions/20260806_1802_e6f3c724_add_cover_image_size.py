"""添加封面分辨率配置列（sqlite 同步）

Revision ID: e6f3c724
Revises: c4d8f023
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f3c724"
down_revision: Union[str, None] = "c4d8f023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("cover_image_size", sa.String(20), nullable=False, server_default="auto"),
    )


def downgrade() -> None:
    op.drop_column("settings", "cover_image_size")
