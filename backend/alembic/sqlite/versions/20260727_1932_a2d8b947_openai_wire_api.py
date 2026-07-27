"""添加 OpenAI wire API 类型（SQLite）

Revision ID: a2d8b947
Revises: 91ac57e4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2d8b947"
down_revision: Union[str, None] = "91ac57e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_provider_configs",
        sa.Column("wire_api", sa.String(30), nullable=False, server_default="chat_completions"),
    )


def downgrade() -> None:
    with op.batch_alter_table("ai_provider_configs") as batch_op:
        batch_op.drop_column("wire_api")
