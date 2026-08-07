"""Versioned project state captured after formal chapter analysis."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SnapshotEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    data: dict[str, Any] = Field(default_factory=dict)


class ProjectStateSnapshotV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    chapter_number: int
    characters: list[SnapshotEntity] = Field(default_factory=list)
    relationships: list[SnapshotEntity] = Field(default_factory=list)
    organizations: list[SnapshotEntity] = Field(default_factory=list)
    organization_members: list[SnapshotEntity] = Field(default_factory=list)
    careers: list[SnapshotEntity] = Field(default_factory=list)
    character_careers: list[SnapshotEntity] = Field(default_factory=list)
    foreshadows: list[SnapshotEntity] = Field(default_factory=list)
    story_memories: list[SnapshotEntity] = Field(default_factory=list)


class ProjectStateCheckpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    chapter_id: str
    chapter_number: int
    analysis_task_id: Optional[str] = None
    content_hash: str
    schema_version: int
    status: str
    invalid_reason: Optional[str] = None
    config_version: Optional[int] = None
    created_at: datetime
    invalidated_at: Optional[datetime] = None
