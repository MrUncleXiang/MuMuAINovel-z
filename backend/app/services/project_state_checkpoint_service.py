"""Capture and validate chapter-bound project state checkpoints."""

from datetime import date, datetime
from typing import Any
import uuid

from sqlalchemy import delete, select, update
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
from app.services.chapter_lifecycle_service import analysis_task_matches_content


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
RESTORE_DELETE_ORDER = (
    OrganizationMember,
    CharacterCareer,
    CharacterRelationship,
    Organization,
    Character,
    Career,
    Foreshadow,
    StoryMemory,
)


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
        if previous is not None:
            previous_chapter = await db.scalar(
                select(Chapter).where(Chapter.id == previous.chapter_id)
            )
            if (
                previous_chapter is None
                or previous.content_hash != analysis_task_hash(previous_chapter)
            ):
                previous.status = "invalid"
                previous.invalid_reason = "上一章检查点正文版本已变化"
                previous.invalidated_at = datetime.now()
                previous = None
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


async def invalidate_checkpoints_from_chapter(
    db: AsyncSession,
    *,
    project_id: str,
    chapter_number: int,
    reason: str,
) -> int:
    """Invalidate the changed chapter boundary and every dependent boundary."""
    result = await db.execute(
        update(ProjectStateCheckpoint)
        .where(
            ProjectStateCheckpoint.project_id == project_id,
            ProjectStateCheckpoint.chapter_number >= chapter_number,
            ProjectStateCheckpoint.status == "valid",
        )
        .values(
            status="invalid",
            invalid_reason=reason[:1000],
            invalidated_at=datetime.now(),
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def restore_project_state(
    db: AsyncSession,
    *,
    project_id: str,
    snapshot: ProjectStateSnapshotV1,
) -> None:
    """Replace mutable project entities with one previously captured state."""
    for model in RESTORE_DELETE_ORDER:
        if model is OrganizationMember:
            statement = delete(model).where(model.organization_id.in_(
                select(Organization.id).where(Organization.project_id == project_id)
            ))
        elif model is CharacterCareer:
            statement = delete(model).where(model.character_id.in_(
                select(Character.id).where(Character.project_id == project_id)
            ))
        else:
            statement = delete(model).where(model.project_id == project_id)
        await db.execute(statement)

    field_models = dict(SNAPSHOT_MODELS)
    restore_order = (
        "careers",
        "characters",
        "relationships",
        "organizations",
        "organization_members",
        "character_careers",
        "foreshadows",
        "story_memories",
    )
    pending_parent_links: list[tuple[Organization, str]] = []
    for field_name in restore_order:
        model = field_models[field_name]
        for entity in getattr(snapshot, field_name):
            data = dict(entity.data)
            if model is Organization and data.get("parent_org_id"):
                parent_id = data.pop("parent_org_id")
                instance = model(id=entity.id, **data, parent_org_id=None)
                pending_parent_links.append((instance, parent_id))
            else:
                instance = model(id=entity.id, **data)
            db.add(instance)
        await db.flush()
    for organization, parent_id in pending_parent_links:
        organization.parent_org_id = parent_id
    await db.flush()


async def prepare_project_state_for_chapter_rewrite(
    db: AsyncSession,
    *,
    user_id: str,
    chapter: Chapter,
    memory_service: Any,
) -> ProjectStateCheckpoint:
    """Restore X-1 and supersede derived state from X onward before a rewrite."""
    if chapter.chapter_number <= 1:
        raise ValueError("第1章缺少写作前状态检查点，暂不能安全覆盖")
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
    if previous is None:
        raise ValueError(
            f"缺少第{chapter.chapter_number - 1}章有效状态检查点，暂不能安全覆盖"
        )

    affected_chapters = list((await db.scalars(
        select(Chapter).where(
            Chapter.project_id == chapter.project_id,
            Chapter.chapter_number >= chapter.chapter_number,
        )
    )).all())
    for affected in affected_chapters:
        deleted = await memory_service.delete_chapter_memories(
            user_id=user_id,
            project_id=chapter.project_id,
            chapter_id=affected.id,
        )
        if not deleted:
            raise RuntimeError(f"第{affected.chapter_number}章向量记忆清理失败")

    snapshot = ProjectStateSnapshotV1.model_validate(previous.state_json)
    await restore_project_state(db, project_id=chapter.project_id, snapshot=snapshot)
    affected_ids = [affected.id for affected in affected_chapters]
    if affected_ids:
        from app.models.memory import PlotAnalysis

        await db.execute(delete(PlotAnalysis).where(PlotAnalysis.chapter_id.in_(affected_ids)))
        await db.execute(
            update(AnalysisTask)
            .where(
                AnalysisTask.chapter_id.in_(affected_ids),
                AnalysisTask.materialized_at.is_not(None),
            )
            .values(
                status="superseded",
                error_message="前序章节正文已修改，需要按顺序重新分析",
                materialized_at=None,
            )
        )
    await invalidate_checkpoints_from_chapter(
        db,
        project_id=chapter.project_id,
        chapter_number=chapter.chapter_number,
        reason=f"第{chapter.chapter_number}章正文准备重建",
    )
    return previous


async def list_valid_project_checkpoints(
    db: AsyncSession,
    *,
    project_id: str,
) -> list[ProjectStateCheckpoint]:
    checkpoints = list((await db.scalars(
        select(ProjectStateCheckpoint)
        .where(
            ProjectStateCheckpoint.project_id == project_id,
            ProjectStateCheckpoint.status == "valid",
        )
        .order_by(
            ProjectStateCheckpoint.chapter_number,
            ProjectStateCheckpoint.created_at,
        )
    )).all())
    if not checkpoints:
        return []
    chapter_ids = [checkpoint.chapter_id for checkpoint in checkpoints]
    chapters = list((await db.scalars(
        select(Chapter).where(Chapter.id.in_(chapter_ids))
    )).all())
    chapters_by_id = {chapter.id: chapter for chapter in chapters}
    valid = []
    for checkpoint in checkpoints:
        chapter = chapters_by_id.get(checkpoint.chapter_id)
        if chapter is None or checkpoint.content_hash != analysis_task_hash(chapter):
            checkpoint.status = "invalid"
            checkpoint.invalid_reason = "检查点正文版本与当前正式正文不一致"
            checkpoint.invalidated_at = datetime.now()
            continue
        valid.append(checkpoint)
    if len(valid) != len(checkpoints):
        await db.commit()
    return valid


def analysis_task_hash(chapter: Chapter) -> str:
    from app.services.chapter_lifecycle_service import chapter_content_hash

    return chapter_content_hash(chapter.content)


async def register_latest_reliable_checkpoint(
    db: AsyncSession,
    *,
    project_id: str,
) -> ProjectStateCheckpoint:
    """Register only the latest legacy boundary that current evidence proves."""
    chapters = list((await db.scalars(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_number, Chapter.sub_index)
    )).all())
    completed = [chapter for chapter in chapters if (chapter.content or "").strip()]
    if not completed:
        raise ValueError("项目没有可登记的正式章节")
    numbers = [chapter.chapter_number for chapter in completed]
    if numbers != list(range(1, numbers[-1] + 1)):
        raise ValueError("章节正文不连续，无法证明最新状态边界")

    latest_tasks: list[AnalysisTask] = []
    for chapter in completed:
        task = await db.scalar(
            select(AnalysisTask)
            .where(AnalysisTask.chapter_id == chapter.id)
            .order_by(AnalysisTask.created_at.desc())
            .limit(1)
        )
        if (
            task is None
            or task.status != "completed"
            or task.materialized_at is None
            or not analysis_task_matches_content(task, chapter)
        ):
            raise ValueError(f"第{chapter.chapter_number}章缺少与当前正文一致的完整分析")
        latest_tasks.append(task)

    latest_chapter = completed[-1]
    latest_task = latest_tasks[-1]
    existing = await db.scalar(select(ProjectStateCheckpoint).where(
        ProjectStateCheckpoint.project_id == project_id,
        ProjectStateCheckpoint.chapter_id == latest_chapter.id,
        ProjectStateCheckpoint.content_hash == latest_task.content_hash,
        ProjectStateCheckpoint.status == "valid",
    ))
    if existing is not None:
        return existing

    snapshot = await capture_project_state(
        db,
        project_id=project_id,
        chapter_number=latest_chapter.chapter_number,
    )
    config_version = await db.scalar(select(ProjectCreationConfig.config_version).where(
        ProjectCreationConfig.project_id == project_id,
    ))
    checkpoint = ProjectStateCheckpoint(
        id=str(uuid.uuid4()),
        project_id=project_id,
        chapter_id=latest_chapter.id,
        chapter_number=latest_chapter.chapter_number,
        analysis_task_id=latest_task.id,
        content_hash=latest_task.content_hash,
        schema_version=snapshot.schema_version,
        status="valid",
        config_version=config_version,
        state_json=snapshot.model_dump(mode="json"),
    )
    db.add(checkpoint)
    await db.commit()
    await db.refresh(checkpoint)
    return checkpoint
