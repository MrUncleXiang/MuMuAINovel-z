"""Transactional persistence for content becoming a formal chapter version."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_task import AnalysisTask
from app.models.chapter import Chapter
from app.models.generation_history import GenerationHistory
from app.models.project import Project
from app.services.chapter_lifecycle_service import (
    chapter_content_hash,
    create_pending_analysis_task,
)


class FormalChapterConflictError(ValueError):
    """The formal chapter changed or cannot be replaced safely."""


@dataclass(frozen=True)
class FormalChapterResult:
    chapter: Chapter
    analysis_task: AnalysisTask


def build_lightweight_chapter_summary(content: str, max_length: int = 300) -> str:
    normalized = " ".join((content or "").split())
    return normalized[:max_length]


async def persist_formal_chapter_content(
    *,
    db: AsyncSession,
    chapter_id: str,
    user_id: str,
    content: str,
    prompt: str,
    model: str,
    foreshadow_service,
    expected_content_hash: str | None = None,
) -> FormalChapterResult:
    """Persist content, history, planned foreshadows and analysis task atomically."""
    chapter = await db.scalar(
        select(Chapter).where(Chapter.id == chapter_id).with_for_update()
    )
    if chapter is None:
        raise FormalChapterConflictError("章节不存在")
    if expected_content_hash and chapter_content_hash(chapter.content) != expected_content_hash:
        raise FormalChapterConflictError("章节正文在生成期间已被修改，请重新生成")

    new_hash = chapter_content_hash(content)
    if chapter.content and chapter_content_hash(chapter.content) != new_hash:
        materialized = await db.scalar(
            select(AnalysisTask.id)
            .where(
                AnalysisTask.chapter_id == chapter.id,
                AnalysisTask.materialized_at.is_not(None),
            )
            .limit(1)
        )
        if materialized:
            raise FormalChapterConflictError(
                "该章节已有正式分析，当前版本暂不能直接覆盖；请等待历史状态重建功能完成"
            )

    project = await db.scalar(
        select(Project).where(Project.id == chapter.project_id).with_for_update()
    )
    if project is None:
        raise FormalChapterConflictError("项目不存在")

    old_word_count = chapter.word_count or 0
    chapter.content = content
    chapter.word_count = len(content)
    chapter.status = "completed"
    chapter.summary = build_lightweight_chapter_summary(content)
    project.current_words = (project.current_words or 0) - old_word_count + chapter.word_count

    db.add(GenerationHistory(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        prompt=prompt,
        generated_content=content[:500],
        model=model,
    ))

    plant_result = await foreshadow_service.auto_plant_pending_foreshadows(
        db=db,
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        chapter_number=chapter.chapter_number,
        chapter_content=content,
        commit=False,
    )
    if plant_result.get("error"):
        raise RuntimeError("计划伏笔状态更新失败")

    analysis_task = create_pending_analysis_task(chapter=chapter, user_id=user_id)
    db.add(analysis_task)
    await db.commit()
    await db.refresh(chapter)
    await db.refresh(analysis_task)
    return FormalChapterResult(chapter=chapter, analysis_task=analysis_task)
