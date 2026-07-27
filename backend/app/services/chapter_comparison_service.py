"""章节多模型候选：冻结提示词、生成候选、采用正式版本。"""
from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.generation_history import GenerationHistory
from app.models.llm_comparison import LLMComparisonBatch, LLMComparisonCandidate
from app.models.outline import Outline
from app.models.project import Project
from app.models.writing_style import WritingStyle
from app.schemas.chapter import ChapterComparisonCreateRequest
from app.schemas.llm_comparison import LLMComparisonBatchCreate, LLMComparisonSelection
from app.services.chapter_context_service import OneToManyContextBuilder, OneToOneContextBuilder
from app.services.foreshadow_service import foreshadow_service
from app.services.llm_comparison_service import CandidateGenerationResult, create_batch
from app.services.memory_service import memory_service
from app.services.prompt_service import PromptService, WritingStyleManager


@dataclass
class FrozenChapterGeneration:
    input_snapshot: dict
    prompt: str
    parameters: dict


async def build_frozen_chapter_generation(
    db: AsyncSession,
    *,
    chapter: Chapter,
    user_id: str,
    request: ChapterComparisonCreateRequest,
) -> FrozenChapterGeneration:
    """只构建一次，确保不同模型收到完全相同的正文提示和参数。"""
    project = await db.scalar(select(Project).where(
        Project.id == chapter.project_id,
        Project.user_id == user_id,
    ))
    if project is None:
        raise ValueError("项目不存在或无权访问")

    if chapter.outline_id:
        outline = await db.scalar(select(Outline).where(Outline.id == chapter.outline_id))
    else:
        outline = await db.scalar(select(Outline).where(
            Outline.project_id == chapter.project_id,
            Outline.order_index == chapter.chapter_number,
        ))

    style_content = ""
    style_name = None
    if request.style_id:
        style = await db.scalar(select(WritingStyle).where(WritingStyle.id == request.style_id))
        if style is None or (style.user_id is not None and style.user_id != user_id):
            raise ValueError("写作风格不存在或无权使用")
        style_content = style.prompt_content or ""
        style_name = style.name

    outline_mode = project.outline_mode or "one-to-many"
    if outline_mode == "one-to-one":
        builder = OneToOneContextBuilder(memory_service=memory_service, foreshadow_service=foreshadow_service)
        context = await builder.build(
            chapter=chapter, project=project, outline=outline, user_id=user_id,
            db=db, target_word_count=request.target_word_count,
        )
    else:
        builder = OneToManyContextBuilder(memory_service=memory_service, foreshadow_service=foreshadow_service)
        context = await builder.build(
            chapter=chapter, project=project, outline=outline, user_id=user_id, db=db,
            style_content=style_content, target_word_count=request.target_word_count,
            temp_narrative_perspective=request.narrative_perspective,
        )

    perspective = request.narrative_perspective or project.narrative_perspective or "第三人称"
    common = dict(
        project_title=project.title,
        chapter_number=chapter.chapter_number,
        chapter_title=chapter.title,
        chapter_outline=context.chapter_outline,
        target_word_count=request.target_word_count,
        genre=project.genre or "未设定",
        narrative_perspective=perspective,
        characters_info=context.chapter_characters or "暂无角色信息",
        chapter_careers=context.chapter_careers or "暂无职业信息",
        foreshadow_reminders=context.foreshadow_reminders or "暂无需要关注的伏笔",
        relevant_memories=context.relevant_memories or "暂无相关记忆",
    )
    if outline_mode == "one-to-one":
        if context.continuation_point:
            template_key = "CHAPTER_GENERATION_ONE_TO_ONE_NEXT"
            common.update(
                previous_chapter_content=context.continuation_point,
                previous_chapter_summary=context.previous_chapter_summary or "（无上一章摘要）",
                recent_chapters_context=context.recent_chapters_context or "暂无最近章节摘要",
            )
        else:
            template_key = "CHAPTER_GENERATION_ONE_TO_ONE"
    elif context.continuation_point:
        template_key = "CHAPTER_GENERATION_ONE_TO_MANY_NEXT"
        common.update(
            continuation_point=context.continuation_point,
            previous_chapter_summary=context.previous_chapter_summary or "（无上一章摘要，请根据锚点续写）",
            recent_chapters_context=context.recent_chapters_context or "",
        )
    else:
        template_key = "CHAPTER_GENERATION_ONE_TO_MANY"

    template = await PromptService.get_template(template_key, user_id, db)
    prompt = PromptService.format_prompt(template, **common)
    if style_content:
        prompt = WritingStyleManager.apply_style_to_prompt(prompt, style_content)

    system_prompt = None
    skill_name = None
    if request.skill_key:
        from app.services.skill_loader import get_all_skills_cached
        skill = next((item for item in get_all_skills_cached() if item["template_key"] == request.skill_key), None)
        if skill is None:
            raise ValueError("选择的 Skill 不存在")
        skill_name = skill["template_name"]
        system_prompt = f"【⚡ Skill 工作流：{skill_name}】\n\n{skill['content']}\n\n⚠️ 请严格遵循上述 Skill 工作流指令进行创作！"
        if style_content:
            system_prompt += f"\n\n【🎨 写作风格要求 - 补充】\n\n{style_content}"
    elif style_content:
        system_prompt = f"【🎨 写作风格要求 - 最高优先级】\n\n{style_content}\n\n⚠️ 请严格遵循上述写作风格要求进行创作！"

    max_tokens = max(2000, min(request.target_word_count * 3, 16000))
    return FrozenChapterGeneration(
        input_snapshot={
            "chapter_id": chapter.id,
            "chapter_number": chapter.chapter_number,
            "chapter_title": chapter.title,
            "project_id": project.id,
            "project_title": project.title,
            "outline_id": chapter.outline_id,
            "outline_mode": outline_mode,
            "template_key": template_key,
            "style_id": request.style_id,
            "style_name": style_name,
            "skill_key": request.skill_key,
            "skill_name": skill_name,
            "narrative_perspective": perspective,
            "target_word_count": request.target_word_count,
            "formal_content_before": chapter.content or "",
            "formal_updated_at": chapter.updated_at.isoformat() if chapter.updated_at else None,
        },
        prompt=prompt,
        parameters={
            "max_tokens": max_tokens,
            "system_prompt": system_prompt,
            "tool_choice": "required",
            "auto_mcp": bool(request.enable_mcp),
        },
    )


async def create_chapter_comparison(
    db: AsyncSession,
    *,
    chapter: Chapter,
    user_id: str,
    request: ChapterComparisonCreateRequest,
) -> tuple[LLMComparisonBatch, list[LLMComparisonCandidate]]:
    frozen = await build_frozen_chapter_generation(db, chapter=chapter, user_id=user_id, request=request)
    return await create_batch(
        db,
        user_id=user_id,
        data=LLMComparisonBatchCreate(
            project_id=chapter.project_id,
            target_type="chapter",
            target_id=chapter.id,
            usage_type="chapter_write_compare",
            input_snapshot=frozen.input_snapshot,
            prompt_snapshot=frozen.prompt,
            parameters_snapshot=frozen.parameters,
            selections=[LLMComparisonSelection(**item.model_dump()) for item in request.selections],
        ),
    )


async def generate_chapter_candidate(
    db: AsyncSession,
    batch: LLMComparisonBatch,
    candidate: LLMComparisonCandidate,
) -> CandidateGenerationResult:
    from app.services.ai_provider_service import create_routed_ai_service

    params = dict(batch.parameters_snapshot or {})
    service = await create_routed_ai_service(
        db,
        user_id=batch.user_id,
        usage_type="chapter_write",
        provider_config_id=candidate.provider_config_id,
        model=candidate.model,
        project_id=batch.project_id,
        chapter_id=batch.target_id,
        task_trace_id=batch.id,
        enable_mcp=bool(params.get("auto_mcp", True)),
    )
    started = perf_counter()
    result = await service.generate_text(prompt=batch.prompt_snapshot, **params)
    elapsed = int((perf_counter() - started) * 1000)
    usage = result.get("usage") or {}
    return CandidateGenerationResult(
        output_text=str(result.get("content") or ""),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        duration_ms=elapsed,
    )


async def apply_chapter_candidate(
    db: AsyncSession,
    batch: LLMComparisonBatch,
    candidate: LLMComparisonCandidate,
) -> None:
    """采用时才修改正式章节；其他候选继续保留。"""
    chapter = await db.scalar(select(Chapter).where(
        Chapter.id == batch.target_id,
        Chapter.project_id == batch.project_id,
    ).with_for_update())
    project = await db.scalar(select(Project).where(
        Project.id == batch.project_id,
        Project.user_id == batch.user_id,
    ).with_for_update())
    if chapter is None or project is None:
        raise ValueError("章节不存在或无权访问")

    expected_updated_at: Optional[str] = (batch.input_snapshot or {}).get("formal_updated_at")
    actual_updated_at = chapter.updated_at.isoformat() if chapter.updated_at else None
    if expected_updated_at != actual_updated_at:
        raise ValueError("正式章节在候选生成后已被修改，请重新发起比较")
    content = candidate.output_text or ""
    if not content.strip():
        raise ValueError("候选结果为空，不能采用")

    old_content = chapter.content or ""
    old_word_count = chapter.word_count or len(old_content)
    chapter.content = content
    chapter.word_count = len(content)
    chapter.summary = content.strip()[:300]
    chapter.status = "completed"
    project.current_words = (project.current_words or 0) - old_word_count + len(content)
    db.add(GenerationHistory(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        prompt=f"采用多模型候选前的正式版本（批次 {batch.id}）",
        generated_content=old_content,
        model="formal-before-comparison",
    ))
    db.add(GenerationHistory(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        prompt=f"采用多模型候选：{candidate.provider_name} / {candidate.model}",
        generated_content=content,
        model=candidate.model[:50],
        tokens_used=candidate.total_tokens,
        generation_time=(candidate.duration_ms or 0) / 1000,
    ))
