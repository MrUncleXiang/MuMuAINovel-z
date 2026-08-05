"""自动化小说生产流水线：运行记录与检查点模型。"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func
import uuid

from app.database import Base


class PipelineStatus:
    """流水线运行状态"""

    IDLE = "idle"  # 未启动
    RUNNING = "running"  # 运行中（后台自动推进）
    AWAITING_REVIEW = "awaiting_review"  # 停在检查点，等待人工审阅
    PAUSED = "paused"  # 用户手动暂停
    COMPLETED = "completed"  # 用户确认完结
    STOPPED = "stopped"  # 用户停止（不一定是完结）
    FAILED = "failed"  # 运行失败


class PipelineStage:
    """流水线阶段"""

    IDLE = "idle"
    BOOK = "book"  # 阶段1：一键建书
    CHAPTER_LOOP = "chapter_loop"  # 阶段2：章节循环
    CHECKPOINT = "checkpoint"  # 阶段3：检查点暂停
    VOLUME_TRANSITION = "volume_transition"  # 阶段4：卷过渡
    COMPLETED = "completed"


class CheckpointType:
    """检查点触发类型"""

    EVERY_N = "every_n"  # 每 N 章
    VOLUME_END = "volume_end"  # 每卷结束
    MILESTONE = "milestone"  # 里程碑
    MANUAL = "manual"  # 手动


class CheckpointStatus:
    """检查点状态"""

    PENDING = "pending"  # 挂起等待决策
    APPROVED = "approved"  # 用户确认继续
    ROLLBACK = "rollback"  # 用户回滚
    STOPPED = "stopped"  # 用户停止流水线


class NovelPipeline(Base):
    """一本书的流水线运行记录（project_id 唯一，一本一条）。"""

    __tablename__ = "novel_pipelines"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True,
        comment="所属项目（一本书一条流水线）",
    )
    status = Column(String(20), nullable=False, default=PipelineStatus.IDLE, comment="运行状态", index=True)
    current_stage = Column(String(30), nullable=False, default=PipelineStage.IDLE, comment="当前阶段")
    current_outline_id = Column(
        String(36), ForeignKey("outlines.id", ondelete="SET NULL"), nullable=True,
        comment="当前卷(Outline)",
    )
    chapter_count = Column(Integer, nullable=False, default=0, comment="已生成章节总数")
    current_checkpoint_id = Column(
        String(36), ForeignKey("pipeline_checkpoints.id", ondelete="SET NULL"), nullable=True,
        comment="当前挂起的检查点",
    )
    config_snapshot = Column(JSON, nullable=False, default=dict, comment="配置快照：里程碑/每N章/模型/预算等")
    progress_json = Column(JSON, nullable=False, default=dict, comment="运行进度明细")
    checkpoint_history = Column(JSON, nullable=False, default=list, comment="检查点决策历史摘要")
    budget_used_tokens = Column(Integer, nullable=False, default=0, comment="累计 tokens")
    budget_used_amount_cents = Column(Integer, nullable=False, default=0, comment="累计估算金额（分）")
    last_error = Column(Text, nullable=True, comment="最近一次失败原因")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<NovelPipeline(project_id={self.project_id}, status={self.status}, stage={self.current_stage})>"


class PipelineCheckpoint(Base):
    """检查点记录（支撑回退到任意历史检查点）。"""

    __tablename__ = "pipeline_checkpoints"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pipeline_id = Column(
        String(36), ForeignKey("novel_pipelines.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    checkpoint_type = Column(String(20), nullable=False, comment="every_n/volume_end/milestone/manual")
    trigger_chapter_number = Column(Integer, nullable=False, comment="触发时的章节总数")
    chapter_from = Column(Integer, nullable=True, comment="本次检查点覆盖起始章节")
    chapter_to = Column(Integer, nullable=True, comment="本次检查点覆盖结束章节")
    status = Column(String(20), nullable=False, default=CheckpointStatus.PENDING, comment="pending/approved/rollback/stopped")
    decision = Column(String(20), nullable=True, comment="continue/rollback/stop")
    rollback_to_checkpoint_id = Column(
        String(36), ForeignKey("pipeline_checkpoints.id", ondelete="SET NULL"), nullable=True,
        comment="回滚目标检查点（回滚决策时记录）",
    )
    decided_at = Column(DateTime, nullable=True, comment="用户决策时间")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_pipeline_checkpoints_pipeline_created", "pipeline_id", "created_at"),
    )

    def __repr__(self):
        return f"<PipelineCheckpoint(type={self.checkpoint_type}, trigger={self.trigger_chapter_number}, status={self.status})>"
