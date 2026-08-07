"""Atomic materialization of a validated chapter analysis result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_task import AnalysisTask
from app.models.chapter import Chapter
from app.models.memory import PlotAnalysis, StoryMemory
from app.services.career_update_service import CareerUpdateService
from app.services.character_state_update_service import CharacterStateUpdateService
from app.services.chapter_lifecycle_service import analysis_task_matches_content
from app.services.foreshadow_service import ForeshadowService


class StaleAnalysisError(ValueError):
    """The result no longer belongs to the chapter's formal content."""


@dataclass(frozen=True)
class AnalysisMaterializationResult:
    memory_count: int
    already_materialized: bool = False


def _analysis_values(analysis: dict[str, Any], report: str, word_count: int) -> dict[str, Any]:
    hooks = analysis.get("hooks", [])
    foreshadows = analysis.get("foreshadows", [])
    plot_points = analysis.get("plot_points", [])
    return {
        "plot_stage": analysis.get("plot_stage", "发展"),
        "conflict_level": analysis.get("conflict", {}).get("level", 0),
        "conflict_types": analysis.get("conflict", {}).get("types", []),
        "emotional_tone": analysis.get("emotional_arc", {}).get("primary_emotion", ""),
        "emotional_intensity": analysis.get("emotional_arc", {}).get("intensity", 0) / 10.0,
        "emotional_curve": analysis.get("emotional_arc"),
        "hooks": hooks,
        "hooks_count": len(hooks),
        "hooks_avg_strength": sum(item.get("strength", 0) for item in hooks) / max(len(hooks), 1),
        "foreshadows": foreshadows,
        "foreshadows_planted": sum(1 for item in foreshadows if item.get("type") == "planted"),
        "foreshadows_resolved": sum(1 for item in foreshadows if item.get("type") == "resolved"),
        "plot_points": plot_points,
        "plot_points_count": len(plot_points),
        "character_states": analysis.get("character_states", []),
        "scenes": analysis.get("scenes", []),
        "pacing": analysis.get("pacing", "moderate"),
        "overall_quality_score": analysis.get("scores", {}).get("overall", 0),
        "pacing_score": analysis.get("scores", {}).get("pacing", 0),
        "engagement_score": analysis.get("scores", {}).get("engagement", 0),
        "coherence_score": analysis.get("scores", {}).get("coherence", 0),
        "analysis_report": report,
        "suggestions": analysis.get("suggestions", []),
        "word_count": word_count,
        "dialogue_ratio": analysis.get("dialogue_ratio", 0),
        "description_ratio": analysis.get("description_ratio", 0),
    }


async def materialize_chapter_analysis(
    *,
    db: AsyncSession,
    user_id: str,
    chapter: Chapter,
    task: AnalysisTask,
    analysis: dict[str, Any],
    analyzer: Any,
    memory_service: Any,
    foreshadow_service: ForeshadowService,
) -> AnalysisMaterializationResult:
    """Apply every formal analysis side effect under one relational transaction."""
    locked_chapter = await db.scalar(
        select(Chapter).where(Chapter.id == chapter.id).with_for_update()
    )
    if locked_chapter is None:
        raise StaleAnalysisError("章节不存在")
    chapter = locked_chapter
    if not analysis_task_matches_content(task, chapter):
        raise StaleAnalysisError("分析结果对应的正文已经过期")

    prior_task = await db.scalar(
        select(AnalysisTask)
        .where(
            AnalysisTask.chapter_id == chapter.id,
            AnalysisTask.content_hash == task.content_hash,
            AnalysisTask.materialized_at.is_not(None),
            AnalysisTask.id != task.id,
        )
        .limit(1)
    )
    if prior_task:
        task.status = "completed"
        task.progress = 100
        task.error_message = None
        task.completed_at = datetime.now()
        task.materialized_at = task.completed_at
        await db.commit()
        return AnalysisMaterializationResult(memory_count=0, already_materialized=True)

    report = analyzer.generate_analysis_summary(analysis)
    values = _analysis_values(analysis, report, chapter.word_count or len(chapter.content or ""))
    plot_analysis = await db.scalar(
        select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter.id).with_for_update()
    )
    if plot_analysis is None:
        plot_analysis = PlotAnalysis(project_id=chapter.project_id, chapter_id=chapter.id)
        db.add(plot_analysis)
    for key, value in values.items():
        setattr(plot_analysis, key, value)

    await db.execute(delete(StoryMemory).where(StoryMemory.chapter_id == chapter.id))
    memories = analyzer.extract_memories_from_analysis(
        analysis=analysis,
        chapter_id=chapter.id,
        chapter_number=chapter.chapter_number,
        chapter_content=chapter.content or "",
        chapter_title=chapter.title or "",
    )
    vector_records: list[dict[str, Any]] = []
    for index, memory in enumerate(memories):
        memory_id = f"{chapter.id}_{memory['type']}_{index}"
        metadata = memory["metadata"]
        db.add(StoryMemory(
            id=memory_id,
            project_id=chapter.project_id,
            chapter_id=chapter.id,
            memory_type=memory["type"],
            content=memory["content"],
            title=memory["title"],
            importance_score=metadata.get("importance_score", 0.5),
            tags=metadata.get("tags", []),
            is_foreshadow=metadata.get("is_foreshadow", 0),
            story_timeline=chapter.chapter_number,
            chapter_position=metadata.get("text_position", -1),
            text_length=metadata.get("text_length", 0),
            related_characters=metadata.get("related_characters", []),
            related_locations=metadata.get("related_locations", []),
        ))
        vector_records.append({
            "id": memory_id,
            "content": memory["content"],
            "type": memory["type"],
            "metadata": metadata,
        })

    character_states = analysis.get("character_states", [])
    if character_states:
        await CareerUpdateService.update_careers_from_analysis(
            db=db,
            project_id=chapter.project_id,
            character_states=character_states,
            chapter_id=chapter.id,
            chapter_number=chapter.chapter_number,
            commit=False,
        )
        await CharacterStateUpdateService.update_from_analysis(
            db=db,
            project_id=chapter.project_id,
            character_states=character_states,
            chapter_id=chapter.id,
            chapter_number=chapter.chapter_number,
            commit=False,
        )

    organization_states = analysis.get("organization_states", [])
    if organization_states:
        await CharacterStateUpdateService.update_organization_states(
            db=db,
            project_id=chapter.project_id,
            organization_states=organization_states,
            chapter_number=chapter.chapter_number,
            commit=False,
        )

    await foreshadow_service.clean_chapter_analysis_foreshadows(
        db=db,
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        commit=False,
    )
    analysis_foreshadows = analysis.get("foreshadows", [])
    if analysis_foreshadows:
        foreshadow_result = await foreshadow_service.auto_update_from_analysis(
            db=db,
            project_id=chapter.project_id,
            chapter_id=chapter.id,
            chapter_number=chapter.chapter_number,
            analysis_foreshadows=analysis_foreshadows,
            commit=False,
        )
        if foreshadow_result.get("errors"):
            raise RuntimeError("伏笔状态更新失败")

    # Chroma is external to SQL. Replace its chapter slice before committing SQL;
    # a failure leaves the task retryable and the SQL transaction is rolled back.
    if not await memory_service.delete_chapter_memories(
        user_id=user_id,
        project_id=chapter.project_id,
        chapter_id=chapter.id,
    ):
        raise RuntimeError("旧向量记忆清理失败")
    if vector_records:
        added_count = await memory_service.batch_add_memories(
            user_id=user_id,
            project_id=chapter.project_id,
            memories=vector_records,
        )
        if added_count != len(vector_records):
            await memory_service.delete_chapter_memories(
                user_id=user_id,
                project_id=chapter.project_id,
                chapter_id=chapter.id,
            )
            raise RuntimeError("向量记忆写入不完整")

    task.status = "completed"
    task.progress = 100
    task.error_message = None
    task.completed_at = datetime.now()
    task.materialized_at = task.completed_at
    await db.commit()
    return AnalysisMaterializationResult(memory_count=len(memories))
