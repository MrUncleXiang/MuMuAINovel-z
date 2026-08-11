"""章节审查记录表：每章最近一次正文审查的问题列表与结果"""
from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime
from app.database import Base
from datetime import datetime


class ChapterReviewRecord(Base):
    """章节审查记录"""
    __tablename__ = "chapter_review_records"

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), nullable=False, index=True, comment="项目ID")
    chapter_id = Column(String(36), nullable=False, index=True, comment="章节ID")
    chapter_number = Column(Integer, nullable=False, comment="章节序号")
    problems = Column(Text, nullable=True, comment="问题列表 JSON")
    major = Column(Boolean, default=False, comment="是否存在结构级问题")
    rounds = Column(Integer, default=1, comment="审查轮数")
    source = Column(String(20), default="auto", comment="来源: auto=生成后自动 / volume=卷检查")
    created_at = Column(DateTime, default=datetime.utcnow, comment="审查时间")
