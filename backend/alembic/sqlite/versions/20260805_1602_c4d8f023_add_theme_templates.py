"""添加题材模板表（sqlite 同步）

Revision ID: c4d8f023
Revises: b3e9f105
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d8f023"
down_revision: Union[str, None] = "b3e9f105"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "theme_templates",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("genre", sa.String(50), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("world_formula", sa.Text(), nullable=True),
        sa.Column("character_prototypes", sa.JSON(), nullable=False),
        sa.Column("volume_structure", sa.Text(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_theme_templates_genre", "theme_templates", ["genre"])


def downgrade() -> None:
    op.drop_index("ix_theme_templates_genre", table_name="theme_templates")
    op.drop_table("theme_templates")
