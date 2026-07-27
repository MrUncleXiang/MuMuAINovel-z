"""添加 OpenAI wire API 类型

Revision ID: e9a4c731
Revises: d8f1b620
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9a4c731"
down_revision: Union[str, None] = "d8f1b620"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_provider_configs",
        sa.Column("wire_api", sa.String(30), nullable=False, server_default="chat_completions"),
    )


def downgrade() -> None:
    op.drop_column("ai_provider_configs", "wire_api")
