"""一次真实 LLM HTTP 调用的审计记录（不保存 API Key 和正文）。"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func
import uuid

from app.database import Base


class AICallLog(Base):
    __tablename__ = "ai_call_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String(36), nullable=False, unique=True, index=True)
    task_trace_id = Column(String(36), nullable=True, index=True, comment="同一用户动作内的多次调用共用")
    user_id = Column(String(100), nullable=False, index=True)
    project_id = Column(String(36), nullable=True, index=True)
    chapter_id = Column(String(36), nullable=True, index=True)
    usage_type = Column(String(50), nullable=False, default="default", index=True)

    provider_config_id = Column(
        String(36),
        ForeignKey("ai_provider_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_name = Column(String(100), nullable=True, comment="快照，配置删除后仍可追溯")
    protocol = Column(String(20), nullable=False)
    requested_model = Column(String(150), nullable=True)
    actual_model = Column(String(150), nullable=False, index=True)

    status = Column(String(20), nullable=False, index=True, comment="success/failed")
    request_mode = Column(String(30), nullable=False)
    is_stream = Column(Boolean, nullable=False, default=False)
    retry_index = Column(Integer, nullable=False, default=0)
    fallback_from_config_id = Column(String(36), nullable=True)

    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    prompt_length = Column(Integer, nullable=False, default=0)
    response_length = Column(Integer, nullable=False, default=0)
    first_token_ms = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    finish_reason = Column(String(100), nullable=True)
    error_type = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("idx_ai_call_logs_user_created", "user_id", "created_at"),
        Index("idx_ai_call_logs_project_created", "project_id", "created_at"),
        Index("idx_ai_call_logs_provider_model", "provider_config_id", "actual_model"),
    )
