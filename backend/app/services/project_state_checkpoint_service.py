"""Capture and validate chapter-bound project state checkpoints."""

from datetime import date, datetime
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.career import Career, CharacterCareer
from app.models.character import Character
from app.models.foreshadow import Foreshadow
from app.models.memory import StoryMemory
from app.models.project_creation_config import ProjectCreationConfig
from app.models.project_state_checkpoint import ProjectStateCheckpoint
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.models.analysis_task import AnalysisTask
from app.models.chapter import Chapter
from app.schemas.project_state_checkpoint import ProjectStateSnapshotV1, SnapshotEntity


SNAPSHOT_MODELS = (
    ("characters", Character),
    ("relationships", CharacterRelationship),
    ("organizations", Organization),
    ("organization_members", OrganizationMember),
    ("careers", Career),
    ("character_careers", CharacterCareer),
    ("foreshadows", Foreshadow),
    ("story_memories", StoryMemory),
)
TIMESTAMP_COLUMNS = {"created_at", "updated_at"}


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def serialize_snapshot_entity(instance: Any) -> SnapshotEntity:
    data = {
        column.name: _json_value(getattr(instance, column.name))
        for column in instance.__table__.columns
        if column.name not in TIMESTAMP_COLUMNS and column.name != "id"
    }
    return SnapshotEntity(id=str(instance.id), data=data)


async def capture_project_state(
    db: AsyncSession,
    *,
    project_id: str,
    chapter_number: int,
) -> ProjectStateSnapshotV1:
    values: dict[str, Any] = {
        "schema_version": 1,
        "chapter_number": chapter_number,
    }
    for field_name, model in SNAPSHOT_MODELS:
        if model is OrganizationMember:
            rows = list((await db.scalars(
                select(model)
                .join(Organization, Organization.id == OrganizationMember.organization_id)
                .where(Organization.project_id == project_id)
                .order_by(model.id)
            )).all())
        elif model is CharacterCareer:
            rows = list((await db.scalars(
                select(model)
                .join(Character, Character.id == CharacterCareer.character_id)
                .where(Character.project_id == project_id)
                .order_by(model.id)
            )).all())
        else:
            rows = list((await db.scalars(
                select(model).where(model.project_id == project_id).order_by(model.id)
            )).all())
        values[field_name] = [serialize_snapshot_entity(row) for row in rows]
    return ProjectStateSnapshotV1.model_validate(values)


async def create_project_state_checkpoint(
    db: AsyncSession,
    *,
    chapter: Chapter,
    analysis_task: AnalysisTask,
) -> ProjectStateCheckpoint:
    """Capture the state produced by one analysis before its transaction commits."""
    existing = await db.scalar(select(ProjectStateCheckpoint).where(
        ProjectStateCheckpoint.analysis_task_id == analysis_task.id,
    ))
    if existing is not None:
        return existing

    previous = None
    if chapter.chapter_number > 1:
        previous = await db.scalar(
            select(ProjectStateCheckpoint)
            .where(
                ProjectStateCheckpoint.project_id == chapter.project_id,
                ProjectStateCheckpoint.chapter_number == chapter.chapter_number - 1,
                ProjectStateCheckpoint.status == "valid",
            )
            .order_by(ProjectStateCheckpoint.created_at.desc())
            .limit(1)
        )
    later_materialized = await db.scalar(
        select(AnalysisTask.id)
        .join(Chapter, Chapter.id == AnalysisTask.chapter_id)
        .where(
            Chapter.project_id == chapter.project_id,
            Chapter.chapter_number > chapter.chapter_number,
            AnalysisTask.materialized_at.is_not(None),
        )
        .limit(1)
    )
    is_continuous = chapter.chapter_number == 1 or previous is not None
    is_current_edge = later_materialized is None
    status = "valid" if is_continuous and is_current_edge else "invalid"
    reasons = []
    if not is_continuous:
        reasons.append("缺少上一章有效状态检查点")
    if not is_current_edge:
        reasons.append("项目已存在后续分析状态，不能证明本章历史切面")

    snapshot = await capture_project_state(
        db,
        project_id=chapter.project_id,
        chapter_number=chapter.chapter_number,
    )
    config_version = await db.scalar(select(ProjectCreationConfig.config_version).where(
        ProjectCreationConfig.project_id == chapter.project_id,
    ))
    checkpoint = ProjectStateCheckpoint(
        id=str(uuid.uuid4()),
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        chapter_number=chapter.chapter_number,
        analysis_task_id=analysis_task.id,
        content_hash=analysis_task.content_hash,
        schema_version=snapshot.schema_version,
        status=status,
        invalid_reason="；".join(reasons) or None,
        config_version=config_version,
        state_json=snapshot.model_dump(mode="json"),
    )
    db.add(checkpoint)
    await db.flush()
    return checkpoint
