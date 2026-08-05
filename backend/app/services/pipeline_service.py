"""自动化小说生产流水线：编排器（阶段状态机 + 后台推进循环）。

阶段流：
  book（一键建书）→ chapter_loop（章节循环）→ checkpoint（检查点挂起）→
  volume_transition（卷过渡）→ chapter_loop → ...

检查点条件（任一满足即挂起，独立判定）：
  - 每 N 章（checkpoint_every_n）
  - 每卷结束（checkpoint_on_volume_end）
  - 里程碑（milestone_chapters）
  - 用户手动暂停

回滚（分内容/分阶段/纯删除）由 checkpoints 任务提供接口，本模块提供编排钩子。
"""
import asyncio
from datetime import datetime
from typing import Any, Optional

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_engine
from app.logger import get_logger
from app.models.background_task import BackgroundTask
from app.models.chapter import Chapter, ChapterStatus
from app.models.novel_pipeline import (
    CheckpointStatus,
    CheckpointType,
    NovelPipeline,
    PipelineCheckpoint,
    PipelineStage,
    PipelineStatus,
)
from app.models.outline import Outline
from app.models.project import Project

logger = get_logger(__name__)

# 后台循环任务持有（防止被 GC）
_pipeline_tasks: set[asyncio.Task] = set()


class PipelineNotFoundError(ValueError):
    pass


class PipelineStateError(ValueError):
    pass


# ---------- 默认配置（蓝图第六节：全阶段默认 deepseek-v4-flash，用户可覆盖） ----------
def default_pipeline_config() -> dict:
    return {
        "milestone_chapters": 30,          # 里程碑：累计章节数 ≥ 30 暂停
        "checkpoint_every_n": 10,          # 每 10 章停一次
        "checkpoint_on_volume_end": True,  # 每卷结束必停
        "models": {                        # 每阶段模型；provider_config_id/model 为空 = 用默认路由
            "book": {"provider_config_id": None, "model": None},
            "chapter": {"provider_config_id": None, "model": None},
            "analysis": {"provider_config_id": None, "model": None},
            "volume_transition": {"provider_config_id": None, "model": None},
        },
        "budget": {"max_amount_cents": 3000, "max_tokens": 0},  # 默认预算 ¥30
        "params": {                        # 每阶段生成参数（用户可调）
            "book": {"temperature": 0.8, "max_tokens": 32000},
            "chapter": {"temperature": 0.8, "max_tokens": 32000},
            "analysis": {"temperature": 0.3, "max_tokens": 8000},
            "volume_transition": {"temperature": 0.8, "max_tokens": 32000},
        },
    }


def merge_config(user_config: Optional[dict]) -> dict:
    cfg = default_pipeline_config()
    if user_config:
        for k, v in user_config.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


# ---------- 查询 ----------
async def get_pipeline(db: AsyncSession, pipeline_id: str, user_id: str) -> NovelPipeline:
    pipeline = await db.scalar(
        select(NovelPipeline).where(
            NovelPipeline.id == pipeline_id,
            NovelPipeline.project_id.in_(select(Project.id).where(Project.user_id == user_id)),
        )
    )
    if pipeline is None:
        raise PipelineNotFoundError("流水线不存在或无权限")
    return pipeline


async def get_pipeline_by_project(db: AsyncSession, project_id: str, user_id: str) -> Optional[NovelPipeline]:
    return await db.scalar(
        select(NovelPipeline).where(
            NovelPipeline.project_id == project_id,
            NovelPipeline.project_id.in_(select(Project.id).where(Project.user_id == user_id)),
        )
    )


# ---------- 后台循环调度 ----------
def _spawn_loop(session_factory: async_sessionmaker[AsyncSession], pipeline_id: str, user_id: str) -> None:
    task = asyncio.create_task(_run_pipeline_loop(session_factory, pipeline_id, user_id))
    _pipeline_tasks.add(task)
    task.add_done_callback(_pipeline_tasks.discard)


async def _session_factory_for(user_id: str) -> async_sessionmaker[AsyncSession]:
    engine = await get_engine(user_id)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------- 启动 / 暂停 / 恢复 / 停止 ----------
async def start_pipeline(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: str,
    config: Optional[dict] = None,
) -> NovelPipeline:
    """创建流水线并启动后台推进。"""
    existing = await get_pipeline_by_project(db, project_id, user_id)
    if existing and existing.status in {PipelineStatus.RUNNING, PipelineStatus.AWAITING_REVIEW}:
        raise PipelineStateError("该项目已有正在运行的流水线")

    if existing is None:
        pipeline = NovelPipeline(
            id=str(uuid.uuid4()),
            project_id=project_id,
            status=PipelineStatus.RUNNING,
            current_stage=PipelineStage.BOOK,
            config_snapshot=merge_config(config),
        )
        db.add(pipeline)
        await db.commit()
        await db.refresh(pipeline)
    else:
        pipeline = existing
        pipeline.status = PipelineStatus.RUNNING
        pipeline.current_stage = PipelineStage.BOOK
        pipeline.config_snapshot = merge_config(config or pipeline.config_snapshot)
        await db.commit()

    # 建书阶段：若项目还没有大纲/章节，直接进入 chapter_loop 前的准备由后续任务承接；
    # 本编排器从 chapter_loop 起驱动（一键建书后台化属于 wizard-background 任务）。
    factory = await _session_factory_for(user_id)
    async with factory() as loop_db:
        loop_pipeline = await get_pipeline(loop_db, pipeline.id, user_id)
        outline = await loop_db.scalar(
            select(Outline).where(Outline.project_id == project_id).order_by(Outline.order_index).limit(1)
        )
        if outline is not None:
            loop_pipeline.current_stage = PipelineStage.CHAPTER_LOOP
            loop_pipeline.current_outline_id = outline.id
            await loop_db.commit()
        else:
            loop_pipeline.current_stage = PipelineStage.BOOK
            loop_pipeline.last_error = "项目没有大纲，无法开始章节循环（建书后台化尚未实现）"
            loop_pipeline.status = PipelineStatus.PAUSED
            await loop_db.commit()
            raise PipelineStateError("项目没有大纲，请先建书。")

    pipeline = await get_pipeline(db, pipeline.id, user_id)
    _spawn_loop(await _session_factory_for(user_id), pipeline.id, user_id)
    return pipeline


async def resume_pipeline(db: AsyncSession, *, user_id: str, pipeline_id: str) -> NovelPipeline:
    pipeline = await get_pipeline(db, pipeline_id, user_id)
    if pipeline.status not in {PipelineStatus.AWAITING_REVIEW, PipelineStatus.PAUSED}:
        raise PipelineStateError(f"流水线当前状态为 {pipeline.status}，不能恢复")
    if pipeline.current_stage == PipelineStage.CHECKPOINT:
        pipeline.current_stage = PipelineStage.CHAPTER_LOOP
    pipeline.status = PipelineStatus.RUNNING
    await db.commit()
    _spawn_loop(await _session_factory_for(user_id), pipeline.id, user_id)
    return pipeline


async def pause_pipeline(db: AsyncSession, *, user_id: str, pipeline_id: str) -> NovelPipeline:
    pipeline = await get_pipeline(db, pipeline_id, user_id)
    if pipeline.status not in {PipelineStatus.RUNNING, PipelineStatus.AWAITING_REVIEW}:
        raise PipelineStateError(f"流水线当前状态为 {pipeline.status}，不能暂停")
    pipeline.status = PipelineStatus.PAUSED
    await db.commit()
    return pipeline


async def stop_pipeline(db: AsyncSession, *, user_id: str, pipeline_id: str) -> NovelPipeline:
    pipeline = await get_pipeline(db, pipeline_id, user_id)
    pipeline.status = PipelineStatus.STOPPED
    await db.commit()
    return pipeline


# ---------- 主循环 ----------
async def _run_pipeline_loop(
    session_factory: async_sessionmaker[AsyncSession],
    pipeline_id: str,
    user_id: str,
) -> None:
    """流水线推进循环：逐章生成 → 检查点判断 → 挂起或继续。"""
    try:
        while True:
            async with session_factory() as db:
                pipeline = await get_pipeline(db, pipeline_id, user_id)
                if pipeline.status != PipelineStatus.RUNNING:
                    return

                if pipeline.current_stage == PipelineStage.BOOK:
                    # 建书后台化（wizard-background 任务）未实现前的占位：
                    # 尝试直接找第一个大纲进入章节循环
                    outline = await db.scalar(
                        select(Outline)
                        .where(Outline.project_id == pipeline.project_id)
                        .order_by(Outline.order_index).limit(1)
                    )
                    if outline is None:
                        pipeline.status = PipelineStatus.PAUSED
                        pipeline.last_error = "项目没有大纲，无法开始章节循环"
                        await db.commit()
                        return
                    pipeline.current_stage = PipelineStage.CHAPTER_LOOP
                    pipeline.current_outline_id = outline.id
                    await db.commit()
                    continue

                if pipeline.current_stage == PipelineStage.VOLUME_TRANSITION:
                    await _transition_volume(db, pipeline, user_id)
                    pipeline.current_stage = PipelineStage.CHAPTER_LOOP
                    await db.commit()
                    continue

                if pipeline.current_stage == PipelineStage.CHAPTER_LOOP:
                    chapter = await _next_pending_chapter(db, pipeline)
                    if chapter is None:
                        # 当前卷写完了
                        if pipeline.config_snapshot.get("checkpoint_on_volume_end", True):
                            await _create_checkpoint(
                                db, pipeline, CheckpointType.VOLUME_END,
                                trigger=pipeline.chapter_count,
                                chapter_from=await _current_volume_range(db, pipeline, end=True),
                                chapter_to=pipeline.chapter_count,
                            )
                            pipeline.status = PipelineStatus.AWAITING_REVIEW
                            pipeline.current_stage = PipelineStage.CHECKPOINT
                            await db.commit()
                            return
                        pipeline.current_stage = PipelineStage.VOLUME_TRANSITION
                        await db.commit()
                        continue

                    # 生成该章节（复用现有后台生成逻辑）
                    ok, err = await _generate_one_chapter(db, pipeline, chapter, user_id)
                    if not ok:
                        chapter.status = ChapterStatus.FAILED
                        pipeline.last_error = err
                        await db.commit()
                        return

                    pipeline.chapter_count = await _count_completed_chapters(db, pipeline.project_id)
                    await db.commit()

                    # 检查点判断
                    due, ctype = await _checkpoint_due(db, pipeline)
                    if due:
                        await _create_checkpoint(
                            db, pipeline, ctype,
                            trigger=pipeline.chapter_count,
                            chapter_from=await _current_volume_range(db, pipeline, end=False),
                            chapter_to=pipeline.chapter_count,
                        )
                        pipeline.status = PipelineStatus.AWAITING_REVIEW
                        pipeline.current_stage = PipelineStage.CHECKPOINT
                        await db.commit()
                        return

                    await asyncio.sleep(0.3)
                    continue

                # 未知阶段：暂停并记录
                pipeline.status = PipelineStatus.PAUSED
                pipeline.last_error = f"未知阶段 {pipeline.current_stage}"
                await db.commit()
                return
    except PipelineNotFoundError:
        logger.warning(f"流水线不存在，循环退出: {pipeline_id[:8]}")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"流水线循环异常: {exc}", exc_info=True)
        try:
            async with session_factory() as db:
                pipeline = await get_pipeline(db, pipeline_id, user_id)
                pipeline.status = PipelineStatus.FAILED
                pipeline.last_error = str(exc)[:2000]
                await db.commit()
        except Exception:  # noqa: BLE001
            pass


# ---------- 子步骤 ----------
async def _next_pending_chapter(db: AsyncSession, pipeline: NovelPipeline) -> Optional[Chapter]:
    """当前卷(Outline)内、按顺序的第一个可生成章节（pending/draft 且前置已满足）。"""
    if not pipeline.current_outline_id:
        # 回退：当前卷为空时，取项目内最早的未完成章节
        stmt = (
            select(Chapter)
            .where(
                Chapter.project_id == pipeline.project_id,
                Chapter.status.in_([ChapterStatus.PENDING, ChapterStatus.DRAFT]),
            )
            .order_by(Chapter.chapter_number, Chapter.sub_index)
            .limit(10)
        )
    else:
        stmt = (
            select(Chapter)
            .where(
                Chapter.outline_id == pipeline.current_outline_id,
                Chapter.status.in_([ChapterStatus.PENDING, ChapterStatus.DRAFT]),
            )
            .order_by(Chapter.chapter_number, Chapter.sub_index)
            .limit(10)
        )
    chapters = list((await db.scalars(stmt)).all())

    from app.api.chapters import check_prerequisites

    for ch in chapters:
        can, msg, _ = await check_prerequisites(db, ch)
        if can:
            return ch
    return None


async def _count_completed_chapters(db: AsyncSession, project_id: str) -> int:
    from sqlalchemy import func

    return (
        await db.scalar(
            select(func.count(Chapter.id)).where(
                Chapter.project_id == project_id,
                Chapter.status == ChapterStatus.COMPLETED,
            )
        )
        or 0
    )


async def _current_volume_range(db: AsyncSession, pipeline: NovelPipeline, *, end: bool) -> Optional[int]:
    """当前卷的起始章节号（end=False 返回起始，end=True 返回结束）。"""
    if not pipeline.current_outline_id:
        return None
    chapter = await db.scalar(
        select(Chapter)
        .where(Chapter.outline_id == pipeline.current_outline_id)
        .order_by(Chapter.chapter_number if not end else Chapter.chapter_number.desc())
        .limit(1)
    )
    return chapter.chapter_number if chapter else None


async def _checkpoint_due(db: AsyncSession, pipeline: NovelPipeline) -> tuple[bool, str]:
    """判断当前是否该触发检查点。返回 (是否触发, 类型)。"""
    cfg = pipeline.config_snapshot or {}
    n = pipeline.chapter_count
    every_n = cfg.get("checkpoint_every_n") or 0
    milestone = cfg.get("milestone_chapters") or 0

    if every_n and n > 0 and n % every_n == 0:
        return True, CheckpointType.EVERY_N
    if milestone and n >= milestone:
        return True, CheckpointType.MILESTONE
    return False, ""


async def _create_checkpoint(
    db: AsyncSession,
    pipeline: NovelPipeline,
    ctype: str,
    *,
    trigger: int,
    chapter_from: Optional[int],
    chapter_to: Optional[int],
) -> PipelineCheckpoint:
    cp = PipelineCheckpoint(
        id=str(uuid.uuid4()),
        pipeline_id=pipeline.id,
        checkpoint_type=ctype,
        trigger_chapter_number=trigger,
        chapter_from=chapter_from,
        chapter_to=chapter_to,
        status=CheckpointStatus.PENDING,
    )
    db.add(cp)
    await db.flush()
    pipeline.current_checkpoint_id = cp.id
    history = list(pipeline.checkpoint_history or [])
    history.append({
        "checkpoint_id": cp.id,
        "type": ctype,
        "trigger": trigger,
        "chapter_from": chapter_from,
        "chapter_to": chapter_to,
        "status": CheckpointStatus.PENDING,
        "created_at": datetime.now().isoformat(),
    })
    pipeline.checkpoint_history = history
    return cp


async def _generate_one_chapter(
    db: AsyncSession,
    pipeline: NovelPipeline,
    chapter: Chapter,
    user_id: str,
) -> tuple[bool, str]:
    """生成单章正文（复用现有后台章节生成逻辑）。"""
    from app.api.chapters import _run_chapter_generation_bg
    from app.services.background_task_service import TaskProgressTracker
    from app.services.ai_provider_service import create_routed_ai_service

    cfg = pipeline.config_snapshot or {}
    chapter_model_cfg = (cfg.get("models") or {}).get("chapter") or {}
    provider_config_id = chapter_model_cfg.get("provider_config_id")
    model = chapter_model_cfg.get("model")
    params = (cfg.get("params") or {}).get("chapter") or {}

    tracker = TaskProgressTracker(f"pipeline-{pipeline.id[:8]}", user_id, "流水线章节")
    try:
        ai_service = await create_routed_ai_service(
            db,
            user_id=user_id,
            usage_type="chapter_write",
            provider_config_id=provider_config_id,
            model=model,
            project_id=pipeline.project_id,
            chapter_id=chapter.id,
            task_trace_id=f"pipeline-{pipeline.id[:8]}",
            enable_mcp=False,
        )
        await _run_chapter_generation_bg(
            task_input={
                "chapter_id": chapter.id,
                "style_id": None,
                "target_word_count": 3000,
                "enable_mcp": False,
                "model": model,
                "provider_config_id": provider_config_id,
                "narrative_perspective": None,
                "skill_key": None,
                "temperature": params.get("temperature"),
                "max_tokens": params.get("max_tokens"),
            },
            db=db,
            ai_service=ai_service,
            tracker=tracker,
            user_id=user_id,
            task_id=f"pipeline-{pipeline.id[:8]}",
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001
        logger.error(f"章节生成失败: {exc}")
        return False, str(exc)[:1000]


async def _transition_volume(db: AsyncSession, pipeline: NovelPipeline, user_id: str) -> None:
    """卷过渡：当前卷写完 → 生成下一卷的 Outline 并设为当前卷。

    MVP（本任务）：若项目还有未归入任何卷的大纲或章节，直接选下一个；
    否则创建一条新的 Outline（标题/内容由 AI 生成，卷过渡细化在 volume-transition 任务）。
    """
    # 1) 尝试找一个还没有被任何卷用过的下一个大纲（按 order_index）
    used_outline_ids = select(Outline.id)
    next_outline = await db.scalar(
        select(Outline)
        .where(Outline.project_id == pipeline.project_id)
        .order_by(Outline.order_index)
        .limit(1)
    )
    # 简化：直接找当前卷之后的下一个大纲
    current = await db.get(Outline, pipeline.current_outline_id) if pipeline.current_outline_id else None
    if current is None:
        raise PipelineStateError("当前卷不存在，无法过渡")

    next_outline = await db.scalar(
        select(Outline)
        .where(Outline.project_id == pipeline.project_id, Outline.order_index > current.order_index)
        .order_by(Outline.order_index)
        .limit(1)
    )
    if next_outline is not None:
        pipeline.current_outline_id = next_outline.id
        return

    # 2) 没有下一条大纲 → 用 AI 生成一卷新大纲（继续模式，简单版）
    from app.services.prompt_service import PromptService

    project = await db.get(Project, pipeline.project_id)
    title = project.title if project else "未命名"
    template = await PromptService.get_template("OUTLINE_CONTINUE", user_id, db)
    prompt = PromptService.format_prompt(
        template,
        title=title,
        latest_outline_title=current.title,
        latest_outline_content=current.content or "",
        requirements="生成下一卷",
    )
    cfg = pipeline.config_snapshot or {}
    vt_cfg = (cfg.get("models") or {}).get("volume_transition") or {}
    params = (cfg.get("params") or {}).get("volume_transition") or {}

    from app.services.ai_provider_service import create_routed_ai_service

    service = await create_routed_ai_service(
        db,
        user_id=user_id,
        usage_type="outline",
        provider_config_id=vt_cfg.get("provider_config_id"),
        model=vt_cfg.get("model"),
        project_id=pipeline.project_id,
        task_trace_id=f"pipeline-{pipeline.id[:8]}",
        enable_mcp=False,
    )
    result = await service.generate_text(
        prompt=prompt,
        temperature=params.get("temperature", 0.8),
        max_tokens=params.get("max_tokens", 32000),
        auto_mcp=False,
    )
    content = result.get("content", "") if isinstance(result, dict) else str(result)
    new_outline = Outline(
        id=str(uuid.uuid4()),
        project_id=pipeline.project_id,
        title=f"卷 {current.order_index + 1}",
        content=content,
        order_index=current.order_index + 1,
    )
    db.add(new_outline)
    await db.flush()
    pipeline.current_outline_id = new_outline.id
