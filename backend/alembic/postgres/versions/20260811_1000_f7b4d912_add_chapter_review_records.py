"""新增章节审查记录表 chapter_review_records

Revision ID: f7b4d912
Revises: f6a3c842
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7b4d912"
down_revision: Union[str, None] = "f6a3c842"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chapter_review_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("chapter_id", sa.String(36), nullable=False, index=True),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("problems", sa.Text(), nullable=True),
        sa.Column("major", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rounds", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(20), nullable=False, server_default="auto"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("chapter_review_records")
