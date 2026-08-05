"""题材模板库：手动种子 + AI 分析提炼的热门题材模板。"""
from sqlalchemy import Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.sql import func
import uuid

from app.database import Base


class ThemeTemplate(Base):
    """一套热门题材模板（标签/世界观公式/角色原型/卷结构）。"""

    __tablename__ = "theme_templates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(200), nullable=False, comment="模板名称（题材名）")
    genre = Column(String(50), nullable=True, comment="小说类型")
    tags = Column(JSON, nullable=False, default=list, comment="标签列表")
    description = Column(Text, nullable=True, comment="题材一句话描述")
    world_formula = Column(Text, nullable=True, comment="世界观公式（设定模板）")
    character_prototypes = Column(JSON, nullable=False, default=list, comment="角色原型列表")
    volume_structure = Column(Text, nullable=True, comment="常见卷结构/节奏")
    source = Column(String(50), nullable=False, default="manual", comment="manual/firecrawl")
    source_refs = Column(JSON, nullable=False, default=list, comment="来源示例（链接/书名）")
    usage_count = Column(Integer, nullable=False, default=0, comment="被用于开书次数")
    created_by = Column(String(100), nullable=True, comment="创建者 user_id")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<ThemeTemplate(title={self.title}, genre={self.genre})>"
