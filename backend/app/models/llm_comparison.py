"""同一份冻结输入的多 LLM 候选比较记录。"""
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class LLMComparisonBatch(Base):
    """一次多模型比较；输入与参数创建后不可改。"""

    __tablename__ = "llm_comparison_batches"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    target_type = Column(String(30), nullable=False, index=True)
    target_id = Column(String(36), nullable=True, index=True)
    usage_type = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="draft", index=True)
    input_snapshot = Column(JSON, nullable=False)
    prompt_snapshot = Column(Text, nullable=False)
    parameters_snapshot = Column(JSON, nullable=False, default=dict)
    adopted_candidate_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "target_type IN ('chapter', 'outline', 'analysis')",
            name="ck_llm_comparison_batches_target_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'queued', 'running', 'completed', 'partial_failed', 'failed', 'adopted')",
            name="ck_llm_comparison_batches_status",
        ),
        Index("idx_llm_comparison_batches_user_created", "user_id", "created_at"),
        Index("idx_llm_comparison_batches_target", "target_type", "target_id"),
    )


class LLMComparisonCandidate(Base):
    """批次中的一个供应商/模型输出。"""

    __tablename__ = "llm_comparison_candidates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id = Column(
        String(36),
        ForeignKey("llm_comparison_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_config_id = Column(
        String(36),
        ForeignKey("ai_provider_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_name = Column(String(100), nullable=False)
    protocol = Column(String(20), nullable=False)
    model = Column(String(150), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    output_text = Column(Text, nullable=True)
    output_data = Column(JSON, nullable=True)
    error_type = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    ai_call_log_id = Column(String(36), ForeignKey("ai_call_logs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    adopted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed')",
            name="ck_llm_comparison_candidates_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_llm_comparison_candidates_attempt_count"),
        UniqueConstraint(
            "batch_id", "provider_config_id", "model",
            name="uq_llm_comparison_candidate_selection",
        ),
        Index("idx_llm_comparison_candidates_batch_status", "batch_id", "status"),
    )
