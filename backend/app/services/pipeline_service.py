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

import json
import uuid

from sqlalchemy import delete, func, select
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

    # 建书阶段：若项目已有大纲则直接进入章节循环；否则保持在 BOOK 阶段，由后台循环自动一键建书。
    factory = await _session_factory_for(user_id)
    async with factory() as loop_db:
        loop_pipeline = await get_pipeline(loop_db, pipeline.id, user_id)
        outline = await loop_db.scalar(
            select(Outline).where(Outline.project_id == project_id).order_by(Outline.order_index).limit(1)
        )
        if outline is not None:
            loop_pipeline.current_stage = PipelineStage.CHAPTER_LOOP
            loop_pipeline.current_outline_id = outline.id
        else:
            loop_pipeline.current_stage = PipelineStage.BOOK
        await loop_db.commit()

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
    mode="content+outline"：同时重置受影响的大纲（骨架保留，卷过渡时重新规划）。
    """
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

    # 2) content+outline：重置受影响大纲的内容/结构（骨架保留，卷过渡时重新规划）
    if mode == "content+outline":
        affected_outline_ids = [c.outline_id for c in affected if c.outline_id]
        if affected_outline_ids:
            outlines_to_reset = list((await db.scalars(
                select(Outline).where(Outline.id.in_(affected_outline_ids))
            )).all())
            for outline in outlines_to_reset:
                outline.content = ""
                outline.structure = ""
                outline.updated_at = datetime.now()

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
                    # 一键建书：若项目还没有大纲，AI 生成第 1 卷大纲 + 章节骨架
                    existing = list((await db.scalars(
                        select(Outline).where(Outline.project_id == pipeline.project_id)
                        .order_by(Outline.order_index)
                    )).all())
                    cfg = pipeline.config_snapshot or {}
                    volume_chapters = int((cfg.get("volume_chapters") or 10))
                    if not existing:
                        try:
                            # 一键建书：先世界设定+角色，再卷1大纲+章节骨架（失败自动重试）
                            await _generate_world_and_characters(db, pipeline, user_id)
                            await _with_retry(
                                lambda: _generate_and_apply_new_volume(
                                    db, pipeline, user_id, existing, volume_chapters,
                                ),
                                retries=2, label="卷1大纲生成",
                            )
                            # 一键建书完成：标记项目向导状态为完成，避免点击项目被拉回向导页
                            project = await db.get(Project, pipeline.project_id)
                            if project is not None and project.wizard_status != "completed":
                                project.wizard_status = "completed"
                                project.wizard_step = 4
                        except PipelineStateError as exc:
                            pipeline.status = PipelineStatus.PAUSED
                            pipeline.last_error = f"一键建书失败：{exc}"
                            await db.commit()
                            return
                        await db.commit()
                        continue
                    pipeline.current_stage = PipelineStage.CHAPTER_LOOP
                    pipeline.current_outline_id = existing[0].id
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

                    # 预算统计与超限检查
                    await _update_budget(db, pipeline)
                    budget_exceeded = await _budget_exceeded(db, pipeline)
                    if budget_exceeded:
                        pipeline.status = PipelineStatus.PAUSED
                        pipeline.last_error = f"预算已用完（已用 ¥{pipeline.budget_used_amount_cents / 100:.2f}），流水线暂停；可在配置中加预算后继续"
                        await db.commit()
                        return

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


async def _update_budget(db: AsyncSession, pipeline: NovelPipeline) -> None:
    """根据 AI 调用日志汇总本流水线的 tokens 与估算费用。"""
    from sqlalchemy import func

    from app.models.ai_call_log import AICallLog
    from app.services.pricing import estimate_cost_cents

    trace_prefix = f"pipeline-{pipeline.id[:8]}"
    rows = list((await db.scalars(
        select(AICallLog).where(
            AICallLog.task_trace_id.like(f"{trace_prefix}%"),
            AICallLog.status == "success",
        )
    )).all())
    total_tokens = 0
    total_cents = 0
    for row in rows:
        pt = row.prompt_tokens or 0
        ct = row.completion_tokens or 0
        total_tokens += pt + ct
        total_cents += estimate_cost_cents(row.actual_model, pt, ct)
    pipeline.budget_used_tokens = total_tokens
    pipeline.budget_used_amount_cents = total_cents


async def _budget_exceeded(db: AsyncSession, pipeline: NovelPipeline) -> bool:
    """预算是否超限（金额上限或 token 上限，任一超限即暂停）。"""
    cfg = pipeline.config_snapshot or {}
    budget = cfg.get("budget") or {}
    max_cents = int(budget.get("max_amount_cents") or 0)
    max_tokens = int(budget.get("max_tokens") or 0)
    if max_cents > 0 and pipeline.budget_used_amount_cents >= max_cents:
        return True
    if max_tokens > 0 and pipeline.budget_used_tokens >= max_tokens:
        return True
    return False


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
    """卷过渡：当前卷写完 → AI 生成下一卷 Outline + 章节骨架，设为当前卷。

    生成 JSON：{title, summary, chapters: [{title, summary}]}，每卷章节数由配置
    volume_chapters 决定（默认 10）。
    """
    from app.api.outlines import _build_outline_continue_context
    from app.models.character import Character
    from app.services.prompt_service import PromptService
    from app.services.ai_provider_service import create_routed_ai_service
    from app.services.json_helper import loads_json

    project = await db.get(Project, pipeline.project_id)
    if project is None:
        raise PipelineStateError("项目不存在")

    cfg = pipeline.config_snapshot or {}
    vt_cfg = (cfg.get("models") or {}).get("volume_transition") or {}
    params = (cfg.get("params") or {}).get("volume_transition") or {}
    volume_chapters = int((cfg.get("volume_chapters") or 10))

    # 若当前卷存在但内容/结构为空（content+outline 回滚后），先重新规划它
    if pipeline.current_outline_id:
        current_outline = await db.get(Outline, pipeline.current_outline_id)
        if current_outline is not None and not (current_outline.structure or "").strip():
            await _regenerate_volume(db, pipeline, user_id, current_outline, volume_chapters)
            return

    # 已有大纲（作为续写上下文）
    outlines = list((await db.scalars(
        select(Outline).where(Outline.project_id == pipeline.project_id).order_by(Outline.order_index)
    )).all())
    characters = list((await db.scalars(
        select(Character).where(Character.project_id == pipeline.project_id)
    )).all())
    context = await _build_outline_continue_context(
        project=project,
        latest_outlines=outlines,
        characters=characters,
        chapter_count=volume_chapters,
        plot_stage="development",
        story_direction=cfg.get("volume_direction") or "自然延续",
        requirements=f"生成下一卷（第 {len(outlines) + 1} 卷）的大纲，共 {volume_chapters} 章",
        db=db,
    )
    start = len(outlines) + 1
    template = await PromptService.get_template("OUTLINE_CONTINUE", user_id, db)
    prompt = PromptService.format_prompt(
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
        chapter_count=volume_chapters,
        start_chapter=start,
        end_chapter=start + volume_chapters - 1,
        current_chapter_count=len(outlines),
        plot_stage_instruction="继续展开情节，深化角色关系",
        story_direction=cfg.get("volume_direction") or "自然延续",
        requirements=f"生成下一卷（第 {len(outlines) + 1} 卷）的大纲，共 {volume_chapters} 章",
        mcp_references="",
    )

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
    raw = result.get("content", "") if isinstance(result, dict) else str(result)
    data = loads_json(raw)
    # OUTLINE_CONTINUE 模板输出为章节 JSON 数组：[{title, summary}, ...]
    if isinstance(data, dict) and isinstance(data.get("chapters"), list):
        chapters = data["chapters"]
        volume_title = str(data.get("title") or f"卷 {len(outlines) + 1}")
        volume_summary = str(data.get("summary") or "")
    elif isinstance(data, list) and data:
        chapters = data
        volume_title = f"卷 {len(outlines) + 1}"
        volume_summary = ""
    else:
        raise PipelineStateError("下一卷大纲生成结果无法解析")
    if not isinstance(chapters, list) or not chapters:
        raise PipelineStateError("下一卷大纲未包含章节列表")

    # 建 Outline（=卷）+ 章节骨架
    # structure 需为字典（现有上下文服务读 structure.get('emotion') 等），卷级用 dict 包装
    new_outline = Outline(
        id=str(uuid.uuid4()),
        project_id=pipeline.project_id,
        title=volume_title,
        content=volume_summary or "\n\n".join(
            (ch.get("summary") if isinstance(ch, dict) else "") for ch in chapters[:volume_chapters]
        ),
        structure=json.dumps({
            "title": volume_title,
            "summary": volume_summary,
            "chapters": chapters[:volume_chapters],
        }, ensure_ascii=False),
        order_index=len(outlines) + 1,
    )
    db.add(new_outline)
    await db.flush()

    last_number = await db.scalar(
        select(func.max(Chapter.chapter_number)).where(Chapter.project_id == pipeline.project_id)
    ) or 0
    for i, ch in enumerate(chapters[:volume_chapters], start=1):
        ch_title = (ch.get("title") if isinstance(ch, dict) else None) or f"第 {last_number + i} 章"
        ch_summary = (ch.get("summary") if isinstance(ch, dict) else None) or ""
        ch_emotion = (ch.get("emotional_tone") or ch.get("emotion") if isinstance(ch, dict) else None) or ""
        db.add(Chapter(
            id=str(uuid.uuid4()),
            project_id=pipeline.project_id,
            chapter_number=last_number + i,
            title=ch_title,
            summary=ch_summary,
            status=ChapterStatus.PENDING,
            outline_id=new_outline.id,
            sub_index=i,
            expansion_plan=json.dumps({"summary": ch_summary, "emotional_tone": ch_emotion}, ensure_ascii=False),
        ))
    await db.flush()
    pipeline.current_outline_id = new_outline.id
    pipeline.current_stage = PipelineStage.CHAPTER_LOOP


async def _regenerate_volume(
    db: AsyncSession,
    pipeline: NovelPipeline,
    user_id: str,
    outline: Outline,
    volume_chapters: int,
) -> None:
    """重新规划一个空的卷 Outline（content+outline 回滚后调用）：AI 生成 → 更新大纲 + 重建章节骨架。"""
    from app.api.outlines import _build_outline_continue_context
    from app.models.character import Character
    from app.services.prompt_service import PromptService
    from app.services.ai_provider_service import create_routed_ai_service
    from app.services.json_helper import loads_json

    project = await db.get(Project, pipeline.project_id)
    if project is None:
        raise PipelineStateError("项目不存在")

    cfg = pipeline.config_snapshot or {}
    vt_cfg = (cfg.get("models") or {}).get("volume_transition") or {}
    params = (cfg.get("params") or {}).get("volume_transition") or {}

    outlines = list((await db.scalars(
        select(Outline).where(Outline.project_id == pipeline.project_id).order_by(Outline.order_index)
    )).all())
    characters = list((await db.scalars(
        select(Character).where(Character.project_id == pipeline.project_id)
    )).all())
    context = await _build_outline_continue_context(
        project=project,
        latest_outlines=outlines,
        characters=characters,
        chapter_count=volume_chapters,
        plot_stage="development",
        story_direction=cfg.get("volume_direction") or "自然延续",
        requirements=f"重新规划第 {outline.order_index} 卷的大纲，共 {volume_chapters} 章",
        db=db,
    )
    template = await PromptService.get_template("OUTLINE_CONTINUE", user_id, db)
    prompt = PromptService.format_prompt(
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
        chapter_count=volume_chapters,
        start_chapter=1,
        end_chapter=volume_chapters,
        current_chapter_count=len(outlines),
        plot_stage_instruction="继续展开情节，深化角色关系",
        story_direction=cfg.get("volume_direction") or "自然延续",
        requirements=f"重新规划第 {outline.order_index} 卷的大纲，共 {volume_chapters} 章",
        mcp_references="",
    )
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
    raw = result.get("content", "") if isinstance(result, dict) else str(result)
    data = loads_json(raw)
    if isinstance(data, dict) and isinstance(data.get("chapters"), list):
        chapters = data["chapters"]
        volume_title = str(data.get("title") or outline.title or f"卷 {outline.order_index}")
        volume_summary = str(data.get("summary") or "")
    elif isinstance(data, list) and data:
        chapters = data
        volume_title = outline.title or f"卷 {outline.order_index}"
        volume_summary = ""
    else:
        raise PipelineStateError("卷大纲重新规划结果无法解析")
    if not isinstance(chapters, list) or not chapters:
        raise PipelineStateError("卷大纲重新规划未包含章节列表")

    # 重建骨架：删除该卷旧的空骨架，按新规划重建
    await db.execute(
        delete(Chapter).where(
            Chapter.outline_id == outline.id,
            Chapter.project_id == pipeline.project_id,
        )
    )
    outline.content = volume_summary
    outline.structure = json.dumps({
        "title": volume_title,
        "summary": volume_summary,
        "chapters": chapters[:volume_chapters],
    }, ensure_ascii=False)
    outline.updated_at = datetime.now()

    last_number = await db.scalar(
        select(func.max(Chapter.chapter_number)).where(Chapter.project_id == pipeline.project_id)
    ) or 0
    for i, ch in enumerate(chapters[:volume_chapters], start=1):
        ch_title = (ch.get("title") if isinstance(ch, dict) else None) or f"第 {last_number + i} 章"
        ch_summary = (ch.get("summary") if isinstance(ch, dict) else None) or ""
        ch_emotion = (ch.get("emotional_tone") or ch.get("emotion") if isinstance(ch, dict) else None) or ""
        db.add(Chapter(
            id=str(uuid.uuid4()),
            project_id=pipeline.project_id,
            chapter_number=last_number + i,
            title=ch_title,
            summary=ch_summary,
            status=ChapterStatus.PENDING,
            outline_id=outline.id,
            sub_index=i,
            expansion_plan=json.dumps({"summary": ch_summary, "emotional_tone": ch_emotion}, ensure_ascii=False),
        ))
    await db.flush()
    pipeline.current_outline_id = outline.id
    pipeline.current_stage = PipelineStage.CHAPTER_LOOP


async def _generate_and_apply_new_volume(
    db: AsyncSession,
    pipeline: NovelPipeline,
    user_id: str,
    existing_outlines: list[Outline],
    volume_chapters: int,
) -> None:
    """AI 生成一卷新大纲并落地（Outline + 章节骨架），供建书阶段与卷过渡复用。"""
    from app.api.outlines import _build_outline_continue_context
    from app.models.character import Character
    from app.services.prompt_service import PromptService
    from app.services.ai_provider_service import create_routed_ai_service
    from app.services.json_helper import loads_json

    project = await db.get(Project, pipeline.project_id)
    if project is None:
        raise PipelineStateError("项目不存在")

    cfg = pipeline.config_snapshot or {}
    vt_cfg = (cfg.get("models") or {}).get("volume_transition") or {}
    params = (cfg.get("params") or {}).get("volume_transition") or {}

    characters = list((await db.scalars(
        select(Character).where(Character.project_id == pipeline.project_id)
    )).all())
    context = await _build_outline_continue_context(
        project=project,
        latest_outlines=existing_outlines,
        characters=characters,
        chapter_count=volume_chapters,
        plot_stage="development",
        story_direction=cfg.get("volume_direction") or "自然延续",
        requirements=f"生成第 {len(existing_outlines) + 1} 卷大纲，共 {volume_chapters} 章",
        db=db,
    )
    start = len(existing_outlines) + 1
    template = await PromptService.get_template("OUTLINE_CONTINUE", user_id, db)
    prompt = PromptService.format_prompt(
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
        chapter_count=volume_chapters,
        start_chapter=start,
        end_chapter=start + volume_chapters - 1,
        current_chapter_count=len(existing_outlines),
        plot_stage_instruction="继续展开情节，深化角色关系",
        story_direction=cfg.get("volume_direction") or "自然延续",
        requirements=f"生成第 {len(existing_outlines) + 1} 卷大纲，共 {volume_chapters} 章",
        mcp_references="",
    )
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
    raw = result.get("content", "") if isinstance(result, dict) else str(result)
    data = loads_json(raw)
    if isinstance(data, dict) and isinstance(data.get("chapters"), list):
        chapters = data["chapters"]
        volume_title = str(data.get("title") or f"卷 {len(existing_outlines) + 1}")
        volume_summary = str(data.get("summary") or "")
    elif isinstance(data, list) and data:
        chapters = data
        volume_title = f"卷 {len(existing_outlines) + 1}"
        volume_summary = ""
    else:
        raise PipelineStateError("卷大纲生成结果无法解析")
    if not isinstance(chapters, list) or not chapters:
        raise PipelineStateError("卷大纲未包含章节列表")

    new_outline = Outline(
        id=str(uuid.uuid4()),
        project_id=pipeline.project_id,
        title=volume_title,
        content=volume_summary or "\n\n".join(
            (ch.get("summary") if isinstance(ch, dict) else "") for ch in chapters[:volume_chapters]
        ),
        structure=json.dumps({
            "title": volume_title,
            "summary": volume_summary,
            "chapters": chapters[:volume_chapters],
        }, ensure_ascii=False),
        order_index=len(existing_outlines) + 1,
    )
    db.add(new_outline)
    await db.flush()

    last_number = await db.scalar(
        select(func.max(Chapter.chapter_number)).where(Chapter.project_id == pipeline.project_id)
    ) or 0
    for i, ch in enumerate(chapters[:volume_chapters], start=1):
        ch_title = (ch.get("title") if isinstance(ch, dict) else None) or f"第 {last_number + i} 章"
        ch_summary = (ch.get("summary") if isinstance(ch, dict) else None) or ""
        ch_emotion = (ch.get("emotional_tone") or ch.get("emotion") if isinstance(ch, dict) else None) or ""
        db.add(Chapter(
            id=str(uuid.uuid4()),
            project_id=pipeline.project_id,
            chapter_number=last_number + i,
            title=ch_title,
            summary=ch_summary,
            status=ChapterStatus.PENDING,
            outline_id=new_outline.id,
            sub_index=i,
            expansion_plan=json.dumps({"summary": ch_summary, "emotional_tone": ch_emotion}, ensure_ascii=False),
        ))
    await db.flush()
    pipeline.current_outline_id = new_outline.id
    pipeline.current_stage = PipelineStage.CHAPTER_LOOP


async def _generate_world_and_characters(db: AsyncSession, pipeline: NovelPipeline, user_id: str) -> None:
    """一键建书第 0 步：若项目缺世界设定/角色，先自动生成（非 SSE）。"""
    from app.models.character import Character
    from app.services.prompt_service import PromptService
    from app.services.ai_provider_service import create_routed_ai_service
    from app.services.json_helper import loads_json

    project = await db.get(Project, pipeline.project_id)
    if project is None:
        return

    cfg = pipeline.config_snapshot or {}
    book_cfg = (cfg.get("models") or {}).get("book") or {}
    params = (cfg.get("params") or {}).get("book") or {}

    # 1) 世界设定：world_* 字段为空才生成
    needs_world = not (project.world_time_period or "").strip()
    if needs_world:
        template = await PromptService.get_template("WORLD_BUILDING", user_id, db)
        prompt = PromptService.format_prompt(
            template,
            title=project.title or "未命名",
            theme=project.theme or "未设定",
            genre=project.genre or "通用类型",
            description=project.description or "暂无简介",
        )
        service = await create_routed_ai_service(
            db, user_id=user_id, usage_type="world_building",
            provider_config_id=book_cfg.get("provider_config_id"), model=book_cfg.get("model"),
            project_id=pipeline.project_id, task_trace_id=f"pipeline-{pipeline.id[:8]}", enable_mcp=False,
        )
        result = await service.generate_text(
            prompt=prompt, temperature=params.get("temperature", 0.8),
            max_tokens=params.get("max_tokens", 32000), auto_mcp=False,
        )
        raw = result.get("content", "") if isinstance(result, dict) else str(result)
        world = loads_json(raw)
        if isinstance(world, dict):
            project.world_time_period = world.get("time_period") or project.world_time_period
            project.world_location = world.get("location") or project.world_location
            project.world_atmosphere = world.get("atmosphere") or project.world_atmosphere
            project.world_rules = world.get("rules") or project.world_rules
            await db.flush()

    # 2) 角色：项目无角色才生成
    existing_chars = await db.scalar(
        select(func.count(Character.id)).where(Character.project_id == pipeline.project_id)
    ) or 0
    if existing_chars > 0:
        return
    count = int((cfg.get("character_count") or 5))
    template = await PromptService.get_template("CHARACTERS_BATCH_GENERATION", user_id, db)
    prompt = PromptService.format_prompt(
        template,
        title=project.title or "未命名",
        theme=project.theme or "未设定",
        genre=project.genre or "通用",
        count=count,
        time_period=project.world_time_period or "未设定",
        location=project.world_location or "未设定",
        atmosphere=project.world_atmosphere or "未设定",
        rules=project.world_rules or "未设定",
        narrative_perspective=project.narrative_perspective or "第三人称",
        requirements="",
    )
    service = await create_routed_ai_service(
        db, user_id=user_id, usage_type="character",
        provider_config_id=book_cfg.get("provider_config_id"), model=book_cfg.get("model"),
        project_id=pipeline.project_id, task_trace_id=f"pipeline-{pipeline.id[:8]}", enable_mcp=False,
    )
    result = await service.generate_text(
        prompt=prompt, temperature=params.get("temperature", 0.8),
        max_tokens=params.get("max_tokens", 32000), auto_mcp=False,
    )
    raw = result.get("content", "") if isinstance(result, dict) else str(result)
    data = loads_json(raw)
    chars = data if isinstance(data, list) else data.get("characters", []) if isinstance(data, dict) else []
    for c in chars[: count + 3]:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        db.add(Character(
            id=str(uuid.uuid4()),
            project_id=pipeline.project_id,
            name=c.get("name"),
            age=str(c.get("age") or "") if c.get("age") else None,
            gender=c.get("gender"),
            role_type=c.get("role_type") or "supporting",
            personality=c.get("personality") or "",
            background=c.get("backstory") or c.get("background") or "",
            appearance=c.get("appearance") or "",
        ))
    await db.flush()


async def _with_retry(coro_factory, *, retries: int = 2, label: str = "生成"):
    """带重试地执行一个异步操作（供应商偶发失败时自动重试）。"""
    import asyncio as _asyncio

    last_exc = None
    for attempt in range(retries + 1):
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                logger.warning(f"{label}失败（第{attempt + 1}次）：{exc}，{_asyncio.sleep and 8 * (attempt + 1)}秒后重试")
                await _asyncio.sleep(8 * (attempt + 1))
    raise last_exc  # type: ignore[misc]
