"""多 LLM 服务配置、任务路由与调用日志 API 模型。"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


SUPPORTED_PROTOCOLS = {"openai", "anthropic", "gemini"}
SUPPORTED_WIRE_APIS = {"chat_completions", "responses"}


class AIProviderConfigBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    protocol: str = Field(default="openai")
    wire_api: str = Field(default="chat_completions")
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=1000)
    default_model: Optional[str] = Field(default=None, max_length=150)
    models: List[str] = Field(default_factory=list)
    enabled: bool = True
    is_default: bool = False
    sort_order: int = 0
    notes: Optional[str] = None

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_PROTOCOLS:
            raise ValueError("protocol 必须是 openai、anthropic 或 gemini")
        return normalized

    @field_validator("wire_api")
    @classmethod
    def validate_wire_api(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_WIRE_APIS:
            raise ValueError("wire_api 必须是 chat_completions 或 responses")
        return normalized

    @field_validator("models")
    @classmethod
    def normalize_models(cls, values: List[str]) -> List[str]:
        result = []
        for value in values:
            normalized = value.strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result


class AIProviderConfigCreate(AIProviderConfigBase):
    pass


class AIProviderConfigUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    protocol: Optional[str] = None
    wire_api: Optional[str] = None
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=1000)
    default_model: Optional[str] = Field(default=None, max_length=150)
    models: Optional[List[str]] = None
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None
    sort_order: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_PROTOCOLS:
            raise ValueError("protocol 必须是 openai、anthropic 或 gemini")
        return normalized

    @field_validator("wire_api")
    @classmethod
    def validate_wire_api(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_WIRE_APIS:
            raise ValueError("wire_api 必须是 chat_completions 或 responses")
        return normalized


class AIProviderConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    protocol: str
    wire_api: str
    base_url: str
    api_key_configured: bool
    api_key_hint: Optional[str] = None
    default_model: Optional[str] = None
    models: List[str] = Field(default_factory=list)
    enabled: bool
    is_default: bool
    sort_order: int
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AIUsageRouteUpdate(BaseModel):
    provider_config_id: Optional[str] = None
    model: Optional[str] = Field(default=None, max_length=150)


class AIUsageRouteResponse(BaseModel):
    usage_type: str
    provider_config_id: Optional[str] = None
    provider_name: Optional[str] = None
    model: Optional[str] = None


class AISelectionResponse(BaseModel):
    source: str
    usage_type: str
    provider_config_id: Optional[str] = None
    provider_name: str
    protocol: str
    wire_api: str
    model: str


class AICallLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    task_trace_id: Optional[str] = None
    project_id: Optional[str] = None
    chapter_id: Optional[str] = None
    usage_type: str
    provider_config_id: Optional[str] = None
    provider_name: Optional[str] = None
    protocol: str
    requested_model: Optional[str] = None
    actual_model: str
    status: str
    request_mode: str
    is_stream: bool
    retry_index: int
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    prompt_length: int
    response_length: int
    first_token_ms: Optional[int] = None
    duration_ms: Optional[int] = None
    finish_reason: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime


class AICallLogListResponse(BaseModel):
    items: List[AICallLogResponse]
    total: int


class AIUsageSummaryResponse(BaseModel):
    total_calls: int
    success_calls: int
    failed_calls: int
    total_tokens: int
    average_duration_ms: Optional[int] = None
