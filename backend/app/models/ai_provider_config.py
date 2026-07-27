"""可复用的 LLM 服务配置与按任务默认路由。"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func
import uuid

from app.database import Base


class AIProviderConfig(Base):
    """用户保存的一套可复用 LLM 服务配置。"""

    __tablename__ = "ai_provider_configs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, index=True)
    name = Column(String(100), nullable=False, comment="用户可识别的配置名称")
    protocol = Column(String(20), nullable=False, default="openai", comment="openai/anthropic/gemini")
    wire_api = Column(String(30), nullable=False, default="chat_completions", comment="chat_completions/responses")
    base_url = Column(String(500), nullable=False)
    api_key = Column(String(1000), nullable=True)
    default_model = Column(String(150), nullable=True)
    model_catalog = Column("models", JSON, nullable=False, default=list, comment="缓存或手工维护的模型列表")
    enabled = Column(Boolean, nullable=False, default=True)
    is_default = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_ai_provider_configs_user_name"),
        Index("idx_ai_provider_configs_user_enabled", "user_id", "enabled"),
    )


class AIUsageRoute(Base):
    """某类小说任务默认使用哪套配置；本次手选仍具有最高优先级。"""

    __tablename__ = "ai_usage_routes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, index=True)
    usage_type = Column(String(50), nullable=False, comment="chapter_write/analysis/outline/polish 等")
    provider_config_id = Column(
        String(36),
        ForeignKey("ai_provider_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    model = Column(String(150), nullable=True, comment="为空时使用服务配置的默认模型")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "usage_type", name="uq_ai_usage_routes_user_usage"),
    )
