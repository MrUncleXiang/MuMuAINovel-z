"""新增 projects.review_config 字段（正文审查配置）

Revision ID: f6a3c842
Revises: e4b1d2a3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a3c842"
down_revision: Union[str, None] = "e4b1d2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("review_config", sa.Text(), nullable=True, comment="正文审查配置(JSON)"))


def downgrade() -> None:
    op.drop_column("projects", "review_config")
