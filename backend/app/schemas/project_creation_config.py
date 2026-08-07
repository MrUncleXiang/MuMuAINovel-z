"""Secret-free project-owned creation configuration."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelSelection(StrictConfigModel):
    provider_config_id: Optional[str] = None
    model: Optional[str] = Field(default=None, max_length=150)


class MCPSelection(StrictConfigModel):
    enabled: bool = True
    plugin_ids: list[str] = Field(default_factory=list)


class PipelinePreferences(StrictConfigModel):
    budget_limit: Optional[float] = Field(default=None, ge=0)
    checkpoint_every_n_chapters: int = Field(default=1, ge=1, le=100)
    milestone_chapters: int = Field(default=30, ge=0, le=100000)
    checkpoint_on_volume_end: bool = True
    auto_advance: bool = False


class ProjectCreationConfigData(StrictConfigModel):
    chapter: ModelSelection = Field(default_factory=ModelSelection)
    analysis: ModelSelection = Field(default_factory=ModelSelection)
    skill_key: Optional[str] = Field(default=None, max_length=200)
    writing_style_id: Optional[int] = None
    mcp: MCPSelection = Field(default_factory=MCPSelection)
    narrative_perspective: Optional[str] = Field(default=None, max_length=50)
    target_word_count: int = Field(default=3000, ge=500, le=10000)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=256, le=100000)
    pipeline: PipelinePreferences = Field(default_factory=PipelinePreferences)


class ProjectCreationConfigResponse(StrictConfigModel):
    project_id: str
    config_version: int
    config: ProjectCreationConfigData
    persisted: bool
    validation_errors: list[str] = Field(default_factory=list)
    updated_at: Optional[str] = None


class FrozenResourceSnapshot(StrictConfigModel):
    id: Optional[str] = None
    name: Optional[str] = None
    version_hash: Optional[str] = None
    provider_protocol: Optional[str] = None
    model: Optional[str] = None


class ProjectCreationRuntimeSnapshot(StrictConfigModel):
    config_version: int
    chapter: FrozenResourceSnapshot
    analysis: FrozenResourceSnapshot
    skill: Optional[FrozenResourceSnapshot] = None
    writing_style: Optional[FrozenResourceSnapshot] = None
    mcp_plugins: list[FrozenResourceSnapshot] = Field(default_factory=list)
    parameters: dict
