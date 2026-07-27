"""章节分析候选：生成阶段纯预览，确认采用后才写分析表。"""
import json
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.llm_comparison import LLMComparisonBatch, LLMComparisonCandidate
from app.models.memory import PlotAnalysis
from app.schemas.chapter import AnalysisComparisonCreateRequest
from app.schemas.llm_comparison import LLMComparisonBatchCreate, LLMComparisonSelection
from app.services.llm_comparison_service import CandidateGenerationResult, create_batch
from app.services.plot_analyzer import PlotAnalyzer
from app.services.prompt_service import PromptService


async def create_analysis_comparison(db: AsyncSession, *, chapter: Chapter, user_id: str, payload: AnalysisComparisonCreateRequest):
    template = await PromptService.get_template("PLOT_ANALYSIS", user_id, db)
    prompt = PromptService.format_prompt(
        template, chapter_number=chapter.chapter_number, title=chapter.title,
        word_count=chapter.word_count or len(chapter.content or ""), content=(chapter.content or "")[:8000],
        existing_foreshadows="（候选预览不读取或修改动态伏笔状态）", characters_info="（候选预览仅分析正文中出现的角色）",
    )
    return await create_batch(db, user_id=user_id, data=LLMComparisonBatchCreate(
        project_id=chapter.project_id, target_type="analysis", target_id=chapter.id,
        usage_type="chapter_analysis_compare",
        input_snapshot={"chapter_id": chapter.id, "content": chapter.content or "", "updated_at": chapter.updated_at.isoformat() if chapter.updated_at else None},
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
    if (chapter.content or "") != snap.get("content") or (chapter.updated_at.isoformat() if chapter.updated_at else None) != snap.get("updated_at"):
        raise ValueError("章节正文在候选分析后已改变，请重新分析")
    data = candidate.output_data or json.loads(candidate.output_text or "{}")
    row = await db.scalar(select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter.id).with_for_update())
    if row is None:
        row = PlotAnalysis(project_id=chapter.project_id, chapter_id=chapter.id)
        db.add(row)
    values = {
        "plot_stage": data.get("plot_stage", "发展"), "conflict_level": data.get("conflict", {}).get("level", 0),
        "conflict_types": data.get("conflict", {}).get("types", []), "emotional_tone": data.get("emotional_arc", {}).get("primary_emotion", ""),
        "emotional_intensity": data.get("emotional_arc", {}).get("intensity", 0)/10, "hooks": data.get("hooks", []),
        "foreshadows": data.get("foreshadows", []), "plot_points": data.get("plot_points", []), "character_states": data.get("character_states", []),
        "scenes": data.get("scenes", []), "pacing": data.get("pacing", "moderate"), "suggestions": data.get("suggestions", []),
        "overall_quality_score": data.get("scores", {}).get("overall", 0), "pacing_score": data.get("scores", {}).get("pacing", 0),
        "engagement_score": data.get("scores", {}).get("engagement", 0), "coherence_score": data.get("scores", {}).get("coherence", 0),
        "analysis_report": data.get("analysis_report", ""), "dialogue_ratio": data.get("dialogue_ratio", 0), "description_ratio": data.get("description_ratio", 0),
        "word_count": chapter.word_count or len(chapter.content or ""),
    }
    values.update(hooks_count=len(values["hooks"]), foreshadows_planted=sum(x.get("type")=="planted" for x in values["foreshadows"]),
        foreshadows_resolved=sum(x.get("type")=="resolved" for x in values["foreshadows"]), plot_points_count=len(values["plot_points"]))
    for key, value in values.items(): setattr(row, key, value)
