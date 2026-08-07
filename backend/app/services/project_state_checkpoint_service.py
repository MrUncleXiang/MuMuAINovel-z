"""Capture and validate chapter-bound project state checkpoints."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.career import Career, CharacterCareer
from app.models.character import Character
from app.models.foreshadow import Foreshadow
from app.models.memory import StoryMemory
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
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
