"""Transactional deep cloning of one project into an independent book."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import json
import uuid
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_task import AnalysisTask
from app.models.career import Career, CharacterCareer
from app.models.chapter import Chapter, ChapterStatus
from app.models.character import Character
from app.models.generation_history import GenerationHistory
from app.models.memory import PlotAnalysis, StoryMemory
from app.models.novel_pipeline import NovelPipeline, PipelineStage, PipelineStatus
from app.models.outline import Outline
from app.models.project import Project
from app.models.project_creation_config import ProjectCreationConfig
from app.models.project_default_style import ProjectDefaultStyle
from app.models.project_state_checkpoint import ProjectStateCheckpoint
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.schemas.project_clone import ProjectCloneCounts, ProjectCloneRequest, ProjectCloneResponse
from app.schemas.project_state_checkpoint import ProjectStateSnapshotV1
from app.services.chapter_lifecycle_service import analysis_task_matches_content, chapter_content_hash
from app.services.project_state_checkpoint_service import restore_project_state


TIMESTAMP_COLUMNS = {"created_at", "updated_at"}


@dataclass
class CloneMaps:
    all_ids: dict[str, str] = field(default_factory=dict)
    outlines: dict[str, str] = field(default_factory=dict)
    chapters: dict[str, str] = field(default_factory=dict)
    careers: dict[str, str] = field(default_factory=dict)
    characters: dict[str, str] = field(default_factory=dict)
    character_careers: dict[str, str] = field(default_factory=dict)
    relationships: dict[str, str] = field(default_factory=dict)
    organizations: dict[str, str] = field(default_factory=dict)
    organization_members: dict[str, str] = field(default_factory=dict)
    memories: dict[str, str] = field(default_factory=dict)
    foreshadows: dict[str, str] = field(default_factory=dict)
    analysis_tasks: dict[str, str] = field(default_factory=dict)
    analyses: dict[str, str] = field(default_factory=dict)
    generation_history: dict[str, str] = field(default_factory=dict)
    state_checkpoints: dict[str, str] = field(default_factory=dict)

    def allocate(self, bucket: dict[str, str], source_id: str) -> str:
        if source_id not in bucket:
            bucket[source_id] = str(uuid.uuid4())
            self.all_ids[source_id] = bucket[source_id]
        return bucket[source_id]


def _column_values(instance: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    omitted = {"id", *TIMESTAMP_COLUMNS, *(exclude or set())}
    return {
        column.name: deepcopy(getattr(instance, column.name))
        for column in instance.__table__.columns
        if column.name not in omitted
    }


def _remap_value(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_remap_value(item, mapping) for item in value]
    if isinstance(value, dict):
        return {
            mapping.get(str(key), key): _remap_value(item, mapping)
            for key, item in value.items()
        }
    return value


def _remap_text_json(value: Any, mapping: dict[str, str]) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return value
    return json.dumps(_remap_value(decoded, mapping), ensure_ascii=False)


def _new_model(model, source: Any, *, new_id: str | None = None, overrides: dict[str, Any] | None = None):
    values = _column_values(source)
    if overrides:
        values.update(overrides)
    if new_id is not None:
        values["id"] = new_id
    return model(**values)


async def _locked_rows(db: AsyncSession, model, condition, *order_by) -> list[Any]:
    statement = select(model).where(condition).with_for_update()
    if order_by:
        statement = statement.order_by(*order_by)
    return list((await db.scalars(statement)).all())


def _remap_snapshot(
    snapshot: ProjectStateSnapshotV1,
    *,
    target_project_id: str,
    maps: CloneMaps,
) -> ProjectStateSnapshotV1:
    values = snapshot.model_dump(mode="python")
    values = _remap_value(values, maps.all_ids)
    for field_name in (
        "characters",
        "relationships",
        "organizations",
        "careers",
        "foreshadows",
        "story_memories",
    ):
        for entity in values[field_name]:
            entity["data"]["project_id"] = target_project_id
    for entity in values["story_memories"]:
        entity["data"]["vector_id"] = entity["id"]
    return ProjectStateSnapshotV1.model_validate(values)


def _allocate_snapshot_ids(maps: CloneMaps, snapshots: Iterable[ProjectStateSnapshotV1]) -> None:
    buckets = {
        "characters": maps.characters,
        "relationships": maps.relationships,
        "organizations": maps.organizations,
        "organization_members": maps.organization_members,
        "careers": maps.careers,
        "character_careers": maps.character_careers,
        "foreshadows": maps.foreshadows,
        "story_memories": maps.memories,
    }
    for snapshot in snapshots:
        for field_name, bucket in buckets.items():
            for entity in getattr(snapshot, field_name):
                maps.allocate(bucket, entity.id)


async def _validated_checkpoint_chain(
    db: AsyncSession,
    *,
    source: Project,
    checkpoint_id: str,
    chapters_by_number: dict[int, Chapter],
) -> tuple[ProjectStateCheckpoint, list[ProjectStateCheckpoint], list[ProjectStateSnapshotV1]]:
    requested = await db.scalar(
        select(ProjectStateCheckpoint)
        .where(
            ProjectStateCheckpoint.id == checkpoint_id,
            ProjectStateCheckpoint.project_id == source.id,
            ProjectStateCheckpoint.status == "valid",
        )
        .with_for_update()
    )
    if requested is None:
        raise ValueError("所选状态节点不存在、已失效或不属于源书")

    chain = list((await db.scalars(
        select(ProjectStateCheckpoint)
        .where(
            ProjectStateCheckpoint.project_id == source.id,
            ProjectStateCheckpoint.chapter_number <= requested.chapter_number,
            ProjectStateCheckpoint.status == "valid",
        )
        .order_by(ProjectStateCheckpoint.chapter_number)
        .with_for_update()
    )).all())
    by_number = {item.chapter_number: item for item in chain}
    expected_numbers = list(range(1, requested.chapter_number + 1))
    if sorted(by_number) != expected_numbers or len(chain) != len(expected_numbers):
        raise ValueError("所选节点之前缺少连续有效状态节点，暂不能安全继承")

    ordered = [by_number[number] for number in expected_numbers]
    snapshots = []
    for item in ordered:
        chapter = chapters_by_number.get(item.chapter_number)
        if chapter is None or item.chapter_id != chapter.id:
            raise ValueError(f"第{item.chapter_number}章状态节点与当前章节不匹配")
        if not item.analysis_task_id:
            raise ValueError(f"第{item.chapter_number}章状态节点缺少正式分析任务")
        if item.content_hash != chapter_content_hash(chapter.content):
            raise ValueError(f"第{item.chapter_number}章状态节点正文版本无效")
        snapshot = ProjectStateSnapshotV1.model_validate(item.state_json)
        if snapshot.chapter_number != item.chapter_number:
            raise ValueError(f"第{item.chapter_number}章状态节点快照编号不匹配")
        snapshots.append(snapshot)
    return requested, ordered, snapshots


async def _preallocate_settings_ids(
    db: AsyncSession,
    *,
    source_project_id: str,
    maps: CloneMaps,
) -> None:
    careers = await _locked_rows(db, Career, Career.project_id == source_project_id, Career.id)
    characters = await _locked_rows(db, Character, Character.project_id == source_project_id, Character.id)
    character_ids = [item.id for item in characters]
    character_careers = (
        await _locked_rows(db, CharacterCareer, CharacterCareer.character_id.in_(character_ids), CharacterCareer.id)
        if character_ids else []
    )
    relationships = await _locked_rows(
        db, CharacterRelationship, CharacterRelationship.project_id == source_project_id, CharacterRelationship.id
    )
    organizations = await _locked_rows(db, Organization, Organization.project_id == source_project_id, Organization.id)
    organization_ids = [item.id for item in organizations]
    members = (
        await _locked_rows(db, OrganizationMember, OrganizationMember.organization_id.in_(organization_ids), OrganizationMember.id)
        if organization_ids else []
    )
    for items, bucket in (
        (careers, maps.careers),
        (characters, maps.characters),
        (character_careers, maps.character_careers),
        (relationships, maps.relationships),
        (organizations, maps.organizations),
        (members, maps.organization_members),
    ):
        for item in items:
            maps.allocate(bucket, item.id)


async def _copy_project_shell(
    db: AsyncSession,
    *,
    source: Project,
    title: str,
    inherited_words: int,
) -> Project:
    values = _column_values(source, exclude={"user_id", "title", "current_words", "status"})
    values.update(
        user_id=source.user_id,
        title=title,
        current_words=inherited_words,
        status="planning",
        cover_error=None,
    )
    if source.cover_status != "ready" or not source.cover_image_url:
        values.update(
            cover_image_url=None,
            cover_prompt=None,
            cover_status="none",
            cover_updated_at=None,
        )
    target = Project(id=str(uuid.uuid4()), **values)
    db.add(target)
    await db.flush()
    return target


async def _copy_project_configuration(
    db: AsyncSession,
    *,
    source_project_id: str,
    target_project_id: str,
    maps: CloneMaps,
) -> None:
    config = await db.scalar(select(ProjectCreationConfig).where(
        ProjectCreationConfig.project_id == source_project_id
    ).with_for_update())
    if config is not None:
        db.add(ProjectCreationConfig(
            project_id=target_project_id,
            config_version=config.config_version,
            config=_remap_value(deepcopy(config.config), maps.all_ids),
        ))
    default_style = await db.scalar(select(ProjectDefaultStyle).where(
        ProjectDefaultStyle.project_id == source_project_id
    ).with_for_update())
    if default_style is not None:
        db.add(ProjectDefaultStyle(
            project_id=target_project_id,
            style_id=default_style.style_id,
        ))


async def _copy_structure(
    db: AsyncSession,
    *,
    source: Project,
    target: Project,
    maps: CloneMaps,
    inherit_through: int | None,
) -> tuple[list[Chapter], dict[int, Chapter], ProjectCloneCounts]:
    outlines = await _locked_rows(db, Outline, Outline.project_id == source.id, Outline.order_index)
    chapters = await _locked_rows(db, Chapter, Chapter.project_id == source.id, Chapter.chapter_number, Chapter.sub_index)
    for item in outlines:
        maps.allocate(maps.outlines, item.id)
    for item in chapters:
        maps.allocate(maps.chapters, item.id)

    for item in outlines:
        values = _column_values(item, exclude={"project_id", "structure"})
        values.update(
            id=maps.outlines[item.id],
            project_id=target.id,
            structure=_remap_text_json(item.structure, maps.all_ids),
        )
        db.add(Outline(**values))
    await db.flush()

    target_chapters = []
    by_number = {}
    for item in chapters:
        inherited = inherit_through is not None and item.chapter_number <= inherit_through
        values = _column_values(
            item,
            exclude={"project_id", "outline_id", "expansion_plan", "content", "summary", "word_count", "status"},
        )
        target_chapter = Chapter(
            id=maps.chapters[item.id],
            project_id=target.id,
            outline_id=maps.outlines.get(item.outline_id) if item.outline_id else None,
            expansion_plan=_remap_text_json(item.expansion_plan, maps.all_ids),
            content=item.content if inherited else None,
            summary=item.summary if inherited else None,
            word_count=(item.word_count or len(item.content or "")) if inherited else 0,
            status=ChapterStatus.COMPLETED if inherited else ChapterStatus.DRAFT,
            **values,
        )
        db.add(target_chapter)
        target_chapters.append(target_chapter)
        by_number[item.chapter_number] = target_chapter
    await db.flush()
    return target_chapters, by_number, ProjectCloneCounts(
        outlines=len(outlines),
        chapters=len(chapters),
    )


async def _copy_settings_state(
    db: AsyncSession,
    *,
    source: Project,
    target: Project,
    maps: CloneMaps,
) -> ProjectCloneCounts:
    careers = await _locked_rows(db, Career, Career.project_id == source.id, Career.id)
    characters = await _locked_rows(db, Character, Character.project_id == source.id, Character.id)
    character_ids = [item.id for item in characters]
    character_careers = (
        await _locked_rows(db, CharacterCareer, CharacterCareer.character_id.in_(character_ids), CharacterCareer.id)
        if character_ids else []
    )
    relationships = await _locked_rows(db, CharacterRelationship, CharacterRelationship.project_id == source.id, CharacterRelationship.id)
    organizations = await _locked_rows(db, Organization, Organization.project_id == source.id, Organization.id)
    organization_ids = [item.id for item in organizations]
    members = (
        await _locked_rows(db, OrganizationMember, OrganizationMember.organization_id.in_(organization_ids), OrganizationMember.id)
        if organization_ids else []
    )

    for item in careers:
        maps.allocate(maps.careers, item.id)
    for item in characters:
        maps.allocate(maps.characters, item.id)
    for item in character_careers:
        maps.allocate(maps.character_careers, item.id)
    for item in relationships:
        maps.allocate(maps.relationships, item.id)
    for item in organizations:
        maps.allocate(maps.organizations, item.id)
    for item in members:
        maps.allocate(maps.organization_members, item.id)

    for item in careers:
        db.add(_new_model(Career, item, new_id=maps.careers[item.id], overrides={"project_id": target.id}))
    await db.flush()

    for item in characters:
        values = _column_values(item, exclude={"project_id", "relationships", "organization_members", "sub_careers"})
        values.update(
            id=maps.characters[item.id],
            project_id=target.id,
            relationships=_remap_text_json(item.relationships, maps.all_ids),
            organization_members=_remap_text_json(item.organization_members, maps.all_ids),
            sub_careers=_remap_text_json(item.sub_careers, maps.all_ids),
            main_career_id=maps.careers.get(item.main_career_id),
            main_career_stage=1 if item.main_career_id else None,
            status="active",
            status_changed_chapter=None,
            current_state=None,
            state_updated_chapter=None,
        )
        db.add(Character(**values))
    await db.flush()

    for item in character_careers:
        db.add(_new_model(CharacterCareer, item, new_id=maps.character_careers[item.id], overrides={
            "character_id": maps.characters[item.character_id],
            "career_id": maps.careers[item.career_id],
            "current_stage": 1,
            "stage_progress": 0,
            "reached_current_stage_at": None,
        }))
    for item in relationships:
        db.add(_new_model(CharacterRelationship, item, new_id=maps.relationships[item.id], overrides={
            "project_id": target.id,
            "character_from_id": maps.characters[item.character_from_id],
            "character_to_id": maps.characters[item.character_to_id],
            "intimacy_level": 50,
            "status": "active",
            "ended_at": None,
        }))
    await db.flush()

    target_organizations = []
    for item in organizations:
        target_organization = _new_model(Organization, item, new_id=maps.organizations[item.id], overrides={
            "project_id": target.id,
            "character_id": maps.characters[item.character_id],
            "parent_org_id": None,
            "power_level": 50,
            "member_count": sum(member.organization_id == item.id for member in members),
        })
        db.add(target_organization)
        target_organizations.append((target_organization, item.parent_org_id))
    await db.flush()
    for target_organization, source_parent_id in target_organizations:
        target_organization.parent_org_id = maps.organizations.get(source_parent_id)
    await db.flush()

    for item in members:
        db.add(_new_model(OrganizationMember, item, new_id=maps.organization_members[item.id], overrides={
            "organization_id": maps.organizations[item.organization_id],
            "character_id": maps.characters[item.character_id],
            "status": "active",
            "left_at": None,
            "loyalty": 50,
            "contribution": 0,
        }))
    await db.flush()
    return ProjectCloneCounts(
        careers=len(careers),
        characters=len(characters),
        character_careers=len(character_careers),
        relationships=len(relationships),
        organizations=len(organizations),
        organization_members=len(members),
    )


def _merge_counts(base: ProjectCloneCounts, extra: ProjectCloneCounts) -> ProjectCloneCounts:
    values = base.model_dump()
    for key, value in extra.model_dump().items():
        values[key] += value
    return ProjectCloneCounts(**values)


async def _copy_inherited_process(
    db: AsyncSession,
    *,
    source: Project,
    target: Project,
    maps: CloneMaps,
    source_chapters: dict[int, Chapter],
    chain: list[ProjectStateCheckpoint],
    snapshots: list[ProjectStateSnapshotV1],
) -> tuple[ProjectCloneCounts, list[StoryMemory]]:
    source_tasks = list((await db.scalars(
        select(AnalysisTask).where(AnalysisTask.id.in_([item.analysis_task_id for item in chain])).with_for_update()
    )).all())
    tasks_by_id = {item.id: item for item in source_tasks}
    for checkpoint in chain:
        task = tasks_by_id.get(checkpoint.analysis_task_id)
        if task is not None:
            maps.allocate(maps.analysis_tasks, task.id)

    final_snapshot = _remap_snapshot(snapshots[-1], target_project_id=target.id, maps=maps)
    await restore_project_state(db, project_id=target.id, snapshot=final_snapshot)

    for checkpoint in chain:
        task = tasks_by_id.get(checkpoint.analysis_task_id)
        chapter = source_chapters[checkpoint.chapter_number]
        if (
            task is None
            or task.status != "completed"
            or task.materialized_at is None
            or not analysis_task_matches_content(task, chapter)
        ):
            raise ValueError(f"第{checkpoint.chapter_number}章缺少与当前正文一致的完整分析")
        db.add(AnalysisTask(
            id=maps.analysis_tasks[task.id],
            chapter_id=maps.chapters[task.chapter_id],
            user_id=target.user_id,
            project_id=target.id,
            content_hash=task.content_hash,
            status="completed",
            progress=100,
            error_message=None,
            started_at=task.started_at,
            completed_at=task.completed_at or datetime.now(),
            materialized_at=task.materialized_at or task.completed_at or datetime.now(),
        ))
    await db.flush()

    inherited_source_ids = [source_chapters[number].id for number in range(1, chain[-1].chapter_number + 1)]
    analyses = list((await db.scalars(
        select(PlotAnalysis).where(PlotAnalysis.chapter_id.in_(inherited_source_ids)).with_for_update()
    )).all())
    if {item.chapter_id for item in analyses} != set(inherited_source_ids):
        raise ValueError("部分继承章节缺少正式分析结果")
    for item in analyses:
        maps.allocate(maps.analyses, item.id)
        values = _remap_value(_column_values(item, exclude={"project_id", "chapter_id"}), maps.all_ids)
        db.add(PlotAnalysis(
            id=maps.analyses[item.id],
            project_id=target.id,
            chapter_id=maps.chapters[item.chapter_id],
            **values,
        ))

    histories = list((await db.scalars(
        select(GenerationHistory).where(
            GenerationHistory.project_id == source.id,
            GenerationHistory.chapter_id.in_(inherited_source_ids),
        ).with_for_update()
    )).all())
    for item in histories:
        maps.allocate(maps.generation_history, item.id)
        db.add(_new_model(GenerationHistory, item, new_id=maps.generation_history[item.id], overrides={
            "project_id": target.id,
            "chapter_id": maps.chapters.get(item.chapter_id),
        }))
    await db.flush()

    for checkpoint, snapshot in zip(chain, snapshots):
        maps.allocate(maps.state_checkpoints, checkpoint.id)
        remapped = _remap_snapshot(snapshot, target_project_id=target.id, maps=maps)
        db.add(ProjectStateCheckpoint(
            id=maps.state_checkpoints[checkpoint.id],
            project_id=target.id,
            chapter_id=maps.chapters[checkpoint.chapter_id],
            chapter_number=checkpoint.chapter_number,
            analysis_task_id=maps.analysis_tasks[checkpoint.analysis_task_id],
            content_hash=checkpoint.content_hash,
            schema_version=checkpoint.schema_version,
            status="valid",
            invalid_reason=None,
            config_version=checkpoint.config_version,
            state_json=remapped.model_dump(mode="json"),
        ))
    await db.flush()
    target_memories = list((await db.scalars(
        select(StoryMemory).where(StoryMemory.project_id == target.id).order_by(StoryMemory.id)
    )).all())
    return ProjectCloneCounts(
        careers=len(final_snapshot.careers),
        characters=len(final_snapshot.characters),
        character_careers=len(final_snapshot.character_careers),
        relationships=len(final_snapshot.relationships),
        organizations=len(final_snapshot.organizations),
        organization_members=len(final_snapshot.organization_members),
        analyses=len(analyses),
        memories=len(final_snapshot.story_memories),
        foreshadows=len(final_snapshot.foreshadows),
        generation_history=len(histories),
        state_checkpoints=len(chain),
    ), target_memories


async def _create_idle_pipeline(
    db: AsyncSession,
    *,
    source_project_id: str,
    target_project_id: str,
    inherited_chapters: int,
    maps: CloneMaps,
) -> None:
    source_pipeline = await db.scalar(select(NovelPipeline).where(
        NovelPipeline.project_id == source_project_id
    ).with_for_update())
    db.add(NovelPipeline(
        id=str(uuid.uuid4()),
        project_id=target_project_id,
        status=PipelineStatus.IDLE,
        current_stage=PipelineStage.IDLE,
        current_outline_id=None,
        chapter_count=inherited_chapters,
        current_checkpoint_id=None,
        config_snapshot=(
            _remap_value(deepcopy(source_pipeline.config_snapshot), maps.all_ids)
            if source_pipeline else {}
        ),
        progress_json={},
        checkpoint_history=[],
        budget_used_tokens=0,
        budget_used_amount_cents=0,
        last_error=None,
    ))


def _vector_records(memories: list[StoryMemory]) -> list[dict[str, Any]]:
    return [{
        "id": item.id,
        "content": item.content,
        "type": item.memory_type,
        "metadata": {
            "chapter_id": item.chapter_id,
            "chapter_number": item.story_timeline,
            "importance_score": item.importance_score,
            "tags": item.tags or [],
            "title": item.title or "",
            "is_foreshadow": item.is_foreshadow or 0,
            "related_characters": item.related_characters or [],
        },
    } for item in memories]


async def clone_project(
    db: AsyncSession,
    *,
    source_project_id: str,
    user_id: str,
    request: ProjectCloneRequest,
    memory_service: Any,
) -> ProjectCloneResponse:
    """Create an independent book, rolling back SQL and target vectors together."""
    target_id: str | None = None
    try:
        source = await db.scalar(
            select(Project)
            .where(Project.id == source_project_id, Project.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if source is None:
            raise ValueError("源项目不存在或无权访问")

        source_chapter_rows = await _locked_rows(
            db, Chapter, Chapter.project_id == source.id, Chapter.chapter_number, Chapter.sub_index
        )
        source_chapters = {item.chapter_number: item for item in source_chapter_rows}
        chain: list[ProjectStateCheckpoint] = []
        snapshots: list[ProjectStateSnapshotV1] = []
        inherit_through = None
        if request.mode == "inherit_checkpoint":
            requested, chain, snapshots = await _validated_checkpoint_chain(
                db,
                source=source,
                checkpoint_id=request.checkpoint_id or "",
                chapters_by_number=source_chapters,
            )
            inherit_through = requested.chapter_number

        inherited_words = sum(
            item.word_count or len(item.content or "")
            for item in source_chapter_rows
            if inherit_through is not None and item.chapter_number <= inherit_through
        )
        target = await _copy_project_shell(
            db,
            source=source,
            title=request.title,
            inherited_words=inherited_words,
        )
        target_id = target.id
        maps = CloneMaps(all_ids={source.id: target.id})
        source_outlines = await _locked_rows(
            db, Outline, Outline.project_id == source.id, Outline.order_index
        )
        for item in source_outlines:
            maps.allocate(maps.outlines, item.id)
        for item in source_chapter_rows:
            maps.allocate(maps.chapters, item.id)
        if request.mode == "settings_only":
            await _preallocate_settings_ids(
                db,
                source_project_id=source.id,
                maps=maps,
            )
        else:
            _allocate_snapshot_ids(maps, snapshots)
        await _copy_project_configuration(
            db,
            source_project_id=source.id,
            target_project_id=target.id,
            maps=maps,
        )
        _, _, counts = await _copy_structure(
            db,
            source=source,
            target=target,
            maps=maps,
            inherit_through=inherit_through,
        )

        target_memories: list[StoryMemory] = []
        if request.mode == "settings_only":
            counts = _merge_counts(counts, await _copy_settings_state(
                db,
                source=source,
                target=target,
                maps=maps,
            ))
        else:
            process_counts, target_memories = await _copy_inherited_process(
                db,
                source=source,
                target=target,
                maps=maps,
                source_chapters=source_chapters,
                chain=chain,
                snapshots=snapshots,
            )
            counts = _merge_counts(counts, process_counts)

        await _create_idle_pipeline(
            db,
            source_project_id=source.id,
            target_project_id=target.id,
            inherited_chapters=inherit_through or 0,
            maps=maps,
        )
        await db.flush()

        if target_memories:
            records = _vector_records(target_memories)
            inserted = await memory_service.batch_add_memories(user_id, target.id, records)
            if inserted != len(records):
                raise RuntimeError("副本向量记忆重建不完整")

        await db.commit()
        return ProjectCloneResponse(
            project_id=target.id,
            source_project_id=source.id,
            mode=request.mode,
            inherited_through_chapter=inherit_through,
            counts=counts,
        )
    except Exception:
        await db.rollback()
        if target_id:
            await memory_service.delete_project_memories(user_id, target_id)
        raise
