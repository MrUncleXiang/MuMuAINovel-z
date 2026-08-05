"""流水线 API 模型。"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PipelineStartRequest(BaseModel):
    project_id: str = Field(..., description="项目ID")
    config: Optional[Dict[str, Any]] = Field(default=None, description="流水线配置（缺省用默认）")


class PipelineCheckpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    checkpoint_type: str
    trigger_chapter_number: int
    chapter_from: Optional[int] = None
    chapter_to: Optional[int] = None
    status: str
    decision: Optional[str] = None
    rollback_to_checkpoint_id: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: datetime


class PipelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: str
    current_stage: str
    current_outline_id: Optional[str] = None
    chapter_count: int
    current_checkpoint_id: Optional[str] = None
    config_snapshot: Dict[str, Any] = Field(default_factory=dict)
    progress_json: Dict[str, Any] = Field(default_factory=dict)
    checkpoint_history: List[Dict[str, Any]] = Field(default_factory=list)
    budget_used_tokens: int = 0
    budget_used_amount_cents: int = 0
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    current_checkpoint: Optional[PipelineCheckpointResponse] = None


class PipelineListResponse(BaseModel):
    items: List[PipelineResponse]
    total: int
