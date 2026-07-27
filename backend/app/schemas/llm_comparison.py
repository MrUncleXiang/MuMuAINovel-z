"""多 LLM 候选比较 API 数据结构。"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TargetType = Literal["chapter", "outline", "analysis"]


class LLMComparisonSelection(BaseModel):
    provider_config_id: str
    model: str = Field(..., min_length=1, max_length=150)

    @field_validator("model")
    @classmethod
    def clean_model(cls, value: str) -> str:
        return value.strip()


class LLMComparisonBatchCreate(BaseModel):
    project_id: str
    target_type: TargetType
    target_id: Optional[str] = None
    usage_type: str = Field(..., min_length=1, max_length=50)
    input_snapshot: Dict[str, Any]
    prompt_snapshot: str = Field(..., min_length=1)
    parameters_snapshot: Dict[str, Any] = Field(default_factory=dict)
    selections: List[LLMComparisonSelection] = Field(..., min_length=2, max_length=4)

    @model_validator(mode="after")
    def unique_selections(self):
        keys = {(item.provider_config_id, item.model) for item in self.selections}
        if len(keys) != len(self.selections):
            raise ValueError("不能重复选择同一 AI 服务和模型")
        return self

    @field_validator("usage_type")
    @classmethod
    def clean_usage_type(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("parameters_snapshot")
    @classmethod
    def safe_generation_parameters(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"不支持的生成参数：{', '.join(sorted(unknown))}")
        return values


class LLMComparisonCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_config_id: Optional[str] = None
    provider_name: str
    protocol: str
    model: str
    status: str
    attempt_count: int
    output_text: Optional[str] = None
    output_data: Optional[Any] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
    ai_call_log_id: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    adopted_at: Optional[datetime] = None


class LLMComparisonBatchResponse(BaseModel):
    id: str
    project_id: str
    target_type: TargetType
    target_id: Optional[str] = None
    usage_type: str
    status: str
    input_snapshot: Dict[str, Any]
    prompt_snapshot: str
    parameters_snapshot: Dict[str, Any]
    adopted_candidate_id: Optional[str] = None
    candidates: List[LLMComparisonCandidateResponse]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class LLMComparisonBatchListResponse(BaseModel):
    items: List[LLMComparisonBatchResponse]
    total: int
