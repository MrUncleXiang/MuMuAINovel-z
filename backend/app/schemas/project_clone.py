"""Contracts for creating an independent project clone."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


ProjectCloneMode = Literal["settings_only", "inherit_checkpoint"]


class ProjectCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    mode: ProjectCloneMode = "settings_only"
    checkpoint_id: Optional[str] = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def validate_checkpoint_mode(self):
        self.title = self.title.strip()
        if self.mode == "inherit_checkpoint" and not self.checkpoint_id:
            raise ValueError("继承进度模式必须选择可靠状态节点")
        if self.mode == "settings_only" and self.checkpoint_id:
            raise ValueError("仅复制设定模式不能指定状态节点")
        return self


class ProjectCloneCounts(BaseModel):
    outlines: int = 0
    chapters: int = 0
    careers: int = 0
    characters: int = 0
    relationships: int = 0
    organizations: int = 0
    organization_members: int = 0
    character_careers: int = 0
    analyses: int = 0
    memories: int = 0
    foreshadows: int = 0
    generation_history: int = 0
    state_checkpoints: int = 0


class ProjectCloneResponse(BaseModel):
    project_id: str
    source_project_id: str
    mode: ProjectCloneMode
    inherited_through_chapter: Optional[int] = None
    counts: ProjectCloneCounts

