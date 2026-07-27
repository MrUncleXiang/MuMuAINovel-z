"""大纲多模型候选的冻结输入、生成和安全采用。"""
import json
from time import perf_counter

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.character import Character
from app.models.llm_comparison import LLMComparisonBatch, LLMComparisonCandidate
from app.models.outline import Outline
from app.models.project import Project
from app.schemas.llm_comparison import LLMComparisonBatchCreate, LLMComparisonSelection
from app.schemas.outline import OutlineComparisonCreateRequest
from app.services.llm_comparison_service import CandidateGenerationResult, create_batch
from app.services.prompt_service import PromptService


async def _build_outline_prompt(
    db: AsyncSession,
    *,
    project: Project,
    user_id: str,
    payload: OutlineComparisonCreateRequest,
    mode: str,
    existing: list[Outline],
) -> tuple[str, int]:
    characters = list((await db.scalars(select(Character).where(Character.project_id == project.id))).all())
    from app.api.outlines import _build_characters_info, _build_outline_continue_context

    if mode == "new":
        template = await PromptService.get_template("OUTLINE_CREATE", user_id, db)
        return PromptService.format_prompt(
            template,
            title=project.title,
            theme=payload.theme or project.theme or "未设定",
            genre=payload.genre or project.genre or "通用",
            chapter_count=payload.chapter_count,
            narrative_perspective=payload.narrative_perspective or "第三人称",
            time_period=project.world_time_period or "未设定",
            location=project.world_location or "未设定",
            atmosphere=project.world_atmosphere or "未设定",
            rules=project.world_rules or "未设定",
            characters_info=_build_characters_info(characters) or "暂无角色信息",
            requirements=payload.requirements or "",
            mcp_references="",
        ), 1

    if not existing:
        raise ValueError("续写模式需要已有大纲")
    start = existing[-1].order_index + 1
    context = await _build_outline_continue_context(
        project=project,
        latest_outlines=existing,
        characters=characters,
        chapter_count=payload.chapter_count,
        plot_stage=payload.plot_stage,
        story_direction=payload.story_direction or "自然延续",
        requirements=payload.requirements or "",
        db=db,
    )
    stage = {
        "development": "继续展开情节，深化角色关系",
        "climax": "进入故事高潮，矛盾激化",
        "ending": "解决主要冲突，给出结局",
    }.get(payload.plot_stage, "继续展开情节")
    template = await PromptService.get_template("OUTLINE_CONTINUE", user_id, db)
    return PromptService.format_prompt(
        template,
        title=project.title,
        theme=project.theme or "未设定",
        genre=project.genre or "通用",
        narrative_perspective=project.narrative_perspective or "第三人称",
        time_period=project.world_time_period or "未设定",
        location=project.world_location or "未设定",
        atmosphere=project.world_atmosphere or "未设定",
        rules=project.world_rules or "未设定",
        recent_outlines=context["recent_outlines"],
        characters_info=context["characters_info"],
        foreshadow_reminders="暂无需要关注的伏笔",
        chapter_count=payload.chapter_count,
        start_chapter=start,
        end_chapter=start + payload.chapter_count - 1,
        current_chapter_count=len(existing),
        plot_stage_instruction=stage,
        story_direction=payload.story_direction or "自然延续",
        requirements=payload.requirements or "",
        mcp_references="",
    ), start


async def create_outline_comparison(
    db: AsyncSession,
    *,
    project: Project,
    user_id: str,
    payload: OutlineComparisonCreateRequest,
) -> tuple[LLMComparisonBatch, list[LLMComparisonCandidate]]:
    existing = list((await db.scalars(
        select(Outline).where(Outline.project_id == project.id).order_by(Outline.order_index)
    )).all())
    mode = payload.mode
    if mode == "auto":
        mode = "continue" if existing else "new"
    prompt, start_index = await _build_outline_prompt(
        db, project=project, user_id=user_id, payload=payload, mode=mode, existing=existing,
    )
    signatures = [{
        "id": item.id,
        "order_index": item.order_index,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    } for item in existing]
    return await create_batch(
        db,
        user_id=user_id,
        data=LLMComparisonBatchCreate(
            project_id=project.id,
            target_type="outline",
            usage_type="outline_compare",
            input_snapshot={
                "mode": mode,
                "chapter_count": payload.chapter_count,
                "start_index": start_index,
                "existing_outlines": signatures,
                "request": payload.model_dump(exclude={"selections", "provider_config_id", "model", "provider"}),
            },
            prompt_snapshot=prompt,
            parameters_snapshot={"auto_mcp": bool(payload.enable_mcp)},
            selections=[LLMComparisonSelection(**item.model_dump()) for item in payload.selections],
        ),
    )


async def generate_outline_candidate(
    db: AsyncSession,
    batch: LLMComparisonBatch,
    candidate: LLMComparisonCandidate,
) -> CandidateGenerationResult:
    from app.api.outlines import _normalize_outline_data, _parse_ai_response
    from app.services.ai_provider_service import create_routed_ai_service

    service = await create_routed_ai_service(
        db,
        user_id=batch.user_id,
        usage_type="outline",
        provider_config_id=candidate.provider_config_id,
        model=candidate.model,
        project_id=batch.project_id,
        task_trace_id=batch.id,
        enable_mcp=bool((batch.parameters_snapshot or {}).get("auto_mcp", True)),
    )
    started = perf_counter()
    result = await service.generate_text(
        prompt=batch.prompt_snapshot,
        model=candidate.model,
        auto_mcp=bool((batch.parameters_snapshot or {}).get("auto_mcp", True)),
    )
    raw = str(result.get("content") or "")
    snapshot = batch.input_snapshot or {}
    outlines = _normalize_outline_data(
        _parse_ai_response(raw, raise_on_error=True),
        expected_count=int(snapshot["chapter_count"]),
        start_index=int(snapshot["start_index"]),
    )
    usage = result.get("usage") or {}
    return CandidateGenerationResult(
        output_text=json.dumps(outlines, ensure_ascii=False, indent=2),
        output_data=outlines,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        duration_ms=int((perf_counter() - started) * 1000),
    )


async def apply_outline_candidate(
    db: AsyncSession,
    batch: LLMComparisonBatch,
    candidate: LLMComparisonCandidate,
) -> None:
    from app.api.outlines import _normalize_outline_data, _save_outlines

    project = await db.scalar(select(Project).where(
        Project.id == batch.project_id,
        Project.user_id == batch.user_id,
    ).with_for_update())
    if project is None:
        raise ValueError("项目不存在或无权访问")
    snapshot = batch.input_snapshot or {}
    mode = snapshot.get("mode")
    current = list((await db.scalars(
        select(Outline).where(Outline.project_id == project.id).order_by(Outline.order_index).with_for_update()
    )).all())
    current_signatures = [{
        "id": item.id,
        "order_index": item.order_index,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    } for item in current]
    if current_signatures != snapshot.get("existing_outlines", []):
        raise ValueError("正式大纲在候选生成后已被修改，请重新发起比较")

    outline_data = candidate.output_data
    if not isinstance(outline_data, list):
        outline_data = json.loads(candidate.output_text or "[]")
    outline_data = _normalize_outline_data(
        outline_data,
        expected_count=int(snapshot["chapter_count"]),
        start_index=int(snapshot["start_index"]),
    )
    if mode == "new":
        dependent_count = await db.scalar(select(func.count(Chapter.id)).where(
            Chapter.project_id == project.id,
            func.length(func.trim(func.coalesce(Chapter.content, ""))) > 0,
        )) or 0
        if dependent_count:
            raise ValueError(f"已有 {dependent_count} 个章节包含正文。为避免丢失内容，不能直接替换大纲")
        await db.execute(delete(Chapter).where(Chapter.project_id == project.id))
        await db.execute(delete(Outline).where(Outline.project_id == project.id))
    await _save_outlines(project.id, outline_data, db, start_index=int(snapshot["start_index"]))
