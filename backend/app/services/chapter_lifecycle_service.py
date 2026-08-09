"""Shared lifecycle rules for formal chapter content and analysis tasks."""

from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_task import AnalysisTask
from app.models.chapter import Chapter
from app.models.memory import PlotAnalysis


def chapter_content_hash(content: Optional[str]) -> str:
    """Return a stable digest for the exact formal chapter content."""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def create_pending_analysis_task(
    *,
    chapter: Chapter,
    user_id: str,
) -> AnalysisTask:
    """Create an analysis task bound to the chapter's current formal content."""
    return AnalysisTask(
        chapter_id=chapter.id,
        user_id=user_id,
        project_id=chapter.project_id,
        content_hash=chapter_content_hash(chapter.content),
        status="pending",
        progress=0,
    )


def analysis_task_matches_content(task: AnalysisTask, chapter: Chapter) -> bool:
    """Return whether a task is bound to the chapter's current content."""
    return bool(
        task.content_hash
        and task.content_hash == chapter_content_hash(chapter.content)
    )


async def check_previous_analysis_ready(
    db: AsyncSession,
    chapter: Chapter,
) -> tuple[bool, str]:
    """Require the previous chapter's current content to be fully analyzed."""
    if chapter.chapter_number <= 1:
        return True, ""

    prev_chapter = await db.scalar(
        select(Chapter)
        .where(Chapter.project_id == chapter.project_id)
        .where(Chapter.chapter_number < chapter.chapter_number)
        .order_by(Chapter.chapter_number.desc())
        .limit(1)
    )
    if not prev_chapter or not prev_chapter.content:
        return True, ""

    latest_task = await db.scalar(
        select(AnalysisTask)
        .where(AnalysisTask.chapter_id == prev_chapter.id)
        .order_by(AnalysisTask.created_at.desc())
        .limit(1)
    )

    if not latest_task:
        return False, (
            f"上一章（第{prev_chapter.chapter_number}章）还没有分析记录，"
            "无法保证角色状态/记忆/伏笔连贯。可在章节管理中对上一章点「分析」，"
            "或在生成时勾选「跳过上一章分析检查」继续"
        )

    if latest_task.status == "running" or latest_task.status == "pending":
        return False, (
            f"上一章（第{prev_chapter.chapter_number}章）的分析正在进行中，"
            "请等待其完成后再生成下一章；若等待过久，可在章节管理中重新分析该章"
        )

    if latest_task.status == "failed":
        return False, (
            f"上一章（第{prev_chapter.chapter_number}章）的分析失败了，"
            "请在章节管理中对上一章点「重新分析」；"
            "或在生成时勾选「跳过上一章分析检查」继续"
        )

    ready = bool(
        latest_task.status == "completed"
        and latest_task.materialized_at is not None
        and analysis_task_matches_content(latest_task, prev_chapter)
    )

    # Tasks created before content hashes were introduced remain valid only when
    # their persisted analysis is not older than the current chapter row.
    if latest_task and latest_task.status == "completed" and not latest_task.content_hash:
        analysis = await db.scalar(
            select(PlotAnalysis).where(PlotAnalysis.chapter_id == prev_chapter.id)
        )
        ready = bool(
            analysis
            and analysis.created_at
            and prev_chapter.updated_at
            and analysis.created_at >= prev_chapter.updated_at
        )

    if ready:
        return True, ""

    return False, (
        f"上一章（第{prev_chapter.chapter_number}章）的内容自上次分析后有变更"
        "（或分析未完成物化），请在章节管理中对上一章重新分析，"
        "或在生成时勾选「跳过上一章分析检查」继续"
    )
