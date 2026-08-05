"""章节数据模型"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base
import uuid


class ChapterStatus:
    """章节状态枚举（流水线 v1 起统一引用常量，不再散落字符串）"""

    DRAFT = "draft"  # 默认：草稿/空
    PENDING = "pending"  # 排队等待生成
    RUNNING = "running"  # 正在生成中
    COMPLETED = "completed"  # 生成完成
    FAILED = "failed"  # 生成失败
    AWAITING_REVIEW = "awaiting_review"  # 流水线：已生成，停在检查点等待人工审阅
    REWRITING_ROLLBACK = "rewriting_rollback"  # 流水线：被回滚后正在重新生成


class Chapter(Base):
    """章节表"""
    __tablename__ = "chapters"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False, comment="章节序号")
    title = Column(String(200), nullable=False, comment="章节标题")
    content = Column(Text, comment="章节内容")
    summary = Column(Text, comment="章节摘要")
    word_count = Column(Integer, default=0, comment="字数统计")
    status = Column(String(20), default="draft", comment="章节状态")
    
    # 大纲关联字段（实现一对多关系）
    outline_id = Column(String(36), ForeignKey("outlines.id", ondelete="SET NULL"), nullable=True, comment="关联的大纲ID")
    sub_index = Column(Integer, default=1, comment="大纲下的子章节序号")
    
    # 大纲展开规划数据（JSON格式）
    expansion_plan = Column(Text, comment="展开规划详情(JSON): 包含key_events, character_focus, emotional_tone等")
    
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    def __repr__(self):
        return f"<Chapter(id={self.id}, chapter_number={self.chapter_number}, title={self.title}, outline_id={self.outline_id})>"