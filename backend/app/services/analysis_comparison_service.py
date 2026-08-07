"""章节分析候选：生成阶段纯预览，确认采用后才写分析表。"""
import json
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.analysis_task import AnalysisTask
from app.models.llm_comparison import LLMComparisonBatch, LLMComparisonCandidate
from app.schemas.chapter import AnalysisComparisonCreateRequest
from app.schemas.llm_comparison import LLMComparisonBatchCreate, LLMComparisonSelection
from app.services.llm_comparison_service import CandidateGenerationResult, create_batch
from app.services.chapter_analysis_context_service import build_chapter_analysis_context
from app.services.chapter_lifecycle_service import chapter_content_hash, create_pending_analysis_task
from app.services.chapter_analysis_materialization_service import materialize_chapter_analysis
from app.services.foreshadow_service import foreshadow_service
from app.services.plot_analyzer import PlotAnalyzer
from app.services.memory_service import memory_service
from app.services.project_state_checkpoint_service import prepare_project_state_for_chapter_rewrite


async def create_analysis_comparison(db: AsyncSession, *, chapter: Chapter, user_id: str, payload: AnalysisComparisonCreateRequest):
    context = await build_chapter_analysis_context(
        db=db,
        chapter=chapter,
        foreshadow_service=foreshadow_service,
    )
    prompt = await PlotAnalyzer.build_analysis_prompt(
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        word_count=chapter.word_count or len(chapter.content or ""),
        content=chapter.content or "",
        user_id=user_id,
        db=db,
        existing_foreshadows=context.existing_foreshadows,
        characters_info=context.characters_info,
    )
    return await create_batch(db, user_id=user_id, data=LLMComparisonBatchCreate(
        project_id=chapter.project_id, target_type="analysis", target_id=chapter.id,
        usage_type="chapter_analysis_compare",
        input_snapshot={
            "chapter_id": chapter.id,
            "content": chapter.content or "",
            "content_hash": chapter_content_hash(chapter.content),
            "updated_at": chapter.updated_at.isoformat() if chapter.updated_at else None,
        },
        prompt_snapshot=prompt, parameters_snapshot={"temperature": 0.3, "auto_mcp": False},
        selections=[LLMComparisonSelection(**item.model_dump()) for item in payload.selections],
    ))


async def generate_analysis_candidate(db: AsyncSession, batch: LLMComparisonBatch, candidate: LLMComparisonCandidate):
    from app.services.ai_provider_service import create_routed_ai_service
    service = await create_routed_ai_service(db, user_id=batch.user_id, usage_type="chapter_analysis",
        provider_config_id=candidate.provider_config_id, model=candidate.model, project_id=batch.project_id,
        chapter_id=batch.target_id, task_trace_id=batch.id, enable_mcp=False)
    started = perf_counter()
    result = await service.generate_text(prompt=batch.prompt_snapshot, temperature=0.3, auto_mcp=False)
    raw = str(result.get("content") or "")
    analysis = PlotAnalyzer(service)._parse_analysis_response(raw)
    if not analysis:
        raise ValueError("模型返回的分析格式无法解析")
    analysis["analysis_report"] = PlotAnalyzer(service).generate_analysis_summary(analysis)
    usage = result.get("usage") or {}
    return CandidateGenerationResult(output_text=json.dumps(analysis, ensure_ascii=False, indent=2), output_data=analysis,
        prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"), total_tokens=usage.get("total_tokens"),
        duration_ms=int((perf_counter()-started)*1000))


async def apply_analysis_candidate(db: AsyncSession, batch: LLMComparisonBatch, candidate: LLMComparisonCandidate):
    chapter = await db.scalar(select(Chapter).where(Chapter.id == batch.target_id).with_for_update())
    if chapter is None or chapter.project_id != batch.project_id:
        raise ValueError("章节不存在")
    snap = batch.input_snapshot or {}
    if (
        chapter_content_hash(chapter.content) != snap.get("content_hash")
        or (chapter.updated_at.isoformat() if chapter.updated_at else None) != snap.get("updated_at")
    ):
        raise ValueError("章节正文在候选分析后已改变，请重新分析")
    data = candidate.output_data or json.loads(candidate.output_text or "{}")
    existing_task = await db.scalar(
        select(AnalysisTask)
        .where(
            AnalysisTask.chapter_id == chapter.id,
            AnalysisTask.materialized_at.is_not(None),
        )
        .order_by(AnalysisTask.created_at.desc())
        .limit(1)
    )
    if existing_task is not None:
        await prepare_project_state_for_chapter_rewrite(
            db,
            user_id=batch.user_id,
            chapter=chapter,
            memory_service=memory_service,
        )
    task = create_pending_analysis_task(chapter=chapter, user_id=batch.user_id)
    db.add(task)
    await db.flush()
    await materialize_chapter_analysis(
        db=db,
        user_id=batch.user_id,
        chapter=chapter,
        task=task,
        analysis=data,
        analyzer=PlotAnalyzer(None),
        memory_service=memory_service,
        foreshadow_service=foreshadow_service,
        commit=False,
    )
    output_data = dict(data)
    output_data["formal_analysis_task_id"] = task.id
    candidate.output_data = output_data
