"""题材模板 API 模型。"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ThemeTemplateCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    genre: Optional[str] = Field(default=None, max_length=50)
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    world_formula: Optional[str] = None
    character_prototypes: List[dict] = Field(default_factory=list)
    volume_structure: Optional[str] = None
    source_refs: List[str] = Field(default_factory=list)


class ThemeAnalyzeRequest(BaseModel):
    examples: List[str] = Field(..., min_length=1, description="示例：小说标题/链接/简介")
    genre_hint: Optional[str] = Field(default=None, max_length=50, description="题材类型提示（可选）")


class ThemeAnalyzeResponse(ThemeTemplateCreate):
    pass


class ThemeTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    genre: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    world_formula: Optional[str] = None
    character_prototypes: List[dict] = Field(default_factory=list)
    volume_structure: Optional[str] = None
    source: str
    source_refs: List[str] = Field(default_factory=list)
    usage_count: int = 0
    created_at: datetime
    updated_at: datetime
