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
            "chapter": {"temperature": 0.8, "max_tokens": 32000, "target_word_count": 3000},
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


async def update_pipeline_config(
    db: AsyncSession,
    *,
    user_id: str,
    pipeline_id: str,
    config: dict,
) -> NovelPipeline:
    """更新流水线配置（运行中也可改，下次循环迭代生效）。"""
    pipeline = await get_pipeline(db, pipeline_id, user_id)
    if pipeline.status == PipelineStatus.STOPPED:
        raise PipelineStateError("流水线已停止，无法修改配置")
    pipeline.config_snapshot = merge_config({**pipeline.config_snapshot, **config})
    await db.commit()
    return pipeline


# ---------- 检查点操作 ----------
async def list_checkpoints(
    db: AsyncSession, *, user_id: str, pipeline_id: str,
) -> list[PipelineCheckpoint]:
    await get_pipeline(db, pipeline_id, user_id)
    return list((await db.scalars(
        select(PipelineCheckpoint)
        .where(PipelineCheckpoint.pipeline_id == pipeline_id)
        .order_by(PipelineCheckpoint.created_at.desc())
    )).all())


async def get_checkpoint(
    db: AsyncSession, *, user_id: str, pipeline_id: str, checkpoint_id: str,
) -> PipelineCheckpoint:
    await get_pipeline(db, pipeline_id, user_id)
    checkpoint = await db.get(PipelineCheckpoint, checkpoint_id)
    if checkpoint is None or checkpoint.pipeline_id != pipeline_id:
        raise PipelineNotFoundError("检查点不存在")
    return checkpoint


async def approve_checkpoint(
    db: AsyncSession,
    *,
    user_id: str,
    pipeline_id: str,
    checkpoint_id: str,
) -> NovelPipeline:
    """检查点审阅：确认继续。将当前检查点标记 approved 并恢复流水线。"""
    pipeline = await get_pipeline(db, pipeline_id, user_id)
    checkpoint = await get_checkpoint(db, user_id=user_id, pipeline_id=pipeline_id, checkpoint_id=checkpoint_id)
    if checkpoint.status != CheckpointStatus.PENDING:
        raise PipelineStateError(f"检查点状态为 {checkpoint.status}，不能再次决策")
    checkpoint.status = CheckpointStatus.APPROVED
    checkpoint.decision = "continue"
    checkpoint.decided_at = datetime.now()
    history = list(pipeline.checkpoint_history or [])
    for item in history:
        if item.get("checkpoint_id") == checkpoint.id:
            item["status"] = CheckpointStatus.APPROVED
            item["decision"] = "continue"
    pipeline.checkpoint_history = history
    pipeline.current_checkpoint_id = None
    if pipeline.current_stage == PipelineStage.CHECKPOINT:
        pipeline.current_stage = PipelineStage.CHAPTER_LOOP
    pipeline.status = PipelineStatus.RUNNING
    await db.commit()
    _spawn_loop(await _session_factory_for(user_id), pipeline.id, user_id)
    return pipeline


async def rollback_to_checkpoint(
    db: AsyncSession,
    *,
    user_id: str,
    pipeline_id: str,
    target_checkpoint_id: str,
    mode: str = "content",
) -> NovelPipeline:
    """检查点审阅：回滚。删除目标检查点之后的所有章节（纯删除，蓝图决策），然后自动重写。

    mode="content"：只回退章节正文（默认）。
    mode="content+outline"：同时回退大纲（细化实现在 rollback 任务）。
    """
    from sqlalchemy import delete

    pipeline = await get_pipeline(db, pipeline_id, user_id)
    target = await get_checkpoint(db, user_id=user_id, pipeline_id=pipeline_id, checkpoint_id=target_checkpoint_id)
    if mode not in {"content", "content+outline"}:
        raise PipelineStateError("mode 必须是 content 或 content+outline")

    # 1) 回滚目标检查点之后的章节：删除内容、重置为草稿（骨架保留，重写时重新生成）
    #    纯删除语义 = 废弃内容不留存；章节骨架（标题/编号/大纲关联）是计划而非内容，保留。
    affected = list((await db.scalars(
        select(Chapter).where(
            Chapter.project_id == pipeline.project_id,
            Chapter.chapter_number > target.trigger_chapter_number,
        )
    )).all())
    for chapter in affected:
        chapter.content = ""
        chapter.summary = ""
        chapter.word_count = 0
        chapter.status = ChapterStatus.DRAFT
        chapter.updated_at = datetime.now()

    # 2) content+outline：额外重置目标检查点之后创建的大纲（细粒度实现留待 rollback 任务）
    if mode == "content+outline":
        await db.execute(
            delete(Outline).where(
                Outline.project_id == pipeline.project_id,
                Outline.created_at > target.created_at,
            )
        )

    # 3) 记录当前挂起检查点的决策为 rollback
    if pipeline.current_checkpoint_id:
        cur = await db.get(PipelineCheckpoint, pipeline.current_checkpoint_id)
        if cur is not None and cur.status == CheckpointStatus.PENDING:
            cur.status = CheckpointStatus.ROLLBACK
            cur.decision = "rollback"
            cur.rollback_to_checkpoint_id = target.id
            cur.decided_at = datetime.now()
    history = list(pipeline.checkpoint_history or [])
    for item in history:
        if item.get("checkpoint_id") == pipeline.current_checkpoint_id:
            item["status"] = CheckpointStatus.ROLLBACK
            item["decision"] = "rollback"
            item["rollback_to"] = target.id
    pipeline.checkpoint_history = history

    # 4) 重置计数并恢复推进
    pipeline.chapter_count = target.trigger_chapter_number
    pipeline.current_checkpoint_id = None
    pipeline.current_stage = PipelineStage.CHAPTER_LOOP
    pipeline.status = PipelineStatus.RUNNING
    await db.commit()
    _spawn_loop(await _session_factory_for(user_id), pipeline.id, user_id)
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
                    try:
                        await _transition_volume(db, pipeline, user_id)
                    except PipelineStateError as exc:
                        pipeline.status = PipelineStatus.PAUSED
                        pipeline.last_error = str(exc)
                        await db.commit()
                        return
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

                    # 生成该章节（复用现有后台生成逻辑），空内容/失败自动重试
                    ok, err = False, ""
                    for attempt in range(1, 4):
                        ok, err = await _generate_one_chapter(db, pipeline, chapter, user_id)
                        if not ok:
                            await asyncio.sleep(5 * attempt)
                            continue
                        # 校验内容非空（推理型模型可能在 token 上限内只输出思考）
                        fresh = await db.get(Chapter, chapter.id)
                        if fresh and (fresh.content or "").strip():
                            break
                        err = "生成结果为空（模型只输出了思考内容），重试"
                        chapter.status = ChapterStatus.PENDING
                        await db.commit()
                        await asyncio.sleep(5 * attempt)
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
    target_word_count = int(params.get("target_word_count", 3000) or 3000)

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
                "target_word_count": target_word_count,
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
    """卷过渡：当前卷写完 → 切到下一卷 Outline。

    MVP（检查点任务）：只切到已有的大纲（下一个 Outline）；若没有下一条大纲，
    暂停并提示（AI 自动生成下一卷大纲属于 volume-transition 任务）。
    """
    current = await db.get(Outline, pipeline.current_outline_id) if pipeline.current_outline_id else None
    if current is None:
        # 没有当前卷：取项目内第一个大纲
        first = await db.scalar(
            select(Outline).where(Outline.project_id == pipeline.project_id)
            .order_by(Outline.order_index).limit(1)
        )
        if first is None:
            raise PipelineStateError("项目没有大纲，无法进行卷过渡")
        pipeline.current_outline_id = first.id
        return

    next_outline = await db.scalar(
        select(Outline)
        .where(Outline.project_id == pipeline.project_id, Outline.order_index > current.order_index)
        .order_by(Outline.order_index)
        .limit(1)
    )
    if next_outline is not None:
        pipeline.current_outline_id = next_outline.id
        return

    raise PipelineStateError("没有下一卷大纲（AI 自动生成下一卷在 volume-transition 任务实现）")
