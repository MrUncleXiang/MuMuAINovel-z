"""Consistent project state captured at a formal chapter boundary."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class ProjectStateCheckpoint(Base):
    __tablename__ = "project_state_checkpoints"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    analysis_task_id = Column(
        String(36),
        ForeignKey("analysis_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_hash = Column(String(64), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="valid")
    invalid_reason = Column(Text, nullable=True)
    config_version = Column(Integer, nullable=True)
    state_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    invalidated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "chapter_id",
            "content_hash",
            "analysis_task_id",
            name="uq_project_state_checkpoint_version",
        ),
        Index(
            "idx_project_state_checkpoint_lookup",
            "project_id",
            "chapter_number",
            "status",
        ),
    )
