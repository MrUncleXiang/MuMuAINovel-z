"""章节管理API"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
import json
import asyncio
from typing import List, Optional
from datetime import datetime, timedelta
from asyncio import Queue, Lock

from app.database import get_db, get_engine
from app.api.common import verify_project_access
from app.services.chapter_context_service import (
    OneToManyContextBuilder,
    OneToOneContextBuilder
)
from app.models.chapter import Chapter
from app.models.project import Project
from app.models.outline import Outline
from app.models.character import Character
from app.models.career import Career, CharacterCareer
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.models.writing_style import WritingStyle
from app.models.analysis_task import AnalysisTask
from app.models.memory import PlotAnalysis, StoryMemory
from app.models.batch_generation_task import BatchGenerationTask
from app.models.regeneration_task import RegenerationTask
from app.models.background_task import BackgroundTask
from app.models.generation_history import GenerationHistory
from app.schemas.llm_comparison import LLMComparisonSelection
from app.schemas.chapter import (
    ChapterCreate,
    ChapterUpdate,
    ChapterResponse,
    ChapterListResponse,
    AnalysisTaskStatusResponse,
    BatchAnalysisStatusRequest,
    BatchAnalysisStatusResponse,
    BatchAnalyzeUnanalyzedRequest,
    BatchAnalyzeUnanalyzedResponse,
    ChapterAnalysisRequest,
    ChapterGenerateRequest,
    ChapterAIEditRequest,
    ChapterComparisonCreateRequest,
    ChapterCandidateEditRequest,
    AnalysisComparisonCreateRequest,
    BatchGenerateRequest,
    BatchGenerateResponse,
    VolumeReviewRequest,
    BatchGenerateStatusResponse,
    ExpansionPlanUpdate,
    PartialRegenerateRequest
)
from app.schemas.regeneration import (
    ChapterRegenerateRequest,
    RegenerationTaskResponse,
    RegenerationTaskStatus
)
from app.services.ai_service import AIService
from app.services.prompt_service import prompt_service, PromptService, WritingStyleManager
from app.services.plot_analyzer import PlotAnalyzer
from app.services.memory_service import memory_service
from app.services.foreshadow_service import foreshadow_service
from app.services.chapter_regenerator import ChapterRegenerator
from app.logger import get_logger
from app.api.settings import get_user_ai_service
from app.services.ai_provider_service import create_routed_ai_service
from app.models.llm_comparison import LLMComparisonBatch
from app.models.llm_comparison import LLMComparisonCandidate
from app.schemas.llm_comparison import LLMComparisonBatchResponse, LLMComparisonCandidateResponse
from app.services.chapter_comparison_service import (
    apply_chapter_candidate,
    create_chapter_comparison,
    generate_chapter_candidate,
)
from app.services.llm_comparison_service import (
    ComparisonNotFoundError,
    ComparisonStateError,
    adopt_candidate,
    get_owned_batch,
    list_candidates,
    retry_candidate,
    run_batch,
)
from app.services.analysis_comparison_service import (
    apply_analysis_candidate,
    create_analysis_comparison,
    generate_analysis_candidate,
)
from app.services.project_creation_config_service import freeze_project_creation_config
from app.services.chapter_lifecycle_service import (
    analysis_task_matches_content,
    chapter_content_hash,
    check_previous_analysis_ready,
    create_pending_analysis_task,
)
from app.services.chapter_analysis_materialization_service import (
    materialize_chapter_analysis,
)
from app.services.chapter_analysis_context_service import (
    build_chapter_analysis_context,
    build_characters_info_with_careers,
)
from app.services.formal_chapter_service import (
    FormalChapterConflictError,
    build_lightweight_chapter_summary as _build_lightweight_chapter_summary,
    prepare_chapter_content_replacement,
    persist_formal_chapter_content,
)
from app.utils.sse_response import SSEResponse, create_sse_response

router = APIRouter(prefix="/chapters", tags=["章节管理"])
logger = get_logger(__name__)

# 全局数据库写入锁（每个用户一个锁，用于保护SQLite写入操作）
db_write_locks: dict[str, Lock] = {}
analysis_background_tasks: set[asyncio.Task] = set()
comparison_background_tasks: set[asyncio.Task] = set()

ANALYSIS_TASK_TIMEOUT_SECONDS = 600
ANALYSIS_TASK_STALE_SECONDS = 720


def _schedule_analysis_background(coroutine) -> asyncio.Task:
    """持有后台任务引用，直到任务结束。"""
    task = asyncio.create_task(coroutine)
    analysis_background_tasks.add(task)
    task.add_done_callback(analysis_background_tasks.discard)
    return task


def _schedule_comparison_background(coroutine) -> asyncio.Task:
    """持有多模型生成任务引用，避免请求结束后被回收。"""
    task = asyncio.create_task(coroutine)
    comparison_background_tasks.add(task)
    task.add_done_callback(comparison_background_tasks.discard)
    return task


async def _chapter_comparison_response(db: AsyncSession, batch: LLMComparisonBatch) -> LLMComparisonBatchResponse:
    candidates = await list_candidates(db, batch.id)
    return LLMComparisonBatchResponse(
        id=batch.id,
        project_id=batch.project_id,
        target_type=batch.target_type,
        target_id=batch.target_id,
        usage_type=batch.usage_type,
        status=batch.status,
        input_snapshot=batch.input_snapshot or {},
        prompt_snapshot=batch.prompt_snapshot,
        parameters_snapshot=batch.parameters_snapshot or {},
        adopted_candidate_id=batch.adopted_candidate_id,
        candidates=[LLMComparisonCandidateResponse.model_validate(item) for item in candidates],
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        completed_at=batch.completed_at,
    )


async def get_db_write_lock(user_id: str) -> Lock:
    """获取或创建用户的数据库写入锁"""
    if user_id not in db_write_locks:
        db_write_locks[user_id] = Lock()
        logger.debug(f"🔒 为用户 {user_id} 创建数据库写入锁")
    return db_write_locks[user_id]


async def _set_analysis_task_terminal_state(
    user_id: str,
    task_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> bool:
    """使用独立事务写入终态，避免分析会话失败后无法更新任务。"""
    engine = await get_engine(user_id)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    completed_at = datetime.now()

    for attempt in range(1, 4):
        async with session_factory() as terminal_db:
            try:
                result = await terminal_db.execute(
                    update(AnalysisTask)
                    .where(
                        AnalysisTask.id == task_id,
                        AnalysisTask.status.in_(["pending", "running"]),
                    )
                    .values(
                        status=status,
                        progress=100 if status == "completed" else 0,
                        error_message=error_message if status == "failed" else None,
                        completed_at=completed_at,
                        materialized_at=completed_at if status == "completed" else None,
                    )
                )
                await terminal_db.commit()
                if result.rowcount == 0:
                    logger.info(f"分析任务已处于终态，无需重复更新: {task_id}")
                    return False
                return True
            except Exception as exc:
                await terminal_db.rollback()
                logger.error(f"更新分析任务终态失败({attempt}/3): {task_id}, {exc}")
                if attempt < 3:
                    await asyncio.sleep(0.1)

    return False


@router.post("", response_model=ChapterResponse, summary="创建章节")
async def create_chapter(
    chapter: ChapterCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """创建新的章节"""
    # 验证用户权限和项目是否存在
    user_id = getattr(request.state, 'user_id', None)
    project = await verify_project_access(chapter.project_id, user_id, db)
    
    # 计算字数(处理content可能为None的情况)
    word_count = len(chapter.content) if chapter.content else 0
    
    db_chapter = Chapter(
        **chapter.model_dump(),
        word_count=word_count
    )
    db.add(db_chapter)
    
    # 更新项目的当前字数
    project.current_words = project.current_words + word_count
    
    await db.commit()
    await db.refresh(db_chapter)
    return db_chapter


@router.get("/project/{project_id}", response_model=ChapterListResponse, summary="获取项目的所有章节")
async def get_project_chapters(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    include_content: bool = True,
):
    """获取指定项目的所有章节（带大纲信息）

    include_content=False 时 content 置 None（轻量目录模式，正文按章单独加载）。
    默认 True 保持全量返回，现有调用方不受影响。
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    # 获取总数
    count_result = await db.execute(
        select(func.count(Chapter.id)).where(Chapter.project_id == project_id)
    )
    total = count_result.scalar_one()
    
    # 获取章节列表，同时加载关联的大纲信息
    result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_number)
    )
    chapters = result.scalars().all()
    
    # 获取所有大纲信息（用于填充outline_title）
    outline_ids = [ch.outline_id for ch in chapters if ch.outline_id]
    outlines_map = {}
    if outline_ids:
        outlines_result = await db.execute(
            select(Outline).where(Outline.id.in_(outline_ids))
        )
        outlines_map = {o.id: o for o in outlines_result.scalars().all()}
    
    # 为所有章节添加大纲信息（统一处理）
    chapters_with_outline = []
    for chapter in chapters:
        chapter_dict = {
            "id": chapter.id,
            "project_id": chapter.project_id,
            "chapter_number": chapter.chapter_number,
            "title": chapter.title,
            "content": chapter.content if include_content else None,
            "summary": chapter.summary,
            "word_count": chapter.word_count,
            "status": chapter.status,
            "outline_id": chapter.outline_id,
            "sub_index": chapter.sub_index,
            "expansion_plan": chapter.expansion_plan,
            "created_at": chapter.created_at,
            "updated_at": chapter.updated_at,
        }
        
        # 添加大纲信息
        if chapter.outline_id and chapter.outline_id in outlines_map:
            outline = outlines_map[chapter.outline_id]
            chapter_dict["outline_title"] = outline.title
            chapter_dict["outline_order"] = outline.order_index
        else:
            chapter_dict["outline_title"] = None
            chapter_dict["outline_order"] = None
        
        chapters_with_outline.append(chapter_dict)
    
    return ChapterListResponse(total=total, items=chapters_with_outline)


@router.get("/{chapter_id}", response_model=ChapterResponse, summary="获取章节详情")
async def get_chapter(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """根据ID获取章节详情"""
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    return chapter


@router.get("/{chapter_id}/navigation", summary="获取章节导航信息")
async def get_chapter_navigation(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    获取章节的导航信息（上一章/下一章）
    用于章节阅读器的翻页功能
    """
    # 获取当前章节
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    current_chapter = result.scalar_one_or_none()
    
    if not current_chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(current_chapter.project_id, user_id, db)
    
    # 获取上一章
    prev_result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == current_chapter.project_id)
        .where(Chapter.chapter_number < current_chapter.chapter_number)
        .order_by(Chapter.chapter_number.desc())
        .limit(1)
    )
    prev_chapter = prev_result.scalar_one_or_none()
    
    # 获取下一章
    next_result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == current_chapter.project_id)
        .where(Chapter.chapter_number > current_chapter.chapter_number)
        .order_by(Chapter.chapter_number.asc())
        .limit(1)
    )
    next_chapter = next_result.scalar_one_or_none()
    
    return {
        "current": {
            "id": current_chapter.id,
            "chapter_number": current_chapter.chapter_number,
            "title": current_chapter.title
        },
        "previous": {
            "id": prev_chapter.id,
            "chapter_number": prev_chapter.chapter_number,
            "title": prev_chapter.title
        } if prev_chapter else None,
        "next": {
            "id": next_chapter.id,
            "chapter_number": next_chapter.chapter_number,
            "title": next_chapter.title
        } if next_chapter else None
    }


@router.put("/{chapter_id}", response_model=ChapterResponse, summary="更新章节")
async def update_chapter(
    chapter_id: str,
    chapter_update: ChapterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新章节信息"""
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 记录旧字数
    old_word_count = chapter.word_count or 0
    
    # 更新字段
    update_data = chapter_update.model_dump(exclude_unset=True)
    if "content" in update_data:
        try:
            await prepare_chapter_content_replacement(
                db=db,
                chapter=chapter,
                new_content=update_data["content"],
                user_id=user_id,
                memory_service=memory_service,
            )
        except FormalChapterConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    for field, value in update_data.items():
        setattr(chapter, field, value)
    
    # 如果内容更新了，重新计算字数（包括清空内容的情况）
    if "content" in update_data:
        new_word_count = len(chapter.content) if chapter.content else 0
        chapter.word_count = new_word_count
        
        # 更新项目字数
        result = await db.execute(
            select(Project).where(Project.id == chapter.project_id)
        )
        project = result.scalar_one_or_none()
        if project:
            project.current_words = project.current_words - old_word_count + new_word_count
        
        # 如果内容被清空，清理相关数据
            if not chapter.content or chapter.content.strip() == "":
                chapter.status = "draft"
                
                # 清理分析任务
                analysis_tasks_result = await db.execute(
                    select(AnalysisTask).where(AnalysisTask.chapter_id == chapter_id)
                )
                analysis_tasks = analysis_tasks_result.scalars().all()
                for task in analysis_tasks:
                    await db.delete(task)
                
                # 清理分析结果
                plot_analysis_result = await db.execute(
                    select(PlotAnalysis).where(PlotAnalysis.chapter_id == chapter_id)
                )
                plot_analyses = plot_analysis_result.scalars().all()
                for analysis in plot_analyses:
                    await db.delete(analysis)
                
                # 清理故事记忆（关系数据库）
                story_memories_result = await db.execute(
                    select(StoryMemory).where(StoryMemory.chapter_id == chapter_id)
                )
                story_memories = story_memories_result.scalars().all()
                for memory in story_memories:
                    await db.delete(memory)
                
                # 清理向量数据库中的记忆数据
                try:
                    await memory_service.delete_chapter_memories(
                        user_id=user_id,
                        project_id=chapter.project_id,
                        chapter_id=chapter_id
                    )
                    logger.info(f"✅ 已清理章节 {chapter_id[:8]} 的向量记忆数据")
                except Exception as e:
                    logger.warning(f"⚠️ 清理向量记忆数据失败: {str(e)}")
                
                # 🔮 清理章节相关的分析伏笔数据
                try:
                    foreshadow_result = await foreshadow_service.delete_chapter_foreshadows(
                        db=db,
                        project_id=chapter.project_id,
                        chapter_id=chapter_id,
                        only_analysis_source=True  # 只删除分析来源的伏笔，保留手动创建的
                    )
                    if foreshadow_result['deleted_count'] > 0:
                        logger.info(f"🔮 已清理章节 {chapter_id[:8]} 的 {foreshadow_result['deleted_count']} 个伏笔数据")
                except Exception as e:
                    logger.warning(f"⚠️ 清理伏笔数据失败: {str(e)}")
                
                logger.info(f"🗑️ 章节 {chapter_id[:8]} 内容已清空，已清理分析、记忆和伏笔数据")
    
    await db.commit()
    await db.refresh(chapter)
    
    chapter_dict = {
        "id": chapter.id,
        "project_id": chapter.project_id,
        "chapter_number": chapter.chapter_number,
        "title": chapter.title,
        "content": chapter.content,
        "summary": chapter.summary,
        "word_count": chapter.word_count,
        "status": chapter.status,
        "outline_id": chapter.outline_id,
        "sub_index": chapter.sub_index,
        "expansion_plan": chapter.expansion_plan,
        "created_at": chapter.created_at,
        "updated_at": chapter.updated_at,
        "outline_title": None,
        "outline_order": None
    }
    
    # 如果章节关联了大纲，查询大纲信息
    if chapter.outline_id:
        outline_result = await db.execute(
            select(Outline).where(Outline.id == chapter.outline_id)
        )
        outline = outline_result.scalar_one_or_none()
        if outline:
            chapter_dict["outline_title"] = outline.title
            chapter_dict["outline_order"] = outline.order_index
    
    return chapter_dict


@router.delete("/project/{project_id}", summary="删除项目全部章节")
async def delete_all_chapters(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """删除项目全部章节（保留大纲），逐章复用清理逻辑：字数/向量记忆/伏笔"""
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)

    chapters = list((await db.scalars(
        select(Chapter).where(Chapter.project_id == project_id)
    )).all())
    if not chapters:
        return {"message": "没有可删除的章节", "deleted_count": 0}

    # 更新项目字数（汇总扣减）
    total_words = sum(ch.word_count or 0 for ch in chapters)
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project and total_words > 0:
        project.current_words = max(0, (project.current_words or 0) - total_words)

    deleted_count = 0
    for chapter in chapters:
        # 🗑️ 清理向量记忆（失败不阻断）
        try:
            await memory_service.delete_chapter_memories(
                user_id=user_id, project_id=project_id, chapter_id=chapter.id
            )
        except Exception as e:
            logger.warning(f"⚠️ 清理章节 {chapter.id[:8]} 向量记忆失败: {e}")
        # 🔮 清理分析来源伏笔（失败不阻断）
        try:
            await foreshadow_service.delete_chapter_foreshadows(
                db=db, project_id=project_id, chapter_id=chapter.id,
                only_analysis_source=True
            )
        except Exception as e:
            logger.warning(f"⚠️ 清理章节 {chapter.id[:8]} 伏笔失败: {e}")
        await db.delete(chapter)
        deleted_count += 1

    await db.commit()
    logger.info(f"🗑️ 已删除项目 {project_id} 的全部 {deleted_count} 个章节（保留大纲）")
    return {"message": f"已删除全部 {deleted_count} 个章节", "deleted_count": deleted_count}


@router.delete("/{chapter_id}", summary="删除章节")
async def delete_chapter(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """删除章节"""
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 更新项目字数
    result = await db.execute(
        select(Project).where(Project.id == chapter.project_id)
    )
    project = result.scalar_one_or_none()
    if project:
        # 处理 word_count 和 current_words 可能为 None 的情况
        chapter_word_count = chapter.word_count or 0
        project.current_words = max(0, (project.current_words or 0) - chapter_word_count)
    
    # 🗑️ 清理向量数据库中的记忆数据
    try:
        await memory_service.delete_chapter_memories(
            user_id=user_id,
            project_id=chapter.project_id,
            chapter_id=chapter_id
        )
        logger.info(f"✅ 已清理章节 {chapter_id[:8]} 的向量记忆数据")
    except Exception as e:
        logger.warning(f"⚠️ 清理向量记忆数据失败: {str(e)}")
        # 不阻断删除流程，继续执行
    
    # 🔮 清理与该章节相关的伏笔数据（仅分析来源的伏笔）
    try:
        foreshadow_result = await foreshadow_service.delete_chapter_foreshadows(
            db=db,
            project_id=chapter.project_id,
            chapter_id=chapter_id,
            only_analysis_source=True  # 只删除分析来源的伏笔，保留手动创建的
        )
        if foreshadow_result['deleted_count'] > 0:
            logger.info(f"🔮 已清理章节 {chapter_id[:8]} 的 {foreshadow_result['deleted_count']} 个伏笔数据")
    except Exception as e:
        logger.warning(f"⚠️ 清理伏笔数据失败: {str(e)}")
        # 不阻断删除流程，继续执行
    
    # 删除章节（关系数据库中的记忆会被级联删除）
    await db.delete(chapter)
    await db.commit()
    
    return {"message": "章节删除成功"}


async def check_prerequisites(db: AsyncSession, chapter: Chapter) -> tuple[bool, str, list[Chapter]]:
    """
    检查章节前置条件
    
    Args:
        db: 数据库会话
        chapter: 当前章节
        
    Returns:
        (可否生成, 错误信息, 前置章节列表)
    """
    # 如果是第一章，无需检查前置
    if chapter.chapter_number == 1:
        return True, "", []
    
    # 查询所有前置章节（序号小于当前章节的）
    result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == chapter.project_id)
        .where(Chapter.chapter_number < chapter.chapter_number)
        .order_by(Chapter.chapter_number)
    )
    previous_chapters = result.scalars().all()
    
    # 检查是否所有前置章节都有内容
    incomplete_chapters = [
        ch for ch in previous_chapters
        if not ch.content or ch.content.strip() == ""
    ]
    
    if incomplete_chapters:
        missing_numbers = [str(ch.chapter_number) for ch in incomplete_chapters]
        error_msg = f"需要先完成前置章节：第 {', '.join(missing_numbers)} 章"
        return False, error_msg, previous_chapters
    
    return True, "", previous_chapters


@router.get("/{chapter_id}/can-generate", summary="检查章节是否可以生成")
async def check_can_generate(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    检查章节是否满足生成条件
    返回可生成状态和前置章节信息
    """
    # 获取章节
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 检查前置条件
    can_generate, error_msg, previous_chapters = await check_prerequisites(db, chapter)
    
    # 构建前置章节信息
    previous_info = [
        {
            "id": ch.id,
            "chapter_number": ch.chapter_number,
            "title": ch.title,
            "has_content": bool(ch.content and ch.content.strip()),
            "word_count": ch.word_count or 0
        }
        for ch in previous_chapters
    ]
    
    return {
        "can_generate": can_generate,
        "reason": error_msg if not can_generate else "",
        "previous_chapters": previous_info,
        "chapter_number": chapter.chapter_number
    }


async def analyze_chapter_background(
    chapter_id: str,
    user_id: str,
    project_id: str,
    task_id: str,
    ai_service: Optional[AIService] = None,
    provider_config_id: Optional[str] = None,
    model: Optional[str] = None,
    enable_mcp: bool = True,
    allowed_mcp_plugin_ids: Optional[list[str]] = None,
) -> bool:
    """执行有硬超时保障的章节分析，并确保中断后任务进入终态。"""
    try:
        return await asyncio.wait_for(
            _analyze_chapter_background_impl(
                chapter_id=chapter_id,
                user_id=user_id,
                project_id=project_id,
                task_id=task_id,
                ai_service=ai_service,
                provider_config_id=provider_config_id,
                model=model,
                enable_mcp=enable_mcp,
                allowed_mcp_plugin_ids=allowed_mcp_plugin_ids,
            ),
            timeout=ANALYSIS_TASK_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        error_message = f"分析任务超时（超过{ANALYSIS_TASK_TIMEOUT_SECONDS // 60}分钟）"
        logger.error(f"❌ {error_message}: chapter_id={chapter_id}, task_id={task_id}")
        await _set_analysis_task_terminal_state(user_id, task_id, "failed", error_message)
        return False
    except asyncio.CancelledError:
        terminal_update = asyncio.create_task(
            _set_analysis_task_terminal_state(
                user_id,
                task_id,
                "failed",
                "分析任务被取消或服务关闭",
            )
        )
        await asyncio.shield(terminal_update)
        raise


async def _analyze_chapter_background_impl(
    chapter_id: str,
    user_id: str,
    project_id: str,
    task_id: str,
    ai_service: Optional[AIService] = None,
    provider_config_id: Optional[str] = None,
    model: Optional[str] = None,
    enable_mcp: bool = True,
    allowed_mcp_plugin_ids: Optional[list[str]] = None,
) -> bool:
    """
    后台异步分析章节（支持并发，使用锁保护数据库写入）
    
    Args:
        chapter_id: 章节ID
        user_id: 用户ID
        project_id: 项目ID
        task_id: 任务ID
        ai_service: AI服务实例
        
    Returns:
        bool: True表示分析成功，False表示分析失败
    """
    db_session = None
    write_lock = await get_db_write_lock(user_id)
    
    try:
        logger.info(f"🔍 开始分析章节: {chapter_id}, 任务ID: {task_id}")
        
        # 创建独立数据库会话
        from app.database import get_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        
        engine = await get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        db_session = AsyncSessionLocal()
        
        # 1. 获取任务（读操作）
        task_result = await db_session.execute(
            select(AnalysisTask).where(AnalysisTask.id == task_id)
        )
        task = task_result.scalar_one_or_none()
        
        if not task:
            logger.error(f"❌ 任务不存在: {task_id}")
            return False
        if task.status not in ("pending", "running"):
            logger.warning(f"分析任务已结束，跳过执行: {task_id}, status={task.status}")
            return False
        
        # 更新任务状态（写操作，需要锁）
        async with write_lock:
            task.status = 'running'
            task.started_at = datetime.now()
            task.progress = 10
            await db_session.commit()
        
        # 2. 获取章节信息（读操作）
        chapter_result = await db_session.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        chapter = chapter_result.scalar_one_or_none()
        if not chapter or not chapter.content:
            async with write_lock:
                task.status = 'failed'
                task.error_message = '章节不存在或内容为空'
                task.completed_at = datetime.now()
                await db_session.commit()
            logger.error(f"❌ 章节不存在或内容为空: {chapter_id}")
            return False
        if not analysis_task_matches_content(task, chapter):
            async with write_lock:
                task.status = "failed"
                task.error_message = "章节正文已变化，请基于当前正文重新分析"
                task.completed_at = datetime.now()
                await db_session.commit()
            logger.warning(f"分析任务对应的正文已过期: chapter_id={chapter_id}, task_id={task_id}")
            return False
        
        async with write_lock:
            task.progress = 20
            await db_session.commit()
        
        if ai_service is None:
            ai_service = await create_routed_ai_service(
                db=db_session,
                user_id=user_id,
                usage_type="chapter_analysis",
                provider_config_id=provider_config_id,
                model=model,
                task_trace_id=task_id,
                project_id=project_id,
                chapter_id=chapter_id,
                enable_mcp=enable_mcp,
                allowed_mcp_plugin_ids=allowed_mcp_plugin_ids,
            )

        analysis_context = await build_chapter_analysis_context(
            db=db_session,
            chapter=chapter,
            foreshadow_service=foreshadow_service,
        )
        
        # 定义重试回调函数，用于在重试时更新任务状态
        last_fail_reason = {"msg": ""}
        async def on_retry_callback(attempt: int, max_retries: int, wait_time: int, error_reason: str):
            """重试时更新任务状态，让前端能感知到重试进度"""
            last_fail_reason["msg"] = error_reason
            try:
                async with write_lock:
                    # 重新获取任务（确保获取最新状态）
                    task_result_retry = await db_session.execute(
                        select(AnalysisTask).where(AnalysisTask.id == task_id)
                    )
                    task_retry = task_result_retry.scalar_one_or_none()
                    if task_retry:
                        # 更新任务状态，保持 running 但更新 started_at 以重置超时计时器
                        task_retry.status = 'running'
                        task_retry.started_at = datetime.now()  # 重置开始时间，防止超时检测误判
                        task_retry.progress = 25 + attempt * 5  # 根据重试次数更新进度
                        task_retry.error_message = f"正在重试({attempt}/{max_retries})：{error_reason[:100]}"
                        await db_session.commit()
                        logger.info(f"🔄 分析任务重试状态已更新: 尝试 {attempt}/{max_retries}, 等待 {wait_time}s, 原因: {error_reason[:50]}...")
            except Exception as callback_error:
                logger.warning(f"⚠️ 更新重试状态失败: {callback_error}")
        
        # 3. 使用PlotAnalyzer分析章节（传入已有伏笔列表、角色信息和重试回调）
        analyzer = PlotAnalyzer(ai_service)
        analysis_result = await analyzer.analyze_chapter(
            chapter_number=chapter.chapter_number,
            title=chapter.title,
            content=chapter.content,
            word_count=chapter.word_count or len(chapter.content),
            user_id=user_id,
            db=db_session,
            existing_foreshadows=analysis_context.existing_foreshadows,
            on_retry=on_retry_callback,
            characters_info=analysis_context.characters_info
        )

        # 3b. 兜底重试：主模型（常为 flash）失败 → 用 chapter_analysis 路由（pro）再完整分析一次
        if not analysis_result:
            fallback_reason = last_fail_reason.get("msg", "")
            logger.warning(f"🔄 主模型分析失败（{fallback_reason[:80]}），尝试 pro 兜底重试...")
            try:
                from app.services.ai_provider_service import create_routed_ai_service as _cras
                fallback_ai = await _cras(
                    db=db_session, user_id=user_id, usage_type="chapter_analysis",
                    task_trace_id=task_id, project_id=project_id,
                    chapter_id=chapter_id, enable_mcp=False,
                )
                fallback_analyzer = PlotAnalyzer(fallback_ai)
                fallback_result = await fallback_analyzer.analyze_chapter(
                    chapter_number=chapter.chapter_number,
                    title=chapter.title,
                    content=chapter.content,
                    word_count=chapter.word_count or len(chapter.content),
                    user_id=user_id,
                    db=db_session,
                    existing_foreshadows=analysis_context.existing_foreshadows,
                    on_retry=on_retry_callback,
                    characters_info=analysis_context.characters_info
                )
                if fallback_result:
                    logger.info("✅ pro 兜底分析成功，采用兜底结果")
                    analysis_result = fallback_result
            except Exception as fb_err:
                logger.warning(f"⚠️ pro 兜底分析失败: {fb_err}")
        
        if not analysis_result:
            async with write_lock:
                task.status = 'failed'
                reason = last_fail_reason.get("msg", "")
                task.error_message = (
                    f"AI分析失败：{reason[:120]}"
                    if reason else "AI分析失败（多次尝试均未得到有效结果）"
                ) + "。可关闭后重新分析，或在弹窗中选择更强模型（如 deepseek-v4-pro）。"
                task.completed_at = datetime.now()
                await db_session.commit()
            logger.error(f"❌ AI分析失败: {chapter_id}，原因: {reason}")
            return False

        # LLM 调用期间用户可能编辑正文；过期结果绝不能写入正式状态。
        await db_session.refresh(chapter)
        if not analysis_task_matches_content(task, chapter):
            async with write_lock:
                task.status = "failed"
                task.error_message = "分析期间章节正文发生变化，请重新分析"
                task.completed_at = datetime.now()
                await db_session.commit()
            logger.warning(f"丢弃过期分析结果: chapter_id={chapter_id}, task_id={task_id}")
            return False
        
        async with write_lock:
            materialization = await materialize_chapter_analysis(
                db=db_session,
                user_id=user_id,
                chapter=chapter,
                task=task,
                analysis=analysis_result,
                analyzer=analyzer,
                memory_service=memory_service,
                foreshadow_service=foreshadow_service,
            )

        if materialization.already_materialized:
            logger.info(f"章节分析已由同一正文的其他任务完成: {chapter_id}")
        else:
            logger.info(
                f"✅ 章节分析完成: {chapter_id}, "
                f"提取{materialization.memory_count}条记忆"
            )
        return True
        
    except Exception as e:
        logger.error(f"❌ 后台分析异常: {str(e)}", exc_info=True)
        if db_session:
            try:
                await db_session.rollback()
            except Exception as rollback_error:
                logger.warning(f"回滚分析事务失败: {rollback_error}")
        await _set_analysis_task_terminal_state(
            user_id, task_id, "failed", str(e)[:500]
        )
        return False
        
    finally:
        if db_session:
            await db_session.close()


@router.post("/{chapter_id}/analysis-comparison-batches", response_model=LLMComparisonBatchResponse, summary="创建多模型分析候选")
async def create_analysis_comparison_batch(chapter_id: str, payload: AnalysisComparisonCreateRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = getattr(request.state, "user_id", None)
    chapter = await db.scalar(select(Chapter).where(Chapter.id == chapter_id))
    if chapter is None or not chapter.content:
        raise HTTPException(status_code=400, detail="章节不存在或正文为空")
    await verify_project_access(chapter.project_id, user_id, db)
    batch, _ = await create_analysis_comparison(db, chapter=chapter, user_id=user_id, payload=payload)
    engine = await get_engine(user_id)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    _schedule_comparison_background(run_batch(sessions, batch_id=batch.id, user_id=user_id, generate=generate_analysis_candidate, concurrency=2))
    return await _chapter_comparison_response(db, batch)


@router.post("/{chapter_id}/analysis-comparison-batches/{batch_id}/retry/{candidate_id}", response_model=LLMComparisonCandidateResponse)
async def retry_analysis_comparison_candidate(chapter_id: str, batch_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = getattr(request.state, "user_id", None)
    batch = await get_owned_batch(db, batch_id=batch_id, user_id=user_id)
    if batch.target_type != "analysis" or batch.target_id != chapter_id:
        raise HTTPException(status_code=404, detail="分析候选不存在")
    candidate = await retry_candidate(db, batch_id=batch_id, candidate_id=candidate_id, user_id=user_id)
    engine = await get_engine(user_id)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    _schedule_comparison_background(run_batch(sessions, batch_id=batch.id, user_id=user_id, generate=generate_analysis_candidate, concurrency=1))
    return LLMComparisonCandidateResponse.model_validate(candidate)


@router.post("/{chapter_id}/analysis-comparison-batches/{batch_id}/adopt/{candidate_id}", response_model=LLMComparisonBatchResponse)
async def adopt_analysis_comparison_candidate(chapter_id: str, batch_id: str, candidate_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = getattr(request.state, "user_id", None)
    try:
        batch = await get_owned_batch(db, batch_id=batch_id, user_id=user_id)
        if batch.target_type != "analysis" or batch.target_id != chapter_id:
            raise ComparisonNotFoundError("分析候选不存在")
        batch, _, _ = await adopt_candidate(
            db,
            batch_id=batch_id,
            candidate_id=candidate_id,
            user_id=user_id,
            apply_target=apply_analysis_candidate,
        )
        await db.refresh(batch)
        return await _chapter_comparison_response(db, batch)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ComparisonStateError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{chapter_id}/comparison-batches", response_model=LLMComparisonBatchResponse, summary="创建章节多模型候选")
async def create_chapter_comparison_batch(
    chapter_id: str,
    payload: ChapterComparisonCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    chapter = await db.scalar(select(Chapter).where(Chapter.id == chapter_id))
    if chapter is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    await verify_project_access(chapter.project_id, user_id, db)
    can_generate, error_msg, _ = await check_prerequisites(db, chapter)
    if not can_generate:
        raise HTTPException(status_code=400, detail=error_msg)
    analysis_ready, analysis_msg = await check_previous_analysis_ready(db, chapter)
    if not analysis_ready and not getattr(payload, 'skip_analysis_check', False):
        raise HTTPException(status_code=409, detail=analysis_msg)
    try:
        batch, _ = await create_chapter_comparison(db, chapter=chapter, user_id=user_id, request=payload)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    engine = await get_engine(user_id)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    _schedule_comparison_background(run_batch(
        session_factory,
        batch_id=batch.id,
        user_id=user_id,
        generate=generate_chapter_candidate,
        concurrency=2,
    ))
    return await _chapter_comparison_response(db, batch)


@router.post("/{chapter_id}/comparison-batches/{batch_id}/retry/{candidate_id}", response_model=LLMComparisonCandidateResponse, summary="重试章节候选")
async def retry_chapter_comparison_candidate(
    chapter_id: str,
    batch_id: str,
    candidate_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    try:
        batch = await get_owned_batch(db, batch_id=batch_id, user_id=user_id)
        if batch.target_type != "chapter" or batch.target_id != chapter_id:
            raise ComparisonNotFoundError("章节候选批次不存在")
        candidate = await retry_candidate(db, batch_id=batch_id, candidate_id=candidate_id, user_id=user_id)
        engine = await get_engine(user_id)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        _schedule_comparison_background(run_batch(
            session_factory, batch_id=batch.id, user_id=user_id,
            generate=generate_chapter_candidate, concurrency=1,
        ))
        return LLMComparisonCandidateResponse.model_validate(candidate)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ComparisonStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{chapter_id}/comparison-batches/{batch_id}/adopt/{candidate_id}", response_model=LLMComparisonBatchResponse, summary="采用章节候选")
async def adopt_chapter_comparison_candidate(
    chapter_id: str,
    batch_id: str,
    candidate_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    try:
        batch = await get_owned_batch(db, batch_id=batch_id, user_id=user_id)
        if batch.target_type != "chapter" or batch.target_id != chapter_id:
            raise ComparisonNotFoundError("章节候选批次不存在")
        project = await verify_project_access(batch.project_id, user_id, db)
        runtime = await freeze_project_creation_config(
            db,
            project=project,
            user_id=user_id,
        )
        batch, candidate, adopted_now = await adopt_candidate(
            db,
            batch_id=batch_id,
            candidate_id=candidate_id,
            user_id=user_id,
            apply_target=apply_chapter_candidate,
        )
        if adopted_now:
            analysis_task_id = (candidate.output_data or {}).get("formal_analysis_task_id")
            if not analysis_task_id:
                raise RuntimeError("章节已采用，但未创建正式分析任务")
            _schedule_analysis_background(analyze_chapter_background(
                chapter_id=chapter_id,
                user_id=user_id,
                project_id=batch.project_id,
                task_id=analysis_task_id,
                provider_config_id=runtime.analysis.id,
                model=runtime.analysis.model,
                enable_mcp=bool(runtime.parameters.get("mcp_enabled", True)),
                allowed_mcp_plugin_ids=[
                    plugin.id for plugin in runtime.mcp_plugins if plugin.id
                ],
            ))
        await db.refresh(batch)
        return await _chapter_comparison_response(db, batch)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ComparisonStateError, FormalChapterConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.put("/{chapter_id}/comparison-batches/{batch_id}/candidates/{candidate_id}", response_model=LLMComparisonCandidateResponse, summary="编辑章节候选")
async def edit_chapter_comparison_candidate(
    chapter_id: str,
    batch_id: str,
    candidate_id: str,
    payload: ChapterCandidateEditRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    try:
        batch = await get_owned_batch(db, batch_id=batch_id, user_id=user_id, lock=True)
        if batch.target_type != "chapter" or batch.target_id != chapter_id:
            raise ComparisonNotFoundError("章节候选批次不存在")
        if batch.adopted_candidate_id:
            raise ComparisonStateError("该批次已有正式采用结果，不能再编辑")
        candidate = await db.scalar(select(LLMComparisonCandidate).where(
            LLMComparisonCandidate.id == candidate_id,
            LLMComparisonCandidate.batch_id == batch.id,
        ).with_for_update())
        if candidate is None:
            raise ComparisonNotFoundError("候选结果不存在")
        if candidate.status != "success":
            raise ComparisonStateError("只能编辑生成成功的候选结果")
        candidate.output_text = payload.output_text
        await db.commit()
        await db.refresh(candidate)
        return LLMComparisonCandidateResponse.model_validate(candidate)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ComparisonStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{chapter_id}/generate-stream", summary="AI创作章节内容（流式）")
async def generate_chapter_content_stream(
    chapter_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    generate_request: ChapterGenerateRequest = ChapterGenerateRequest(),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    根据大纲、前置章节内容和项目信息AI创作章节完整内容（流式返回）
    要求：必须按顺序生成，确保前置章节都已完成
    
    请求体参数：
    - style_id: 可选，指定使用的写作风格ID。不提供则不使用任何风格
    - target_word_count: 可选，目标字数，默认3000字，范围500-10000字
    - enable_mcp: 可选，是否启用MCP工具增强，默认True
    
    注意：此函数不使用依赖注入的db，而是在生成器内部创建独立的数据库会话
    以避免流式响应期间的连接泄漏问题
    """
    style_id = generate_request.style_id
    target_word_count = generate_request.target_word_count or 3000
    custom_model = generate_request.model if hasattr(generate_request, 'model') else None
    temp_narrative_perspective = generate_request.narrative_perspective if hasattr(generate_request, 'narrative_perspective') else None
    skill_key = generate_request.skill_key if hasattr(generate_request, 'skill_key') else None
    # 预先验证章节存在性（使用临时会话）
    async for temp_db in get_db(request):
        try:
            result = await temp_db.execute(
                select(Chapter).where(Chapter.id == chapter_id)
            )
            chapter = result.scalar_one_or_none()
            if not chapter:
                raise HTTPException(status_code=404, detail="章节不存在")
            
            # 检查前置条件
            can_generate, error_msg, previous_chapters = await check_prerequisites(temp_db, chapter)
            if not can_generate:
                raise HTTPException(status_code=400, detail=error_msg)
            analysis_ready, analysis_msg = await check_previous_analysis_ready(temp_db, chapter)
            if not analysis_ready and not getattr(generate_request, 'skip_analysis_check', False):
                raise HTTPException(status_code=409, detail=analysis_msg)
            
            # 保存前置章节数据供生成器使用
            previous_chapters_data = [
                {
                    'id': ch.id,
                    'chapter_number': ch.chapter_number,
                    'title': ch.title,
                    'content': ch.content
                }
                for ch in previous_chapters
            ]
        finally:
            await temp_db.close()
        break
    
    async def event_generator():
        # 在生成器内部创建独立的数据库会话
        db_session = None
        db_committed = False
        # 获取当前用户ID（在生成器外部就需要）
        current_user_id = getattr(request.state, "user_id", "system")
        
        # 初始化标准进度追踪器
        from app.utils.sse_response import WizardProgressTracker
        tracker = WizardProgressTracker("章节")
        
        try:
            yield await tracker.start()
            
            # 创建新的数据库会话
            async for db_session in get_db(request):
                # === 加载阶段 ===
                yield await tracker.loading("加载章节信息...", 0.2)
                
                # 重新获取章节信息
                chapter_result = await db_session.execute(
                    select(Chapter).where(Chapter.id == chapter_id)
                )
                current_chapter = chapter_result.scalar_one_or_none()
                if not current_chapter:
                    yield await tracker.error("章节不存在", 404)
                    return
                expected_content_hash = chapter_content_hash(current_chapter.content)
            
                yield await tracker.loading("加载项目信息...", 0.4)
                
                # 获取项目信息
                project_result = await db_session.execute(
                    select(Project).where(Project.id == current_chapter.project_id)
                )
                project = project_result.scalar_one_or_none()
                if not project:
                    yield await tracker.error("项目不存在", 404)
                    return

                # 统一解析：本次手选 > 章节写作默认路由 > 用户默认服务 > 旧版设置。
                from app.services.ai_provider_service import create_routed_ai_service
                routed_ai_service = await create_routed_ai_service(
                    db_session,
                    user_id=current_user_id,
                    usage_type="chapter_write",
                    provider_config_id=generate_request.provider_config_id,
                    model=generate_request.model,
                    project_id=current_chapter.project_id,
                    chapter_id=current_chapter.id,
                    enable_mcp=generate_request.enable_mcp,
                )
                
                # 获取项目的大纲模式
                outline_mode = project.outline_mode if project else 'one-to-many'
                logger.info(f"📋 项目大纲模式: {outline_mode}")
                
                # 获取对应的大纲（优先使用 chapter.outline_id 直接关联）
                if current_chapter.outline_id:
                    outline_result = await db_session.execute(
                        select(Outline)
                        .where(Outline.id == current_chapter.outline_id)
                        .execution_options(populate_existing=True)
                    )
                else:
                    # 回退到按序号查找
                    outline_result = await db_session.execute(
                        select(Outline)
                        .where(Outline.project_id == current_chapter.project_id)
                        .where(Outline.order_index == current_chapter.chapter_number)
                        .execution_options(populate_existing=True)
                    )
                outline = outline_result.scalar_one_or_none()
                
                # 获取写作风格
                style_content = ""
                if style_id:
                    # 使用指定的风格
                    style_result = await db_session.execute(
                        select(WritingStyle).where(WritingStyle.id == style_id)
                    )
                    style = style_result.scalar_one_or_none()
                    if style:
                        # 验证风格是否可用：全局预设风格（user_id为NULL）或者当前用户的自定义风格
                        if style.user_id is None or style.user_id == current_user_id:
                            style_content = style.prompt_content or ""
                            style_type = "全局预设" if style.user_id is None else "用户自定义"
                            logger.info(f"使用指定风格: {style.name} ({style_type})")
                        else:
                            logger.warning(f"风格 {style_id} 不属于当前项目，无法使用")
                    else:
                        logger.warning(f"未找到风格 {style_id}")
                else:
                    logger.info("未指定写作风格，使用原始提示词")
                
                # 🚀 根据大纲模式选择独立的上下文构建器
                if outline_mode == 'one-to-one':
                    # ========== 1-1模式：使用独立的简化构建器 ==========
                    logger.info(f"🔧 [1-1模式] 使用 OneToOneContextBuilder")
                    context_builder = OneToOneContextBuilder(
                        memory_service=memory_service,
                        foreshadow_service=foreshadow_service
                    )
                    chapter_context = await context_builder.build(
                        chapter=current_chapter,
                        project=project,
                        outline=outline,
                        user_id=current_user_id,
                        db=db_session,
                        target_word_count=target_word_count
                    )
                    
                    # 日志输出统计信息
                    logger.info(f"📊 [1-1模式] 上下文统计:")
                    logger.info(f"  - 章节序号: {current_chapter.chapter_number}")
                    logger.info(f"  - 大纲长度: {chapter_context.context_stats.get('outline_length', 0)} 字符")
                    logger.info(f"  - 上一章内容: {chapter_context.context_stats.get('previous_content_length', 0)} 字符")
                    logger.info(f"  - 角色信息: {chapter_context.context_stats.get('characters_length', 0)} 字符")
                    logger.info(f"  - 伏笔提醒: {chapter_context.context_stats.get('foreshadow_length', 0)} 字符")
                    logger.info(f"  - 相关记忆: {chapter_context.context_stats.get('memories_length', 0)} 字符")
                    logger.info(f"  - 总长度: {chapter_context.context_stats.get('total_length', 0)} 字符")
                else:
                    # ========== 1-N模式：使用独立的完整构建器 ==========
                    logger.info(f"🔧 [1-N模式] 使用 OneToManyContextBuilder")
                    context_builder = OneToManyContextBuilder(
                        memory_service=memory_service,
                        foreshadow_service=foreshadow_service
                    )
                    chapter_context = await context_builder.build(
                        chapter=current_chapter,
                        project=project,
                        outline=outline,
                        user_id=current_user_id,
                        db=db_session,
                        style_content=style_content,
                        target_word_count=target_word_count,
                        temp_narrative_perspective=temp_narrative_perspective
                    )
                    
                    # 日志输出统计信息
                    logger.info(f"📊 [1-N模式] 上下文统计:")
                    logger.info(f"  - 章节序号: {current_chapter.chapter_number}")
                    logger.info(f"  - 衔接锚点: {chapter_context.context_stats.get('continuation_length', 0)} 字符")
                    logger.info(f"  - 角色信息: {chapter_context.context_stats.get('characters_length', 0)} 字符")
                    logger.info(f"  - 相关记忆: {chapter_context.context_stats.get('memories_length', 0)} 字符")
                    logger.info(f"  - 故事骨架: {chapter_context.context_stats.get('skeleton_length', 0)} 字符")
                    logger.info(f"  - 伏笔提醒: {chapter_context.context_stats.get('foreshadow_length', 0)} 字符")
                    logger.info(f"  - 总长度: {chapter_context.context_stats.get('total_length', 0)} 字符")
            
                yield await tracker.loading("上下文构建完成", 0.8)
                
                # 🎭 确定使用的叙事人称（临时指定 > 项目默认 > 系统默认）
                chapter_perspective = (
                    temp_narrative_perspective or
                    project.narrative_perspective or
                    '第三人称'
                )
                logger.info(f"📝 使用叙事人称: {chapter_perspective}")
                
                # 🚀 根据大纲模式选择提示词模板和参数
                if outline_mode == 'one-to-one':
                    # 1-1模式
                    if chapter_context.continuation_point:
                        # 有上一章内容
                        template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_ONE_NEXT", current_user_id, db_session)
                        base_prompt = PromptService.format_prompt(
                            template,
                            project_title=project.title,
                            chapter_number=current_chapter.chapter_number,
                            chapter_title=current_chapter.title,
                            chapter_outline=chapter_context.chapter_outline,
                            target_word_count=target_word_count,
                            genre=project.genre or '未设定',
                            narrative_perspective=chapter_perspective,
                            previous_chapter_content=chapter_context.continuation_point,
                            previous_chapter_summary=chapter_context.previous_chapter_summary or '（无上一章摘要）',
                            recent_chapters_context=chapter_context.recent_chapters_context or '暂无最近章节摘要',
                            characters_info=chapter_context.chapter_characters or '暂无角色信息',
                            chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                            foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                            relevant_memories=chapter_context.relevant_memories or '暂无相关记忆'
                        )
                        logger.debug(f"创建第{current_chapter.chapter_number}章提示词完成: prompt_length={len(base_prompt)}")
                    else:
                        # 第一章
                        template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_ONE", current_user_id, db_session)
                        base_prompt = PromptService.format_prompt(
                            template,
                            project_title=project.title,
                            chapter_number=current_chapter.chapter_number,
                            chapter_title=current_chapter.title,
                            chapter_outline=chapter_context.chapter_outline,
                            target_word_count=target_word_count,
                            genre=project.genre or '未设定',
                            narrative_perspective=chapter_perspective,
                            characters_info=chapter_context.chapter_characters or '暂无角色信息',
                            chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                            foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                            relevant_memories=chapter_context.relevant_memories or '暂无相关记忆'
                        )
                        logger.debug(f"创建第一章提示词完成: prompt_length={len(base_prompt)}")
                else:
                    # ========== 1-n模式：使用完整模板 ==========
                    if chapter_context.continuation_point:
                        # 有前置内容，使用 WITH_CONTEXT 模板
                        logger.info(f"📝 [1-n模式] 使用带上下文的模板（第{current_chapter.chapter_number}章）")
                        
                        # 提取上一章摘要
                        previous_summary = "（无上一章摘要，请根据锚点续写）"
                        if chapter_context.previous_chapter_summary:
                            previous_summary = chapter_context.previous_chapter_summary
                        
                        template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_MANY_NEXT", current_user_id, db_session)
                        base_prompt = PromptService.format_prompt(
                            template,
                            project_title=project.title,
                            chapter_number=current_chapter.chapter_number,
                            chapter_title=current_chapter.title,
                            chapter_outline=chapter_context.chapter_outline,
                            target_word_count=target_word_count,
                            continuation_point=chapter_context.continuation_point,
                            genre=project.genre or '未设定',
                            narrative_perspective=chapter_perspective,
                            characters_info=chapter_context.chapter_characters or '暂无角色信息',
                            chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                            foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                            previous_chapter_summary=previous_summary,
                            recent_chapters_context=chapter_context.recent_chapters_context or '',
                            relevant_memories=chapter_context.relevant_memories or ''
                        )
                        logger.debug(f"创建第{current_chapter.chapter_number}章提示词完成: prompt_length={len(base_prompt)}")
                    else:
                        # 第1章，使用无前置内容模板
                        logger.info(f"📝 [1-n模式] 使用第一章模板")
                        template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_MANY", current_user_id, db_session)
                        base_prompt = PromptService.format_prompt(
                            template,
                            project_title=project.title,
                            chapter_number=current_chapter.chapter_number,
                            chapter_title=current_chapter.title,
                            chapter_outline=chapter_context.chapter_outline,
                            target_word_count=target_word_count,
                            genre=project.genre or '未设定',
                            narrative_perspective=chapter_perspective,
                            characters_info=chapter_context.chapter_characters or '暂无角色信息',
                            chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                            foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                            relevant_memories=chapter_context.relevant_memories or '暂无相关记忆'
                        )
                        logger.debug(f"创建第一章提示词完成: prompt_length={len(base_prompt)}")
                
                # 应用写作风格
                if style_content:
                    prompt = WritingStyleManager.apply_style_to_prompt(base_prompt, style_content)
                else:
                    prompt = base_prompt
                
                # === 准备阶段 ===
                yield await tracker.preparing("准备AI提示词...")
                
                logger.info(f"开始AI流式创作章节 {chapter_id}")
                
                # 🎨 方案一：将写作风格注入到系统提示词（最高优先级）
                system_prompt_with_style = None
                
                # ⚡ Skill 支持：当指定 skill_key 时，将 Skill 工作流注入系统提示词（公共函数，与大纲生成共用）
                if skill_key:
                    try:
                        from app.services.skill_loader import build_skill_system_prompt
                        skill_prompt = build_skill_system_prompt(skill_key)
                        if skill_prompt:
                            system_prompt_with_style = skill_prompt
                            if style_content:
                                system_prompt_with_style += f"""

【🎨 写作风格要求 - 补充】

{style_content}"""
                            logger.info(f"⚡ 已将 Skill '{skill_key}' 注入系统提示词")
                    except Exception as skill_err:
                        logger.warning(f"⚠️ 加载 Skill 失败: {skill_err}")
                
                if not system_prompt_with_style and style_content:
                    system_prompt_with_style = f"""【🎨 写作风格要求 - 最高优先级】

{style_content}

⚠️ 请严格遵循上述写作风格要求进行创作，这是最重要的指令！
确保在整个章节创作过程中始终保持风格的一致性。"""
                    logger.info(f"✅ 已将写作风格注入系统提示词（{len(style_content)}字符）")
                
                # 🔢 计算 max_tokens 限制
                # 中文字符约 1.5-2 个 token，使用 2.5 倍系数确保有足够空间完成段落
                # 同时设置上限防止过长，下限确保基本可用（流式请求无 task_input，按目标字数计算）
                calculated_max_tokens = int(target_word_count * 3)
                calculated_max_tokens = max(2000, min(calculated_max_tokens, 16000))  # 限制在 2000-16000 之间
                logger.info(f"📊 目标字数: {target_word_count}, 计算 max_tokens: {calculated_max_tokens}")
                
                # 准备生成参数
                generate_kwargs = {
                    "prompt": prompt,
                    "system_prompt": system_prompt_with_style,
                    "tool_choice": "required",
                    "max_tokens": calculated_max_tokens,
                    "auto_mcp": bool(generate_request.enable_mcp)
                }
                if custom_model:
                    logger.info(f"  使用自定义模型: {custom_model}")
                    generate_kwargs["model"] = custom_model
                    # 注意：这里使用用户配置的AI服务，模型参数会覆盖默认模型
                    # 如果需要切换provider，需要在前端传递provider参数
                
                # === 生成阶段 ===
                full_content = ""
                chunk_count = 0
                
                yield await tracker.generating(
                    current_chars=0,
                    estimated_total=target_word_count
                )
                
                async for chunk in routed_ai_service.generate_text_stream(**generate_kwargs):
                    full_content += chunk
                    chunk_count += 1
                    
                    # 发送内容块
                    yield await tracker.generating_chunk(chunk)
                    
                    # 每5个chunk发送一次进度更新
                    if chunk_count % 5 == 0:
                        yield await tracker.generating(
                            current_chars=len(full_content),
                            estimated_total=target_word_count,
                            message=f'正在创作中... 已生成 {len(full_content)} 字'
                        )
                    
                    # 每20个chunk发送心跳
                    if chunk_count % 20 == 0:
                        yield await tracker.heartbeat()
                    
                    await asyncio.sleep(0)  # 让出控制权
                
                # === 保存阶段 ===
                yield await tracker.saving("正在保存章节...", 0.3)
                
                formal_result = await persist_formal_chapter_content(
                    db=db_session,
                    chapter_id=chapter_id,
                    user_id=current_user_id,
                    content=full_content,
                    prompt=f"创作章节: 第{current_chapter.chapter_number}章 {current_chapter.title}",
                    model=custom_model or generate_request.model or "default",
                    foreshadow_service=foreshadow_service,
                    memory_service=memory_service,
                    expected_content_hash=expected_content_hash,
                )
                db_committed = True
                current_chapter = formal_result.chapter
                analysis_task = formal_result.analysis_task
                new_word_count = current_chapter.word_count
                task_id = analysis_task.id
                logger.info(f"成功创作章节 {chapter_id}，共 {new_word_count} 字")
                logger.info(f"📋 已创建分析任务: {task_id}")
                
                # 短暂延迟确保SQLite WAL完成写入
                await asyncio.sleep(0.05)
                
                # 直接启动后台分析（并发执行）
                background_tasks.add_task(
                    analyze_chapter_background,
                    chapter_id=chapter_id,
                    user_id=current_user_id,
                    project_id=project.id,
                    task_id=task_id,
                    ai_service=routed_ai_service
                )
                
                yield await tracker.saving("章节保存完成", 0.8)
                
                # === 完成阶段 ===
                yield await tracker.complete("创作完成！")
                
                # 发送结果数据
                yield await tracker.result({
                    'word_count': new_word_count,
                    'analysis_task_id': task_id
                })
                
                # 发送分析开始事件（使用自定义事件）
                yield await SSEResponse.send_event(
                    event='analysis_started',
                    data={
                        'task_id': task_id,
                        'message': '章节分析已开始'
                    }
                )
                
                # 发送完成信号
                yield await tracker.done()
                
                break  # 退出async for db_session循环
        
        except GeneratorExit:
            # SSE连接断开
            logger.warning("章节生成器被提前关闭（SSE断开）")
            if db_session and not db_committed:
                try:
                    if db_session.in_transaction():
                        await db_session.rollback()
                        logger.info("章节生成事务已回滚（GeneratorExit）")
                except Exception as e:
                    logger.error(f"GeneratorExit回滚失败: {str(e)}")
        except Exception as e:
            logger.error(f"流式创作章节失败: {str(e)}")
            if db_session and not db_committed:
                try:
                    if db_session.in_transaction():
                        await db_session.rollback()
                        logger.info("章节生成事务已回滚（异常）")
                except Exception as rollback_error:
                    logger.error(f"回滚失败: {str(rollback_error)}")
            yield await tracker.error(str(e))
        finally:
            # 确保数据库会话被正确关闭
            if db_session:
                try:
                    # 最后检查：确保没有未提交的事务
                    if not db_committed and db_session.in_transaction():
                        await db_session.rollback()
                        logger.warning("在finally中发现未提交事务，已回滚")
                    
                    await db_session.close()
                    logger.info("数据库会话已关闭")
                except Exception as close_error:
                    logger.error(f"关闭数据库会话失败: {str(close_error)}")
                    # 强制关闭
                    try:
                        await db_session.close()
                    except Exception:
                        pass
    
    return create_sse_response(event_generator())


@router.post("/{chapter_id}/generate-background", summary="AI创作章节内容（后台任务）")
async def generate_chapter_content_background(
    chapter_id: str,
    request: Request,
    generate_request: ChapterGenerateRequest = ChapterGenerateRequest(),
    db: AsyncSession = Depends(get_db)
):
    """
    创建后台任务来生成章节内容。
    任务创建后立即返回task_id，前端通过 GET /api/tasks/{task_id} 轮询进度。
    关闭浏览器不影响生成，生成完成后内容自动保存到数据库。
    """
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    # 验证章节存在
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 验证项目权限
    project = await verify_project_access(chapter.project_id, user_id, db)

    # 检查前置条件
    can_generate, error_msg, _ = await check_prerequisites(db, chapter)
    if not can_generate:
        raise HTTPException(status_code=400, detail=error_msg)
    analysis_ready, analysis_msg = await check_previous_analysis_ready(db, chapter)
    if not analysis_ready and not getattr(generate_request, 'skip_analysis_check', False):
        raise HTTPException(status_code=409, detail=analysis_msg)

    # 创建后台任务
    from app.services.background_task_service import background_task_service, TaskProgressTracker
    task = await background_task_service.create_task(
        user_id=user_id,
        project_id=chapter.project_id,
        task_type="chapter_generate",
        task_input={
            "chapter_id": chapter_id,
            "style_id": generate_request.style_id,
            "target_word_count": generate_request.target_word_count or 3000,
            "enable_mcp": generate_request.enable_mcp,
            "model": generate_request.model,
            "provider_config_id": generate_request.provider_config_id,
            "narrative_perspective": generate_request.narrative_perspective,
            "skill_key": generate_request.skill_key,
        },
        db=db
    )

    # 提取闭包需要的值：后台任务运行时请求会话已关闭，不能再访问 ORM 对象（否则可能报 DetachedInstanceError）
    project_id = chapter.project_id

    # 后台执行的函数
    async def _run_chapter_generation(task_id: str, bg_user_id: str):
        from app.database import get_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as BgAsyncSession

        engine = await get_engine(bg_user_id)
        AsyncSessionLocal = async_sessionmaker(engine, class_=BgAsyncSession, expire_on_commit=False)

        async with AsyncSessionLocal() as bg_db:
            tracker = TaskProgressTracker(task_id, bg_user_id, "章节")
            try:
                await tracker.start()

                # 获取AI服务
                from app.services.ai_provider_service import create_routed_ai_service
                bg_ai_service = await create_routed_ai_service(
                    bg_db,
                    user_id=bg_user_id,
                    usage_type="chapter_write",
                    provider_config_id=generate_request.provider_config_id,
                    model=generate_request.model,
                    project_id=project_id,
                    chapter_id=chapter_id,
                    task_trace_id=task_id,
                    enable_mcp=generate_request.enable_mcp,
                )

                await _run_chapter_generation_bg(
                    task_input={
                        "chapter_id": chapter_id,
                        "style_id": generate_request.style_id,
                        "target_word_count": generate_request.target_word_count or 3000,
                        "enable_mcp": generate_request.enable_mcp,
                        "model": generate_request.model,
                        "provider_config_id": generate_request.provider_config_id,
                        "narrative_perspective": generate_request.narrative_perspective,
                        "skill_key": generate_request.skill_key,
                    },
                    db=bg_db,
                    ai_service=bg_ai_service,
                    tracker=tracker,
                    user_id=bg_user_id,
                    task_id=task_id,
                )

            except Exception as e:
                logger.error(f"❌ 后台章节生成失败: {e}", exc_info=True)
                await tracker.error(str(e))

    await background_task_service.spawn_background_task(
        task.id, user_id, _run_chapter_generation
    )

    return {
        "task_id": task.id,
        "task_type": "chapter_generate",
        "status": "pending",
        "message": "任务已创建，请通过 GET /api/tasks/{task_id} 查询进度"
    }


@router.post("/{chapter_id}/generate-background-legacy", summary="AI创作章节内容（后台任务，遗留重复实现）")
async def generate_chapter_content_background_legacy(
    chapter_id: str,
    request: Request,
    generate_request: ChapterGenerateRequest = ChapterGenerateRequest(),
    db: AsyncSession = Depends(get_db)
):
    """
    创建后台任务来生成章节内容。
    任务创建后立即返回task_id，前端通过 GET /api/tasks/{task_id} 轮询进度。
    关闭浏览器不影响生成，生成完成后内容自动保存到数据库。
    """
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    # 验证章节存在
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 验证项目权限
    project = await verify_project_access(chapter.project_id, user_id, db)

    # 检查前置条件
    can_generate, error_msg, _ = await check_prerequisites(db, chapter)
    if not can_generate:
        raise HTTPException(status_code=400, detail=error_msg)

    # 创建后台任务
    from app.services.background_task_service import background_task_service, TaskProgressTracker
    task = await background_task_service.create_task(
        user_id=user_id,
        project_id=chapter.project_id,
        task_type="chapter_generate",
        task_input={
            "chapter_id": chapter_id,
            "style_id": generate_request.style_id,
            "target_word_count": generate_request.target_word_count or 3000,
            "enable_mcp": generate_request.enable_mcp,
            "model": generate_request.model,
            "narrative_perspective": generate_request.narrative_perspective,
        },
        db=db
    )

    # 后台执行的函数
    async def _run_chapter_generation(task_id: str, bg_user_id: str):
        from app.database import get_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as BgAsyncSession

        engine = await get_engine(bg_user_id)
        AsyncSessionLocal = async_sessionmaker(engine, class_=BgAsyncSession, expire_on_commit=False)

        async with AsyncSessionLocal() as bg_db:
            tracker = TaskProgressTracker(task_id, bg_user_id, "章节")
            try:
                await tracker.start()

                # 获取AI服务
                from app.api.settings import get_user_ai_service_from_db
                bg_ai_service = await get_user_ai_service_from_db(bg_user_id, bg_db)

                await _run_chapter_generation_bg(
                    task_input={
                        "chapter_id": chapter_id,
                        "style_id": generate_request.style_id,
                        "target_word_count": generate_request.target_word_count or 3000,
                        "enable_mcp": generate_request.enable_mcp,
                        "model": generate_request.model,
                        "narrative_perspective": generate_request.narrative_perspective,
                    },
                    db=bg_db,
                    ai_service=bg_ai_service,
                    tracker=tracker,
                    user_id=bg_user_id,
                    task_id=task_id,
                )

            except Exception as e:
                logger.error(f"❌ 后台章节生成失败: {e}", exc_info=True)
                await tracker.error(str(e))

    await background_task_service.spawn_background_task(
        task.id, user_id, _run_chapter_generation
    )

    return {
        "task_id": task.id,
        "task_type": "chapter_generate",
        "status": "pending",
        "message": "任务已创建，请通过 GET /api/tasks/{task_id} 查询进度"
    }


async def _run_chapter_generation_bg(
    task_input: dict,
    db: AsyncSession,
    ai_service: AIService,
    tracker,
    user_id: str,
    task_id: str,
):
    """后台执行章节生成（不使用SSE，直接生成并保存）"""
    from app.services.chapter_context_service import (
        OneToManyContextBuilder,
        OneToOneContextBuilder
    )

    chapter_id = task_input["chapter_id"]
    style_id = task_input.get("style_id")
    target_word_count = task_input.get("target_word_count", 3000)
    custom_model = task_input.get("model")
    temp_narrative_perspective = task_input.get("narrative_perspective")
    enable_mcp = task_input.get("enable_mcp", True)
    skill_key = task_input.get("skill_key")
    schedule_analysis = task_input.get("schedule_analysis", True)
    write_lock = await get_db_write_lock(user_id)

    # === 加载阶段 ===
    await tracker.loading("加载章节信息...", 0.2)

    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    current_chapter = chapter_result.scalar_one_or_none()
    if not current_chapter:
        await tracker.error("章节不存在")
        return
    expected_content_hash = chapter_content_hash(current_chapter.content)

    await tracker.loading("加载项目信息...", 0.4)

    project_result = await db.execute(
        select(Project).where(Project.id == current_chapter.project_id)
    )
    project = project_result.scalar_one_or_none()
    if not project:
        await tracker.error("项目不存在")
        return

    outline_mode = project.outline_mode if project else 'one-to-many'

    # 获取大纲
    if current_chapter.outline_id:
        outline_result = await db.execute(
            select(Outline).where(Outline.id == current_chapter.outline_id)
        )
    else:
        outline_result = await db.execute(
            select(Outline)
            .where(Outline.project_id == current_chapter.project_id)
            .where(Outline.order_index == current_chapter.chapter_number)
        )
    outline = outline_result.scalar_one_or_none()

    # 获取写作风格
    style_content = ""
    if style_id:
        style_result = await db.execute(
            select(WritingStyle).where(WritingStyle.id == style_id)
        )
        style = style_result.scalar_one_or_none()
        if style and (style.user_id is None or style.user_id == user_id):
            style_content = style.prompt_content or ""

    # === 构建上下文 ===
    if outline_mode == 'one-to-one':
        context_builder = OneToOneContextBuilder(
            memory_service=memory_service,
            foreshadow_service=foreshadow_service
        )
        chapter_context = await context_builder.build(
            chapter=current_chapter,
            project=project,
            outline=outline,
            user_id=user_id,
            db=db,
            target_word_count=target_word_count
        )
    else:
        context_builder = OneToManyContextBuilder(
            memory_service=memory_service,
            foreshadow_service=foreshadow_service
        )
        chapter_context = await context_builder.build(
            chapter=current_chapter,
            project=project,
            outline=outline,
            user_id=user_id,
            db=db,
            style_content=style_content,
            target_word_count=target_word_count,
            temp_narrative_perspective=temp_narrative_perspective
        )

    await tracker.loading("上下文构建完成", 0.8)

    # 确定叙事人称
    chapter_perspective = (
        temp_narrative_perspective or
        project.narrative_perspective or
        '第三人称'
    )

    # === 准备提示词 ===
    if outline_mode == 'one-to-one':
        if chapter_context.continuation_point:
            template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_ONE_NEXT", user_id, db)
            base_prompt = PromptService.format_prompt(
                template,
                project_title=project.title,
                chapter_number=current_chapter.chapter_number,
                chapter_title=current_chapter.title,
                chapter_outline=chapter_context.chapter_outline,
                target_word_count=target_word_count,
                genre=project.genre or '未设定',
                narrative_perspective=chapter_perspective,
                previous_chapter_content=chapter_context.continuation_point,
                previous_chapter_summary=chapter_context.previous_chapter_summary or '（无上一章摘要）',
                recent_chapters_context=chapter_context.recent_chapters_context or '暂无最近章节摘要',
                characters_info=chapter_context.chapter_characters or '暂无角色信息',
                chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                relevant_memories=chapter_context.relevant_memories or '暂无相关记忆'
            )
        else:
            template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_ONE", user_id, db)
            base_prompt = PromptService.format_prompt(
                template,
                project_title=project.title,
                chapter_number=current_chapter.chapter_number,
                chapter_title=current_chapter.title,
                chapter_outline=chapter_context.chapter_outline,
                target_word_count=target_word_count,
                genre=project.genre or '未设定',
                narrative_perspective=chapter_perspective,
                characters_info=chapter_context.chapter_characters or '暂无角色信息',
                chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                relevant_memories=chapter_context.relevant_memories or '暂无相关记忆'
            )
    else:
        if chapter_context.continuation_point:
            previous_summary = chapter_context.previous_chapter_summary or "（无上一章摘要，请根据锚点续写）"
            template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_MANY_NEXT", user_id, db)
            base_prompt = PromptService.format_prompt(
                template,
                project_title=project.title,
                chapter_number=current_chapter.chapter_number,
                chapter_title=current_chapter.title,
                chapter_outline=chapter_context.chapter_outline,
                target_word_count=target_word_count,
                continuation_point=chapter_context.continuation_point,
                genre=project.genre or '未设定',
                narrative_perspective=chapter_perspective,
                characters_info=chapter_context.chapter_characters or '暂无角色信息',
                chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                previous_chapter_summary=previous_summary,
                recent_chapters_context=chapter_context.recent_chapters_context or '',
                relevant_memories=chapter_context.relevant_memories or ''
            )
        else:
            template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_MANY", user_id, db)
            base_prompt = PromptService.format_prompt(
                template,
                project_title=project.title,
                chapter_number=current_chapter.chapter_number,
                chapter_title=current_chapter.title,
                chapter_outline=chapter_context.chapter_outline,
                target_word_count=target_word_count,
                genre=project.genre or '未设定',
                narrative_perspective=chapter_perspective,
                characters_info=chapter_context.chapter_characters or '暂无角色信息',
                chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                relevant_memories=chapter_context.relevant_memories or '暂无相关记忆'
            )

    # 应用写作风格
    if style_content:
        prompt = WritingStyleManager.apply_style_to_prompt(base_prompt, style_content)
    else:
        prompt = base_prompt

    # === 准备阶段 ===
    await tracker.preparing("准备AI提示词...")

    system_prompt_with_style = None
    if skill_key:
        try:
            from app.services.skill_loader import get_all_skills_cached
            skills = get_all_skills_cached()
            skill = next((s for s in skills if s["template_key"] == skill_key), None)
            if skill:
                skill_content = skill["content"]
                skill_name = skill["template_name"]
                system_prompt_with_style = f"""【⚡ Skill 工作流：{skill_name}】

{skill_content}

⚠️ 请严格遵循上述 Skill 工作流指令进行创作！"""
                if style_content:
                    system_prompt_with_style += f"""

【🎨 写作风格要求 - 补充】

{style_content}"""
                logger.info(f"⚡ 后台生成 - 已将 Skill '{skill_name}' 注入系统提示词（{len(skill_content)}字符）")
            else:
                logger.warning(f"⚠️ 后台生成 - 未找到 Skill: {skill_key}")
        except Exception as skill_err:
            logger.warning(f"⚠️ 后台生成 - 加载 Skill 失败: {skill_err}")

    if not system_prompt_with_style and style_content:
        system_prompt_with_style = f"""【🎨 写作风格要求 - 最高优先级】

{style_content}

⚠️ 请严格遵循上述写作风格要求进行创作，这是最重要的指令！
确保在整个章节创作过程中始终保持风格的一致性。"""

    explicit_max = task_input.get("max_tokens")
    if explicit_max:
        calculated_max_tokens = max(2000, min(int(explicit_max), 16000))
    else:
        calculated_max_tokens = int(target_word_count * 3)
        calculated_max_tokens = max(2000, min(calculated_max_tokens, 16000))

    generate_kwargs = {
        "prompt": prompt,
        "system_prompt": system_prompt_with_style,
        "tool_choice": "required",
        "max_tokens": calculated_max_tokens,
        "auto_mcp": bool(enable_mcp)
    }
    if task_input.get("temperature") is not None:
        generate_kwargs["temperature"] = float(task_input["temperature"])
    if custom_model:
        generate_kwargs["model"] = custom_model

    # === 生成阶段 ===
    full_content = ""
    chunk_count = 0

    await tracker.generating(
        current_chars=0,
        estimated_total=target_word_count
    )

    async for chunk in ai_service.generate_text_stream(**generate_kwargs):
        # 检查是否被取消
        if chunk_count % 10 == 0 and await tracker.check_cancelled():
            logger.info(f"🚫 后台章节生成被取消: {chapter_id}")
            return

        full_content += chunk
        chunk_count += 1

        # 每10个chunk更新一次进度
        if chunk_count % 10 == 0:
            await tracker.generating(
                current_chars=len(full_content),
                estimated_total=target_word_count,
                message=f'正在创作中... 已生成 {len(full_content)} 字'
            )

        await asyncio.sleep(0)

    minimum_content_length = task_input.get("minimum_content_length")
    if minimum_content_length and len(full_content) < int(minimum_content_length):
        raise ValueError(
            f"生成结果不足（{len(full_content)}字 < 目标{int(minimum_content_length)}字）"
        )

    # === 保存阶段 ===
    await tracker.saving("正在保存章节...", 0.3)

    async with write_lock:
        formal_result = await persist_formal_chapter_content(
            db=db,
            chapter_id=chapter_id,
            user_id=user_id,
            content=full_content,
            prompt=f"创作章节: 第{current_chapter.chapter_number}章 {current_chapter.title}",
            model=custom_model or task_input.get("model") or "default",
            foreshadow_service=foreshadow_service,
            memory_service=memory_service,
            expected_content_hash=expected_content_hash,
        )
        current_chapter = formal_result.chapter
        analysis_task = formal_result.analysis_task
        new_word_count = current_chapter.word_count

    logger.info(f"✅ 后台创作章节 {chapter_id} 完成，共 {new_word_count} 字")
    logger.info(f"📋 后台生成：已创建分析任务: {analysis_task.id}")

    await asyncio.sleep(0.05)

    # 启动后台分析
    if schedule_analysis:
        _schedule_analysis_background(
            analyze_chapter_background(
                chapter_id=chapter_id,
                user_id=user_id,
                project_id=current_chapter.project_id,
                task_id=analysis_task.id,
                ai_service=ai_service
            )
        )

    # === 完成 ===
    await tracker.complete(f"创作完成！共 {new_word_count} 字")

    # 更新任务结果
    from app.services.background_task_service import background_task_service
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as BgAsyncSession
    from app.database import get_engine as bg_get_engine
    try:
        engine = await bg_get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(engine, class_=BgAsyncSession, expire_on_commit=False)
        async with AsyncSessionLocal() as result_db:
            from sqlalchemy import update as sql_update
            await result_db.execute(
                sql_update(BackgroundTask)
                .where(BackgroundTask.id == task_id)
                .values(task_result={
                    "chapter_id": chapter_id,
                    "word_count": new_word_count,
                    "analysis_task_id": analysis_task.id
                })
            )
            await result_db.commit()
    except Exception as e:
        logger.warning(f"⚠️ 更新任务结果失败: {e}")

    return analysis_task


def _build_analysis_task_status_payload(
    chapter_id: str,
    task: Optional[AnalysisTask],
    auto_recovered: bool = False
) -> dict:
    """统一构建分析任务状态响应"""
    if not task:
        return {
            "has_task": False,
            "chapter_id": chapter_id,
            "status": "none",
            "progress": 0,
            "error_message": None,
            "auto_recovered": False,
            "task_id": None,
            "created_at": None,
            "started_at": None,
            "completed_at": None
        }

    return {
        "has_task": True,
        "task_id": task.id,
        "chapter_id": task.chapter_id,
        "status": task.status,
        "progress": task.progress,
        "error_message": task.error_message,
        "auto_recovered": auto_recovered,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None
    }


async def _recover_stale_analysis_tasks(db: AsyncSession, tasks: list) -> list[str]:
    """恢复卡死的分析任务：超过 30 分钟仍处于 pending/running 的任务标记为 failed"""
    recovered: list[str] = []
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    for task in tasks:
        if task.status in ("pending", "running"):
            updated_at = task.started_at or task.created_at
            if updated_at and updated_at < cutoff:
                task.status = "failed"
                task.error_message = "任务超时（超过30分钟未更新），已自动标记为失败"
                recovered.append(task.id)
    if recovered:
        await db.flush()
    return recovered


@router.get("/{chapter_id}/analysis/status", summary="查询章节分析任务状态", response_model=AnalysisTaskStatusResponse)
async def get_analysis_task_status(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    查询指定章节的最新分析任务状态
    
    自动恢复机制：
    - 如果任务状态为running且超过1分钟未更新，自动标记为failed
    - 如果任务状态为pending且超过2分钟未启动，自动标记为failed
    
    返回:
    - has_task: 是否存在分析任务
    - task_id: 任务ID（如果存在）
    - status: pending/running/completed/failed/none（如果不存在则为none）
    - progress: 0-100
    - error_message: 错误信息(如果失败)
    - auto_recovered: 是否被自动恢复
    - created_at: 创建时间
    - completed_at: 完成时间
    
    注意：当章节不存在或无权访问时返回404，当没有分析任务时返回has_task=false
    """
    from datetime import timedelta
    
    # 先获取章节以验证存在性和权限
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 获取该章节最新的分析任务
    result = await db.execute(
        select(AnalysisTask)
        .where(AnalysisTask.chapter_id == chapter_id)
        .order_by(AnalysisTask.created_at.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        # 返回无任务状态，而不是抛出404错误
        return _build_analysis_task_status_payload(chapter_id, None)
    
    recovered_ids = await _recover_stale_analysis_tasks(db, [task])
    auto_recovered = task.id in recovered_ids
    
    return _build_analysis_task_status_payload(chapter_id, task, auto_recovered)


@router.post("/project/{project_id}/analysis/statuses", summary="批量查询章节分析任务状态", response_model=BatchAnalysisStatusResponse)
async def get_project_analysis_task_statuses(
    project_id: str,
    payload: BatchAnalysisStatusRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """批量查询项目章节分析状态，避免前端逐章节请求造成请求风暴"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)

    # 先取项目章节列表
    chapter_query = select(Chapter.id).where(Chapter.project_id == project_id)
    if payload.chapter_ids and len(payload.chapter_ids) > 0:
        chapter_query = chapter_query.where(Chapter.id.in_(payload.chapter_ids))

    chapter_result = await db.execute(chapter_query)
    chapter_ids = [row[0] for row in chapter_result.all()]

    if not chapter_ids:
        return {
            "project_id": project_id,
            "total": 0,
            "items": {}
        }

    # 批量查询这些章节对应的所有分析任务，随后在内存中取最新一条
    tasks_result = await db.execute(
        select(AnalysisTask)
        .where(AnalysisTask.chapter_id.in_(chapter_ids))
        .order_by(AnalysisTask.chapter_id, AnalysisTask.created_at.desc())
    )
    all_tasks = tasks_result.scalars().all()

    latest_task_map: dict[str, AnalysisTask] = {}
    for task in all_tasks:
        if task.chapter_id not in latest_task_map:
            latest_task_map[task.chapter_id] = task

    recovered_ids = await _recover_stale_analysis_tasks(
        db, list(latest_task_map.values())
    )

    items: dict[str, dict] = {}
    for chapter_id in chapter_ids:
        task = latest_task_map.get(chapter_id)
        items[chapter_id] = _build_analysis_task_status_payload(
            chapter_id,
            task,
            task.id in recovered_ids if task else False,
        )

    return {
        "project_id": project_id,
        "total": len(chapter_ids),
        "items": items
    }


async def _run_batch_analysis_in_sequence(
    tasks_queue: list[dict[str, int | str]],
    user_id: str,
    project_id: str,
    ai_service: Optional[AIService] = None,
    provider_config_id: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    """按章节顺序逐个执行分析任务。"""
    for index, task_item in enumerate(tasks_queue, start=1):
        chapter_id = str(task_item["chapter_id"])
        chapter_number = int(task_item["chapter_number"])
        task_id = str(task_item["task_id"])

        logger.info(f"🔁 一键分析顺序执行中 [{index}/{len(tasks_queue)}]：第{chapter_number}章")
        try:
            success = await analyze_chapter_background(
                chapter_id=chapter_id,
                user_id=user_id,
                project_id=project_id,
                task_id=task_id,
                ai_service=ai_service,
                provider_config_id=provider_config_id,
                model=model,
            )
            if not success:
                logger.warning(f"⚠️ 一键顺序分析返回失败: chapter_id={chapter_id}, task_id={task_id}")
        except Exception as e:
            # analyze_chapter_background 内部已处理任务失败状态，这里仅保护顺序队列不中断
            logger.error(
                f"❌ 一键顺序分析异常（已继续后续章节） chapter_id={chapter_id}, task_id={task_id}: {str(e)}",
                exc_info=True
            )


@router.post(
    "/project/{project_id}/analysis/analyze-unanalyzed",
    summary="一键按章节顺序分析未分析章节",
    response_model=BatchAnalyzeUnanalyzedResponse
)
async def batch_analyze_unanalyzed_chapters(
    project_id: str,
    payload: BatchAnalyzeUnanalyzedRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """自动识别项目中未完成分析的章节，并按章节顺序逐个启动分析。"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    # 验证项目权限
    await verify_project_access(project_id, user_id, db)

    # 查询目标章节（可选限制 chapter_ids）
    chapter_query = select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number)
    if payload.chapter_ids and len(payload.chapter_ids) > 0:
        chapter_query = chapter_query.where(Chapter.id.in_(payload.chapter_ids))

    chapter_result = await db.execute(chapter_query)
    chapters = chapter_result.scalars().all()

    if not chapters:
        return {
            "project_id": project_id,
            "total_candidates": 0,
            "total_started": 0,
            "total_skipped_no_content": 0,
            "total_skipped_running": 0,
            "total_already_completed": 0,
            "started_tasks": {}
        }

    chapter_ids = [chapter.id for chapter in chapters]

    # 查询每个章节最新分析任务
    tasks_result = await db.execute(
        select(AnalysisTask)
        .where(AnalysisTask.chapter_id.in_(chapter_ids))
        .order_by(AnalysisTask.chapter_id, AnalysisTask.created_at.desc())
    )
    all_tasks = tasks_result.scalars().all()

    latest_task_map: dict[str, AnalysisTask] = {}
    for task in all_tasks:
        if task.chapter_id not in latest_task_map:
            latest_task_map[task.chapter_id] = task

    total_candidates = 0
    total_skipped_no_content = 0
    total_skipped_running = 0
    total_already_completed = 0
    started_tasks: dict[str, dict] = {}
    tasks_to_start: list[tuple[Chapter, AnalysisTask]] = []

    for chapter in chapters:
        # 无内容章节直接跳过
        if not chapter.content or chapter.content.strip() == "":
            total_skipped_no_content += 1
            continue

        total_candidates += 1
        latest_task = latest_task_map.get(chapter.id)

        # 已在队列/分析中，跳过
        if (
            latest_task
            and latest_task.status in ("pending", "running")
            and analysis_task_matches_content(latest_task, chapter)
        ):
            total_skipped_running += 1
            continue

        # 已分析完成，跳过
        if (
            latest_task
            and latest_task.status == "completed"
            and latest_task.materialized_at is not None
            and analysis_task_matches_content(latest_task, chapter)
        ):
            total_already_completed += 1
            continue

        # 无任务/失败/未知状态，重新发起分析
        analysis_task = create_pending_analysis_task(
            chapter=chapter,
            user_id=user_id,
        )
        db.add(analysis_task)
        tasks_to_start.append((chapter, analysis_task))

    if tasks_to_start:
        try:
            await db.flush()

            for chapter, analysis_task in tasks_to_start:
                started_tasks[chapter.id] = _build_analysis_task_status_payload(chapter.id, analysis_task)

            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ 一键分析创建任务失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"一键分析创建任务失败: {str(e)}")

        # 提交后立即按章节顺序调度后台分析（逐章执行）
        tasks_queue = [
            {
                "chapter_id": chapter.id,
                "chapter_number": chapter.chapter_number,
                "task_id": analysis_task.id
            }
            for chapter, analysis_task in tasks_to_start
        ]
        _schedule_analysis_background(
            _run_batch_analysis_in_sequence(
                tasks_queue=tasks_queue,
                user_id=user_id,
                project_id=project_id,
                provider_config_id=payload.provider_config_id,
                model=payload.model,
            )
        )

    return {
        "project_id": project_id,
        "total_candidates": total_candidates,
        "total_started": len(tasks_to_start),
        "total_skipped_no_content": total_skipped_no_content,
        "total_skipped_running": total_skipped_running,
        "total_already_completed": total_already_completed,
        "started_tasks": started_tasks
    }


@router.get("/{chapter_id}/analysis", summary="获取章节分析结果")
async def get_chapter_analysis(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    获取章节的完整分析结果
    
    返回:
    - analysis_data: 完整的分析数据(JSON)
    - summary: 分析摘要文本
    - memories: 提取的记忆列表
    - created_at: 分析时间
    """
    # 先获取章节以验证权限
    chapter_result_check = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter_check = chapter_result_check.scalar_one_or_none()
    if chapter_check:
        # 验证用户权限
        user_id = getattr(request.state, 'user_id', None)
        await verify_project_access(chapter_check.project_id, user_id, db)
    
    # 获取分析结果
    analysis_result = await db.execute(
        select(PlotAnalysis)
        .where(PlotAnalysis.chapter_id == chapter_id)
        .order_by(PlotAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = analysis_result.scalar_one_or_none()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="该章节暂无分析结果")
    
    # 获取相关记忆
    memories_result = await db.execute(
        select(StoryMemory)
        .where(StoryMemory.chapter_id == chapter_id)
        .order_by(StoryMemory.importance_score.desc())
    )
    memories = memories_result.scalars().all()
    
    return {
        "chapter_id": chapter_id,
        "analysis": analysis.to_dict(),  # 使用to_dict()方法
        "memories": [
            {
                "id": mem.id,
                "type": mem.memory_type,
                "title": mem.title,
                "content": mem.content,
                "importance": mem.importance_score,
                "tags": mem.tags,
                "is_foreshadow": mem.is_foreshadow,
                "position": mem.chapter_position,
                "related_characters": mem.related_characters
            }
            for mem in memories
        ],
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None
    }


@router.get("/{chapter_id}/annotations", summary="获取章节标注数据")
async def get_chapter_annotations(
    chapter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    获取章节的标注数据（用于前端展示标注）
    
    返回格式化的标注列表，包含精确位置信息
    适用于章节内容的可视化标注展示
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    
    # 获取章节
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证项目访问权限
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 获取分析结果
    analysis_result = await db.execute(
        select(PlotAnalysis)
        .where(PlotAnalysis.chapter_id == chapter_id)
        .order_by(PlotAnalysis.created_at.desc())
        .limit(1)
    )
    analysis = analysis_result.scalar_one_or_none()
    
    # 获取记忆
    memories_result = await db.execute(
        select(StoryMemory)
        .where(StoryMemory.chapter_id == chapter_id)
        .order_by(StoryMemory.importance_score.desc())
    )
    memories = memories_result.scalars().all()
    
    # 构建标注数据
    annotations = []
    
    for mem in memories:
        # 优先从数据库读取位置信息
        position = mem.chapter_position if mem.chapter_position is not None else -1
        length = mem.text_length if hasattr(mem, 'text_length') and mem.text_length is not None else 0
        metadata_extra = {}
        
        # 如果数据库中没有位置信息，尝试从分析数据中重新计算
        if position == -1 and analysis and chapter.content:
            # 根据记忆类型从分析数据中查找对应项
            if mem.memory_type == 'hook' and analysis.hooks:
                for hook in analysis.hooks:
                    # 通过标题或内容匹配
                    if mem.title and hook.get('type') in mem.title:
                        keyword = hook.get('keyword', '')
                        if keyword:
                            pos = chapter.content.find(keyword)
                            if pos != -1:
                                position = pos
                                length = len(keyword)
                        metadata_extra["strength"] = hook.get('strength', 5)
                        metadata_extra["position_desc"] = hook.get('position', '')
                        break
            
            elif mem.memory_type == 'foreshadow' and analysis.foreshadows:
                for foreshadow in analysis.foreshadows:
                    if foreshadow.get('content') in mem.content:
                        keyword = foreshadow.get('keyword', '')
                        if keyword:
                            pos = chapter.content.find(keyword)
                            if pos != -1:
                                position = pos
                                length = len(keyword)
                        metadata_extra["foreshadow_type"] = foreshadow.get('type', 'planted')
                        metadata_extra["strength"] = foreshadow.get('strength', 5)
                        break
            
            elif mem.memory_type == 'plot_point' and analysis.plot_points:
                for plot_point in analysis.plot_points:
                    if plot_point.get('content') in mem.content:
                        keyword = plot_point.get('keyword', '')
                        if keyword:
                            pos = chapter.content.find(keyword)
                            if pos != -1:
                                position = pos
                                length = len(keyword)
                        break
        else:
            # 如果数据库有位置，也从分析数据中提取额外的元数据
            if analysis:
                if mem.memory_type == 'hook' and analysis.hooks:
                    for hook in analysis.hooks:
                        if mem.title and hook.get('type') in mem.title:
                            metadata_extra["strength"] = hook.get('strength', 5)
                            metadata_extra["position_desc"] = hook.get('position', '')
                            break
                
                elif mem.memory_type == 'foreshadow' and analysis.foreshadows:
                    for foreshadow in analysis.foreshadows:
                        if foreshadow.get('content') in mem.content:
                            metadata_extra["foreshadow_type"] = foreshadow.get('type', 'planted')
                            metadata_extra["strength"] = foreshadow.get('strength', 5)
                            break
        
        annotation = {
            "id": mem.id,
            "type": mem.memory_type,
            "title": mem.title,
            "content": mem.content,
            "importance": mem.importance_score or 0.5,
            "position": position,
            "length": length,
            "tags": mem.tags or [],
            "metadata": {
                "is_foreshadow": mem.is_foreshadow,
                "related_characters": mem.related_characters or [],
                "related_locations": mem.related_locations or [],
                **metadata_extra
            }
        }
        
        annotations.append(annotation)
    
    return {
        "chapter_id": chapter_id,
        "chapter_number": chapter.chapter_number,
        "title": chapter.title,
        "word_count": chapter.word_count or 0,
        "annotations": annotations,
        "has_analysis": analysis is not None,
        "summary": {
            "total_annotations": len(annotations),
            "hooks": len([a for a in annotations if a["type"] == "hook"]),
            "foreshadows": len([a for a in annotations if a["type"] == "foreshadow"]),
            "plot_points": len([a for a in annotations if a["type"] == "plot_point"]),
            "character_events": len([a for a in annotations if a["type"] == "character_event"])
        }
    }


@router.post("/{chapter_id}/analyze", summary="手动触发章节分析")
async def trigger_chapter_analysis(
    chapter_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    payload: ChapterAnalysisRequest = ChapterAnalysisRequest(),
    db: AsyncSession = Depends(get_db)
):
    """
    手动触发章节分析(用于重新分析或分析旧章节)
    """
    # 从请求中获取用户ID
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    # 验证章节存在
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    if not chapter.content or chapter.content.strip() == "":
        raise HTTPException(status_code=400, detail="章节内容为空，无法分析")
    
    # 获取项目信息
    project_result = await db.execute(
        select(Project).where(Project.id == chapter.project_id)
    )
    project = project_result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 避免重复点击或状态轮询误判后创建并发分析任务。
    existing_task_result = await db.execute(
        select(AnalysisTask)
        .where(AnalysisTask.chapter_id == chapter_id)
        .order_by(AnalysisTask.created_at.desc())
        .limit(1)
    )
    existing_task = existing_task_result.scalar_one_or_none()
    if (
        existing_task
        and existing_task.status in ("pending", "running")
        and analysis_task_matches_content(existing_task, chapter)
    ):
        return {
            "task_id": existing_task.id,
            "chapter_id": chapter_id,
            "status": existing_task.status,
            "message": "已有分析任务正在执行"
        }
    if (
        existing_task
        and existing_task.status == "completed"
        and existing_task.materialized_at is not None
        and analysis_task_matches_content(existing_task, chapter)
    ):
        return {
            "task_id": existing_task.id,
            "chapter_id": chapter_id,
            "status": existing_task.status,
            "message": "当前正文已完成分析",
        }
    
    # 创建分析任务
    analysis_task = create_pending_analysis_task(
        chapter=chapter,
        user_id=user_id,
    )
    db.add(analysis_task)
    await db.commit()
    
    task_id = analysis_task.id
    logger.info(f"📋 创建分析任务: {task_id}, 章节: {chapter_id}")
    
    # 刷新数据库会话，确保其他会话可以看到新任务
    await db.refresh(analysis_task)
    
    # 短暂延迟确保SQLite WAL完成写入（让其他会话可见）
    await asyncio.sleep(3)
    
    # 直接启动后台分析（并发执行）
    background_tasks.add_task(
        analyze_chapter_background,
        chapter_id=chapter_id,
        user_id=user_id,
        project_id=project.id,
        task_id=task_id,
        provider_config_id=payload.provider_config_id,
        model=payload.model,
    )
    
    return {
        "task_id": task_id,
        "chapter_id": chapter_id,
        "status": "pending",
        "message": "分析任务已创建并开始执行"
    }



def calculate_estimated_time(
    chapter_count: int,
    target_word_count: int,
    enable_analysis: bool
) -> int:
    """
    计算预估耗时（分钟）
    
    基准：
    - 生成3000字约需2分钟
    - 分析约需1分钟
    """
    generation_time_per_chapter = (target_word_count / 3000) * 2
    analysis_time_per_chapter = 1 if enable_analysis else 0
    
    total_time = chapter_count * (generation_time_per_chapter + analysis_time_per_chapter)
    
    return max(1, int(total_time))


class BatchCompareRequest(BaseModel):
    """批量候选预览：各章独立使用冻结上下文生成，不形成连续正文。"""
    start_chapter_number: int = Field(..., description="起始章节序号")
    count: int = Field(..., description="章节数量", ge=1, le=10)
    selections: List[LLMComparisonSelection] = Field(..., min_length=2, max_length=4)
    style_id: Optional[int] = None
    target_word_count: int = Field(2500, ge=500, le=10000)
    enable_mcp: bool = False
    narrative_perspective: Optional[str] = None
    skill_key: Optional[str] = None


@router.post("/project/{project_id}/batch-compare", summary="批量生成各章独立候选预览")
async def batch_compare_chapters(
    project_id: str,
    payload: BatchCompareRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """各章独立创建候选预览；未采用结果不会成为后续章节的正式上下文。"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    await verify_project_access(project_id, user_id, db)

    result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_number)
    )
    all_chapters = result.scalars().all()
    target = [
        ch for ch in all_chapters
        if payload.start_chapter_number <= ch.chapter_number < payload.start_chapter_number + payload.count
    ]
    if not target:
        raise HTTPException(status_code=404, detail="指定范围内没有章节")

    # 起始章节的前一章必须已完成分析（否则上下文滞后，候选质量受影响）
    analysis_ready, analysis_msg = await check_previous_analysis_ready(db, target[0])
    if not analysis_ready and not getattr(payload, 'skip_analysis_check', False):
        raise HTTPException(status_code=409, detail=f"批量对比需先保证上下文连贯：{analysis_msg}")

    # 登记批量对比任务（复用批量任务表，task_type=batch_compare，前端悬浮任务框可查看进度）
    compare_task = BatchGenerationTask(
        project_id=project_id, user_id=user_id, task_type="batch_compare",
        start_chapter_number=payload.start_chapter_number, chapter_count=len(target),
        chapter_ids=[ch.id for ch in target],
        style_id=payload.style_id, target_word_count=payload.target_word_count,
        enable_analysis=False, status="running", total_chapters=len(target),
        completed_chapters=0, failed_chapters=[], max_retries=0,
        started_at=datetime.now(),
    )
    db.add(compare_task)
    await db.commit()
    await db.refresh(compare_task)

    engine = await get_engine(user_id)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    created_batches = []
    for chapter in target:
        try:
            batch, _ = await create_chapter_comparison(
                db, chapter=chapter, user_id=user_id,
                request=ChapterComparisonCreateRequest(
                    selections=[item.model_dump() for item in payload.selections],
                    style_id=payload.style_id,
                    target_word_count=payload.target_word_count,
                    enable_mcp=payload.enable_mcp,
                    narrative_perspective=payload.narrative_perspective,
                    skill_key=payload.skill_key,
                ),
            )
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=f"第{chapter.chapter_number}章：{exc}")
        _schedule_comparison_background(run_batch(
            session_factory, batch_id=batch.id, user_id=user_id,
            generate=generate_chapter_candidate, concurrency=2,
        ))
        created_batches.append({"chapter_number": chapter.chapter_number, "chapter_id": chapter.id, "batch_id": batch.id})

    return {
        "task_id": compare_task.id,
        "message": (
            f"已创建 {len(created_batches)} 章的独立候选预览"
            f"（每章 {len(payload.selections)} 个候选，不会自动连续创作）"
        ),
        "batches": created_batches,
    }


@router.post("/project/{project_id}/batch-generate", response_model=BatchGenerateResponse, summary="批量顺序生成章节内容")
async def batch_generate_chapters_in_order(
    project_id: str,
    batch_request: BatchGenerateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    从指定章节开始，按顺序批量生成指定数量的章节
    
    特性：
    1. 严格按章节序号顺序生成（不可跳过）
    2. 自动检测起始章节是否可生成
    3. 可选同步分析（影响耗时和质量）
    4. 失败后终止，不继续后续章节
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    # 验证项目存在和用户权限
    project = await verify_project_access(project_id, user_id, db)
    
    # 获取项目的所有章节，按序号排序
    result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_number)
    )
    all_chapters = result.scalars().all()
    
    if not all_chapters:
        raise HTTPException(status_code=404, detail="项目没有章节")
    
    # 计算要生成的章节范围
    start_number = batch_request.start_chapter_number
    end_number = start_number + batch_request.count - 1
    
    # 筛选出要生成的章节
    chapters_to_generate = [
        ch for ch in all_chapters
        if start_number <= ch.chapter_number <= end_number
    ]
    
    if not chapters_to_generate:
        raise HTTPException(status_code=404, detail="指定范围内没有章节")
    
    # 验证起始章节的前置条件
    first_chapter = chapters_to_generate[0]
    can_generate, error_msg, _ = await check_prerequisites(db, first_chapter)
    if not can_generate:
        raise HTTPException(status_code=400, detail=f"起始章节无法生成：{error_msg}")

    # 上一章分析检查不在创建时拦截：执行链会自动接管
    # （失败/缺失自动重新分析、进行中等待；skip_analysis_check 勾选时跳过）
    # 批量生成必须同步分析，否则下一章无法获得最新角色状态、记忆和伏笔上下文。
    enable_analysis = True
    
    # 创建批量生成任务
    batch_task = BatchGenerationTask(
        project_id=project_id,
        user_id=user_id,
        start_chapter_number=start_number,
        chapter_count=len(chapters_to_generate),
        chapter_ids=[ch.id for ch in chapters_to_generate],
        style_id=batch_request.style_id,
        target_word_count=batch_request.target_word_count,
        enable_analysis=enable_analysis,
        max_retries=batch_request.max_retries,
        status='pending',
        total_chapters=len(chapters_to_generate),
        completed_chapters=0,
        failed_chapters=[],
        current_retry_count=0
    )
    # 动态属性传递跳过检查标志（后台任务同进程执行可读取；不落库）
    batch_task.skip_analysis_check = batch_request.skip_analysis_check
    db.add(batch_task)
    await db.commit()
    await db.refresh(batch_task)
    
    batch_id = batch_task.id
    
    # 计算预估耗时
    estimated_time = calculate_estimated_time(
        chapter_count=len(chapters_to_generate),
        target_word_count=batch_request.target_word_count,
        enable_analysis=enable_analysis
    )
    
    logger.info(f"📦 创建批量生成任务: {batch_id}, 章节: 第{start_number}-{end_number}章, 预估耗时: {estimated_time}分钟")
    
    # 启动后台批量生成任务，传递model参数和skill_key
    background_tasks.add_task(
        execute_batch_generation_in_order,
        batch_id=batch_id,
        user_id=user_id,
        ai_service=user_ai_service,
        custom_model=batch_request.model,
        provider_config_id=batch_request.provider_config_id,
        skill_key=batch_request.skill_key,
        enable_mcp=batch_request.enable_mcp,
        narrative_perspective=batch_request.narrative_perspective
    )
    
    return BatchGenerateResponse(
        batch_id=batch_id,
        message=f"批量生成任务已创建，将生成 {len(chapters_to_generate)} 个章节",
        chapters_to_generate=[
            {
                "id": ch.id,
                "chapter_number": ch.chapter_number,
                "title": ch.title
            }
            for ch in chapters_to_generate
        ],
        estimated_time_minutes=estimated_time
    )


@router.get("/batch-generate/{batch_id}/status", response_model=BatchGenerateStatusResponse, summary="查询批量生成任务状态")
async def get_batch_generation_status(
    batch_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """查询批量生成任务的状态和进度"""
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    result = await db.execute(
        select(BatchGenerationTask).where(
            BatchGenerationTask.id == batch_id,
            BatchGenerationTask.user_id == user_id
        )
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="批量生成任务不存在")

    # batch_compare：按各章对比批次候选进度实时汇总
    if (task.task_type or "batch_generate") == "batch_compare":
        from app.models.llm_comparison import LLMComparisonBatch, LLMComparisonCandidate
        chapter_ids = task.chapter_ids or []
        done_chapters = 0
        failed_chapters = []
        any_running = False
        for cid in chapter_ids:
            batch = await db.scalar(
                select(LLMComparisonBatch)
                .where(LLMComparisonBatch.target_type == "chapter", LLMComparisonBatch.target_id == cid)
                .order_by(LLMComparisonBatch.created_at.desc()).limit(1)
            )
            if batch is None:
                any_running = True
                continue
            cands = list((await db.scalars(
                select(LLMComparisonCandidate.status).where(LLMComparisonCandidate.batch_id == batch.id)
            )).all())
            if not cands:
                any_running = True
                continue
            if all(c in ("success", "failed") for c in cands):
                if any(c == "failed" for c in cands):
                    failed_chapters.append(cid)
                done_chapters += 1
            else:
                any_running = True
        task.completed_chapters = done_chapters
        task.failed_chapters = failed_chapters
        if done_chapters >= len(chapter_ids):
            task.status = "completed"
            task.completed_at = datetime.now()
        elif not any_running and done_chapters < len(chapter_ids):
            task.status = "failed"
            task.error_message = "部分章节候选生成失败"
        else:
            task.status = "running"
        await db.commit()

    return BatchGenerateStatusResponse(
        batch_id=task.id,
        status=task.status,
        total=task.total_chapters,
        completed=task.completed_chapters,
        current_chapter_id=task.current_chapter_id,
        current_chapter_number=task.current_chapter_number,
        current_retry_count=task.current_retry_count,
        max_retries=task.max_retries,
        failed_chapters=task.failed_chapters or [],
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        error_message=task.error_message
    )


@router.get("/project/{project_id}/batch-generate/active", summary="获取项目当前运行中的批量生成任务")
async def get_active_batch_generation(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    获取项目当前运行中的批量生成任务
    用于页面刷新后恢复任务状态
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    await verify_project_access(project_id, user_id, db)
    
    result = await db.execute(
        select(BatchGenerationTask)
        .where(BatchGenerationTask.project_id == project_id)
        .where(BatchGenerationTask.user_id == user_id)
        .where(BatchGenerationTask.status.in_(['pending', 'running']))
        .order_by(BatchGenerationTask.created_at.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        return {
            "has_active_task": False,
            "task": None
        }
    
    return {
        "has_active_task": True,
        "task": {
            "batch_id": task.id,
            "status": task.status,
            "total": task.total_chapters,
            "completed": task.completed_chapters,
            "current_chapter_id": task.current_chapter_id,
            "current_chapter_number": task.current_chapter_number,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None
        }
    }


@router.post("/project/{project_id}/volume-review", summary="卷检查（后台任务，只出报告不改文）")
async def volume_review(
    project_id: str,
    payload: VolumeReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """对卷内每章执行正文审查 + 跨章逻辑检查，结果存入后台任务。"""
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    await verify_project_access(project_id, user_id, db)

    outline_result = await db.execute(select(Outline).where(Outline.id == payload.outline_id))
    outline = outline_result.scalar_one_or_none()
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    if outline.project_id != project_id:
        raise HTTPException(status_code=403, detail="大纲不属于该项目")

    from app.services.background_task_service import background_task_service
    task = await background_task_service.create_task(
        user_id=user_id,
        project_id=project_id,
        task_type="volume_review",
        task_input={"outline_id": payload.outline_id},
        db=db,
    )
    await background_task_service.spawn_background_task(
        task.id, user_id, _run_volume_review_bg
    )
    return {"task_id": task.id, "task_type": "volume_review", "status": "pending"}


async def _run_volume_review_bg(task_id: str, bg_user_id: str):
    """后台执行卷检查：逐章审查（apply_fix=False）+ 跨章 continuity 检查"""
    from app.database import get_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as BgAsyncSession
    from app.services.background_task_service import TaskProgressTracker
    from app.models.background_task import BackgroundTask

    engine = await get_engine(bg_user_id)
    AsyncSessionLocal = async_sessionmaker(engine, class_=BgAsyncSession, expire_on_commit=False)
    async with AsyncSessionLocal() as db:
        tracker = TaskProgressTracker(task_id, bg_user_id, "卷检查")
        try:
            await tracker.start()
            bg = (await db.execute(select(BackgroundTask).where(BackgroundTask.id == task_id))).scalar_one_or_none()
            if not bg:
                await tracker.error("任务不存在")
                return
            outline_id = (bg.task_input or {}).get("outline_id")
            if not outline_id:
                await tracker.error("缺少卷参数")
                return
            outline = (await db.execute(select(Outline).where(Outline.id == outline_id))).scalar_one_or_none()
            if not outline:
                await tracker.error("大纲不存在")
                return
            project_id = outline.project_id

            chapters = list((await db.scalars(
                select(Chapter).where(Chapter.outline_id == outline_id).order_by(Chapter.chapter_number)
            )).all())
            if not chapters:
                await tracker.error("该卷还没有展开的章节")
                return

            from app.services.ai_provider_service import create_routed_ai_service
            ai_service = await create_routed_ai_service(
                db, user_id=bg_user_id, usage_type="chapter_write",
                project_id=project_id, enable_mcp=False,
            )

            from app.services.chapter_review_service import review_and_fix
            chapter_reports = []
            total = len(chapters)
            for i, ch in enumerate(chapters):
                await tracker.loading(f"审查第{ch.chapter_number}章（{i + 1}/{total}）...", 0.1 + 0.8 * i / max(total, 1))
                try:
                    r = await review_and_fix(
                        db, chapter=ch, user_id=bg_user_id, ai_service=ai_service,
                        max_rounds=2, enabled=True, apply_fix=False,
                    )
                    # 保存审查记录（卷检查来源）
                    try:
                        from app.services.review_record_service import save_review_record
                        await save_review_record(db, project_id=project_id, chapter=ch, report=r, source="volume")
                    except Exception:
                        pass
                    chapter_reports.append({
                        "chapter_id": str(ch.id),
                        "chapter_number": ch.chapter_number,
                        "title": ch.title,
                        "problems": r.problems,
                        "major": r.major,
                        "rounds": r.rounds,
                        "errors": r.step_errors,
                    })
                except Exception as e:
                    logger.warning(f"⚠️ 卷检查第{ch.chapter_number}章失败: {e}")
                    chapter_reports.append({
                        "chapter_id": str(ch.id),
                        "chapter_number": ch.chapter_number,
                        "title": ch.title,
                        "problems": [],
                        "major": False,
                        "errors": [str(e)],
                    })

            # 跨章 continuity 检查（各章摘要 + 项目档案）
            volume_issues = []
            try:
                await tracker.loading("跨章逻辑检查（continuity）...", 0.95)
                volume_issues = await _check_volume_continuity(
                    db, project_id=project_id, chapters=chapters, user_id=bg_user_id, ai_service=ai_service,
                )
            except Exception as e:
                logger.warning(f"⚠️ 跨章逻辑检查失败: {e}")

            result = {
                "outline_id": outline_id,
                "outline_title": outline.title,
                "chapters": chapter_reports,
                "volume_issues": volume_issues,
            }
            bg.task_result = result
            await db.commit()
            await tracker.complete(f"卷检查完成：{total} 章，共 {sum(len(c['problems']) for c in chapter_reports)} 个问题")
            logger.info(f"✅ 卷检查完成: {outline.title}, {total} 章")
        except Exception as e:
            logger.error(f"❌ 卷检查失败: {e}")
            await tracker.error(str(e))


@router.get("/project/{project_id}/reviews", summary="获取项目各章节最近一次审查记录")
async def get_project_reviews(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """返回每章最近一条审查记录（按章节排序）"""
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    await verify_project_access(project_id, user_id, db)

    from app.models.chapter_review_record import ChapterReviewRecord
    # 取每章最新一条：子查询按 chapter_id 取最大 created_at
    records = list((await db.scalars(
        select(ChapterReviewRecord)
        .where(ChapterReviewRecord.project_id == project_id)
        .order_by(ChapterReviewRecord.chapter_number, ChapterReviewRecord.created_at.desc())
    )).all())
    latest: dict = {}
    for r in records:
        if r.chapter_id not in latest:
            latest[r.chapter_id] = r
    items = []
    for r in sorted(latest.values(), key=lambda x: (x.chapter_number, str(x.created_at))):
        items.append({
            "chapter_id": r.chapter_id,
            "chapter_number": r.chapter_number,
            "problems": json.loads(r.problems) if r.problems else [],
            "major": r.major,
            "rounds": r.rounds,
            "source": r.source,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"project_id": project_id, "items": items}


async def _check_volume_continuity(
    db: AsyncSession,
    *,
    project_id: str,
    chapters: list,
    user_id: str,
    ai_service,
) -> list:
    """跨章逻辑检查：注入 continuity SKILL，输入各章摘要 + 角色档案，输出跨章问题列表"""
    from app.services.skill_loader import build_skill_system_prompt
    from app.models.character import Character
    from app.models.memory import PlotAnalysis, StoryMemory

    characters = list((await db.scalars(select(Character).where(Character.project_id == project_id))).all())
    chars_info = "\n".join(f"- {c.name}: {(c.background or '')[:120]}" for c in characters) or "（无角色档案）"

    summaries = []
    for ch in chapters:
        summaries.append(f"第{ch.chapter_number}章《{ch.title}》：{(ch.content or '')[:400]}")
    chapters_text = "\n\n".join(summaries)

    prompt = (
        f"【任务】对以下一卷（{len(chapters)} 章）的正文做跨章逻辑检查。\n"
        "重点核查：时间线是否矛盾、人物行为是否合理、资源/伤势/身份/战力是否前后一致、"
        "伏笔是否埋下未回收、情绪与关系变化是否跳变。\n"
        "输出 JSON（不要输出其他文字）：\n"
        "{\"problems\": [{\"type\": \"逻辑连贯\", \"description\": \"问题描述（引用涉及章号）\", "
        "\"suggestion\": \"修改建议\", \"level\": \"minor|major\"}]}\n"
        "无问题输出 {\"problems\": []}。\n\n"
        f"【角色档案】\n{chars_info}\n\n"
        f"【本卷各章正文（截取）】\n{chapters_text}"
    )
    system_prompt = build_skill_system_prompt("SKILL_CONTINUITY")
    from app.services.chapter_review_service import _parse_problems
    raw = await ai_service.generate_text(prompt=prompt, system_prompt=system_prompt, temperature=0.3, auto_mcp=False)
    problems = _parse_problems(str(raw.get("content") or ""))
    for p in problems:
        p["step"] = "continuity"
    return problems


@router.post("/batch-generate/{batch_id}/cancel", summary="取消批量生成任务")
async def cancel_batch_generation(
    batch_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """取消正在进行的批量生成任务"""
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    result = await db.execute(
        select(BatchGenerationTask).where(
            BatchGenerationTask.id == batch_id,
            BatchGenerationTask.user_id == user_id
        )
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="批量生成任务不存在")
    
    if task.status in ['completed', 'failed', 'cancelled']:
        raise HTTPException(status_code=400, detail=f"任务已处于 {task.status} 状态，无法取消")
    
    task.status = 'cancelled'
    task.completed_at = datetime.now()
    await db.commit()
    
    logger.info(f"🛑 批量生成任务已取消: {batch_id}")
    
    return {
        "message": "批量生成任务已取消",
        "batch_id": batch_id,
        "completed_chapters": task.completed_chapters,
        "total_chapters": task.total_chapters
    }


async def _ensure_previous_analysis_ready(
    db: AsyncSession,
    chapter: Chapter,
    user_id: str,
    ai_service: AIService,
) -> tuple[bool, str]:
    """
    确保上一章分析就绪（自动接管）：
    - 上一章分析失败/缺失/内容变更 → 自动重新分析（同步等待完成）
    - 上一章分析进行中 → 轮询等待（最多 10 分钟）
    返回 (是否就绪, 说明/错误)。
    """
    from datetime import datetime, timedelta

    ready, msg = await check_previous_analysis_ready(db, chapter)
    if ready:
        return True, ""

    if chapter.chapter_number <= 1:
        return True, ""

    # 获取上一章及其最新分析任务
    prev_chapter = await db.scalar(
        select(Chapter)
        .where(Chapter.project_id == chapter.project_id)
        .where(Chapter.chapter_number < chapter.chapter_number)
        .order_by(Chapter.chapter_number.desc())
        .limit(1)
    )
    if not prev_chapter or not prev_chapter.content:
        return False, f"上一章（第{chapter.chapter_number - 1}章）还没有正文，无法生成第{chapter.chapter_number}章"

    latest_task = await db.scalar(
        select(AnalysisTask)
        .where(AnalysisTask.chapter_id == prev_chapter.id)
        .order_by(AnalysisTask.created_at.desc())
        .limit(1)
    )

    # 情况 1：分析进行中 → 等待完成（轮询最多 10 分钟）
    if latest_task and latest_task.status in ("pending", "running"):
        deadline = datetime.utcnow() + timedelta(minutes=10)
        timed_out = True
        while datetime.utcnow() < deadline:
            await asyncio.sleep(10)
            db.expire_all()  # 同步方法，不可 await（AsyncSession 本地操作）
            t = await db.scalar(
                select(AnalysisTask)
                .where(AnalysisTask.id == latest_task.id)
            )
            if t is None:
                timed_out = False  # 任务消失 → 落重析分支
                break
            if t.status == "completed":
                ok, _ = await check_previous_analysis_ready(db, chapter)
                if ok:
                    return True, "等待上一章分析完成"
                timed_out = False  # 完成但内容仍不匹配 → 落重析分支
                break
            if t.status == "failed":
                timed_out = False  # 失败 → 落重析分支
                break
        if timed_out:
            return False, f"等待上一章（第{chapter.chapter_number - 1}章）分析超时（10分钟），任务已终止，请稍后重试"

    # 情况 2：分析失败/缺失/内容变更 → 自动重新分析（同步等待）
    logger.info(f"🔄 自动接管：上一章（第{chapter.chapter_number - 1}章）分析未就绪，自动重新分析...")
    new_task = create_pending_analysis_task(chapter=prev_chapter, user_id=user_id)
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    ok = await analyze_chapter_background(
        chapter_id=prev_chapter.id,
        user_id=user_id,
        project_id=chapter.project_id,
        task_id=new_task.id,
        ai_service=ai_service,
    )
    if not ok:
        return False, f"自动重新分析上一章（第{chapter.chapter_number - 1}章）失败，任务已终止；可勾选「跳过上一章分析检查」继续"

    ready, msg = await check_previous_analysis_ready(db, chapter)
    if ready:
        return True, f"已自动重新分析上一章（第{chapter.chapter_number - 1}章）"
    return False, msg


async def execute_batch_generation_in_order(
    batch_id: str,
    user_id: str,
    ai_service: AIService,
    custom_model: Optional[str] = None,
    provider_config_id: Optional[str] = None,
    skill_key: Optional[str] = None,
    enable_mcp: bool = True,
    narrative_perspective: Optional[str] = None
):
    """
    按顺序执行批量生成任务（后台任务）
    - 严格按章节序号顺序
    - 任一章节失败则终止后续生成
    - 可选同步分析
    """
    db_session = None
    task = None
    write_lock = await get_db_write_lock(user_id)
    
    try:
        logger.info(f"📦 开始执行顺序批量生成任务: {batch_id}")
        
        # 创建独立数据库会话
        from app.database import get_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        
        engine = await get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        db_session = AsyncSessionLocal()
        
        # 获取任务
        task_result = await db_session.execute(
            select(BatchGenerationTask).where(BatchGenerationTask.id == batch_id)
        )
        task = task_result.scalar_one_or_none()
        
        if not task:
            logger.error(f"❌ 批量生成任务不存在: {batch_id}")
            return

        if task.status == 'cancelled':
            logger.info(f"🛑 批量生成任务启动前已取消: {batch_id}")
            return
        
        # 更新任务状态为运行中
        async with write_lock:
            await db_session.refresh(task)
            if task.status == 'cancelled':
                logger.info(f"🛑 批量生成任务启动前已取消: {batch_id}")
                return
            task.status = 'running'
            task.started_at = datetime.now()
            await db_session.commit()
        
        # 维护上一章的摘要，用于传递给下一章（防重复上下文）
        last_generated_summary = None

        # 按顺序生成每个章节
        for idx, chapter_id in enumerate(task.chapter_ids, 1):
            # 检查任务是否被取消
            await db_session.refresh(task)
            if task.status == 'cancelled':
                logger.info(f"🛑 批量生成任务已被取消: {batch_id}")
                return
            
            # 更新当前章节
            async with write_lock:
                task.current_chapter_id = chapter_id
                task.current_retry_count = 0  # 重置重试计数
                await db_session.commit()
            
            # 重试循环
            retry_count = 0
            chapter_success = False
            chapter = None
            last_error = None
            
            while retry_count <= task.max_retries and not chapter_success:
                try:
                    await db_session.refresh(task)
                    if task.status == 'cancelled':
                        logger.info(f"🛑 批量生成任务已被取消: {batch_id}")
                        return

                    # 获取章节信息
                    chapter_result = await db_session.execute(
                        select(Chapter).where(Chapter.id == chapter_id)
                    )
                    chapter = chapter_result.scalar_one_or_none()
                    
                    if not chapter:
                        raise Exception(f"章节 {chapter_id} 不存在")
                    
                    # 预缓存章节号（后续异常处理用，避免访问已过期属性）
                    current_chapter_number = chapter.chapter_number
                    
                    # 更新当前章节序号和重试次数
                    async with write_lock:
                        task.current_chapter_number = chapter.chapter_number
                        task.current_retry_count = retry_count
                        await db_session.commit()
                    
                    if retry_count > 0:
                        logger.info(f"🔄 [{idx}/{task.total_chapters}] 重试生成章节 (第{retry_count}次): 第{chapter.chapter_number}章 《{chapter.title}》")
                    else:
                        logger.info(f"📝 [{idx}/{task.total_chapters}] 开始生成章节: 第{chapter.chapter_number}章 《{chapter.title}》")
                    
                    # 检查前置条件（每次都检查，确保顺序性）
                    can_generate, error_msg, _ = await check_prerequisites(db_session, chapter)
                    if not can_generate:
                        raise Exception(f"前置条件不满足: {error_msg}")
                    analysis_ready, analysis_msg = await check_previous_analysis_ready(db_session, chapter)
                    if not analysis_ready and not getattr(task, 'skip_analysis_check', False):
                        # 自动接管：失败/缺失/变更自动重新分析，进行中等待；仍失败才中断
                        analysis_ready, analysis_msg = await _ensure_previous_analysis_ready(
                            db_session, chapter, user_id, ai_service
                        )
                        if analysis_ready:
                            logger.info(f"⚙️ 自动接管分析完成：{analysis_msg}")
                        else:
                            raise Exception(analysis_msg)
                    
                    # 生成章节内容（复用现有流式生成逻辑的核心部分），传递model参数
                    # 并获取生成后的摘要（如果生成函数支持返回）
                    generated_summary, analysis_task = await generate_single_chapter_for_batch(
                        db_session=db_session,
                        chapter=chapter,
                        user_id=user_id,
                        style_id=task.style_id,
                        target_word_count=task.target_word_count,
                        ai_service=ai_service,
                        write_lock=write_lock,
                        custom_model=custom_model,
                        provider_config_id=provider_config_id,
                        previous_summary_context=last_generated_summary,
                        skill_key=skill_key,
                        batch_id=batch_id,
                        enable_mcp=enable_mcp,
                        temp_narrative_perspective=narrative_perspective
                    )

                    await db_session.refresh(task)
                    if task.status == 'cancelled':
                        logger.info(f"🛑 批量生成任务已被取消，跳过后续处理: {batch_id}")
                        return
                    
                    # 更新上一章摘要，供下一章使用
                    if generated_summary:
                        last_generated_summary = f"第{chapter.chapter_number}章《{chapter.title}》：{generated_summary}"
                        logger.info(f"📝 已更新上一章摘要上下文: {last_generated_summary[:50]}...")
                    
                    logger.info(f"✅ 章节生成完成: 第{chapter.chapter_number}章")
                    
                    await db_session.refresh(task)
                    if task.status == 'cancelled':
                        logger.info(f"🛑 批量生成任务已被取消，跳过正式分析: {batch_id}")
                        return
                    logger.info(f"🔍 开始正式分析章节: 第{chapter.chapter_number}章")

                    # ⚡ 正文审查（生成后、分析前）：3 步流水线 + 原地修改/打回重写
                    try:
                        from app.services.chapter_review_service import review_and_fix
                        from app.services.chapter_lifecycle_service import chapter_content_hash as _cc_hash
                        from app.services.review_config_service import review_config_defaults
                        from app.models.project import Project as _ProjectModel
                        _prow = (await db_session.execute(
                            select(_ProjectModel).where(_ProjectModel.id == task.project_id)
                        )).scalar_one_or_none()
                        _rcfg = review_config_defaults(_prow.review_config if _prow else None)
                        review_report = await review_and_fix(
                            db_session,
                            chapter=chapter,
                            user_id=user_id,
                            ai_service=ai_service,
                            max_rounds=_rcfg["max_rounds"],
                            enabled=_rcfg["enabled"],
                            steps=_rcfg["steps"],
                        )
                        if review_report.final_content and review_report.final_content != chapter.content:
                            # 审查修改了正文：该章刚生成、尚未分析，直接覆盖安全；同步 content_hash
                            chapter.content = review_report.final_content
                            chapter.word_count = len(review_report.final_content)
                            try:
                                analysis_task.content_hash = _cc_hash(chapter.content)
                            except Exception:
                                pass
                            await db_session.commit()
                            logger.info(f"🔍 审查修改已应用：第{chapter.chapter_number}章，{len(review_report.problems)} 个问题"
                                        f"（major={review_report.major}，{review_report.rounds} 轮，类型：{[p['type'] for p in review_report.problems[:5]]}）")
                        elif review_report.problems:
                            logger.info(f"🔍 审查完成：第{chapter.chapter_number}章 {len(review_report.problems)} 个问题（未修改）")
                        else:
                            logger.info(f"🔍 审查通过：第{chapter.chapter_number}章无问题")
                        if review_report.step_errors:
                            logger.warning(f"⚠️ 审查部分步骤失败（不阻断）: {review_report.step_errors}")
                        # 保存审查记录（供章节列表/剧情分析页查看）
                        try:
                            from app.services.review_record_service import save_review_record
                            await save_review_record(db_session, project_id=task.project_id, chapter=chapter, report=review_report, source="auto")
                        except Exception:
                            pass
                    except Exception as review_err:
                        logger.warning(f"⚠️ 章节审查失败（不阻断生成）: {review_err}")

                    # 分析使用 chapter_analysis 路由（默认 pro，稳定输出大 JSON；
                    # 批量生成所选模型常用于创作，分析这类复杂结构化输出需稳定模型）
                    try:
                        from app.services.ai_provider_service import create_routed_ai_service
                        analysis_ai_service = await create_routed_ai_service(
                            db_session, user_id=user_id, usage_type="chapter_analysis",
                            project_id=task.project_id, enable_mcp=False,
                        )
                    except Exception:
                        analysis_ai_service = ai_service
                    analysis_result = await analyze_chapter_background(
                        chapter_id=chapter_id,
                        user_id=user_id,
                        project_id=task.project_id,
                        task_id=analysis_task.id,
                        ai_service=analysis_ai_service,
                        model=None,
                        enable_mcp=False,
                    )

                    if not analysis_result:
                        error_message = "分析函数返回失败"
                        logger.error(f"❌ 章节分析失败，批量生成中断: 第{chapter.chapter_number}章")
                        failed_info = {
                            'chapter_id': chapter_id,
                            'chapter_number': chapter.chapter_number,
                            'title': chapter.title,
                            'error': f"分析失败: {error_message}",
                            'retry_count': 1
                        }
                        async with write_lock:
                            if task.failed_chapters is None:
                                task.failed_chapters = []
                            task.failed_chapters.append(failed_info)
                            task.status = 'failed'
                            task.error_message = f"第{chapter.chapter_number}章分析失败: {error_message}"[:500]
                            task.completed_at = datetime.now()
                            task.current_retry_count = 0
                            await db_session.commit()
                        return

                    logger.info(f"✅ 章节分析成功: 第{chapter.chapter_number}章")
                    
                    # 标记成功
                    chapter_success = True
                    
                    # 更新完成数
                    async with write_lock:
                        task.completed_chapters += 1
                        task.current_retry_count = 0  # 重置重试计数
                        await db_session.commit()
                    
                    logger.info(f"✅ 进度: {task.completed_chapters}/{task.total_chapters}")
                    
                except Exception as e:
                    last_error = str(e)
                    await db_session.refresh(task)
                    if task.status == 'cancelled':
                        logger.info(f"🛑 批量生成任务已被取消: {batch_id}")
                        return
                    # 用预缓存的章节号（异常时 chapter 可能已过期，访问属性会触发额外加载/掩盖根因）
                    error_msg = f"第{current_chapter_number}章出错: {last_error}"
                    logger.error(f"❌ {error_msg}")
                    
                    retry_count += 1
                    
                    # 如果还有重试机会，等待一小段时间后重试
                    if retry_count <= task.max_retries:
                        wait_time = min(2 ** retry_count, 10)  # 指数退避，最多等待10秒
                        logger.info(f"⏳ 等待 {wait_time} 秒后重试...")
                        await asyncio.sleep(wait_time)
                    else:
                        # 达到最大重试次数，记录失败信息
                        logger.error(f"❌ 章节生成失败，已达最大重试次数({task.max_retries}): 第{chapter.chapter_number if chapter else '?'}章")
                        
                        failed_info = {
                            'chapter_id': chapter_id,
                            'chapter_number': chapter.chapter_number if chapter else -1,
                            'title': chapter.title if chapter else '未知',
                            'error': last_error,
                            'retry_count': retry_count - 1
                        }
                        
                        async with write_lock:
                            if task.failed_chapters is None:
                                task.failed_chapters = []
                            task.failed_chapters.append(failed_info)
                            
                            # 标记任务失败并终止
                            task.status = 'failed'
                            task.error_message = f"第{chapter.chapter_number}章生成失败(重试{retry_count-1}次): {last_error}"[:500]
                            task.completed_at = datetime.now()
                            task.current_retry_count = 0
                            await db_session.commit()
                        
                        # ⚠️ 如果启用了同步分析，任何错误都应该中断任务
                        # 因为章节生成或分析失败会影响后续章节的职业更新和剧情连贯性
                        if task.enable_analysis:
                            logger.error(f"🛑 批量生成中断: 因启用同步分析，任何错误都会中断任务以确保职业信息和剧情连贯性")
                        else:
                            logger.error(f"🛑 批量生成终止于第{chapter.chapter_number}章")
                        
                        return
        
        # 全部完成
        async with write_lock:
            await db_session.refresh(task)
            if task.status == 'cancelled':
                logger.info(f"🛑 批量生成任务已被取消，跳过完成状态覆盖: {batch_id}")
                return
            task.status = 'completed'
            task.completed_at = datetime.now()
            task.current_chapter_id = None
            task.current_chapter_number = None
            await db_session.commit()
        
        logger.info(f"✅ 批量生成任务全部完成: {batch_id}, 成功生成 {task.completed_chapters} 章")
        
    except Exception as e:
        import traceback
        logger.error(f"❌ 批量生成任务异常: {str(e)}\n{traceback.format_exc()}")
        if db_session and task:
            try:
                async with write_lock:
                    await db_session.refresh(task)
                    if task.status != 'cancelled':
                        task.status = 'failed'
                        task.error_message = str(e)[:500]
                        task.completed_at = datetime.now()
                        await db_session.commit()
            except Exception as commit_error:
                logger.error(f"❌ 更新任务失败状态失败: {str(commit_error)}")
    finally:
        if db_session:
            await db_session.close()


async def generate_single_chapter_for_batch(
    db_session: AsyncSession,
    chapter: Chapter,
    user_id: str,
    style_id: Optional[int],
    target_word_count: int,
    ai_service: AIService,
    write_lock: Lock,
    custom_model: Optional[str] = None,
    provider_config_id: Optional[str] = None,
    previous_summary_context: Optional[str] = None,
    skill_key: Optional[str] = None,
    batch_id: Optional[str] = None,
    enable_mcp: bool = True,
    temp_narrative_perspective: Optional[str] = None
) -> tuple[str, AnalysisTask]:
    """
    为批量生成执行单个章节的生成（非流式）
    复用现有生成逻辑的核心部分
    
    Returns:
        生成章节摘要和与该正文绑定的正式分析任务
    """
    expected_content_hash = chapter_content_hash(chapter.content)

    # 获取项目信息
    project_result = await db_session.execute(
        select(Project).where(Project.id == chapter.project_id)
    )
    project = project_result.scalar_one_or_none()
    if not project:
        raise Exception("项目不存在")
    
    # 获取项目的大纲模式
    outline_mode = project.outline_mode if project else 'one-to-many'
    logger.info(f"📋 批量生成 - 项目大纲模式: {outline_mode}")
    
    # 获取对应的大纲（优先使用 chapter.outline_id 直接关联）
    if chapter.outline_id:
        outline_result = await db_session.execute(
            select(Outline).where(Outline.id == chapter.outline_id)
        )
    else:
        # 回退到按序号查找
        outline_result = await db_session.execute(
            select(Outline)
            .where(Outline.project_id == chapter.project_id)
            .where(Outline.order_index == chapter.chapter_number)
        )
    outline = outline_result.scalar_one_or_none()
    
    # 获取写作风格
    style_content = ""
    if style_id:
        style_result = await db_session.execute(
            select(WritingStyle).where(WritingStyle.id == style_id)
        )
        style = style_result.scalar_one_or_none()
        if style:
            if style.user_id is None or style.user_id == user_id:
                style_content = style.prompt_content or ""
    
    # 🚀 根据大纲模式选择独立的上下文构建器（批量生成）
    if outline_mode == 'one-to-one':
        # 1-1模式
        logger.info(f"🔧 批量生成 - [1-1模式] 使用 OneToOneContextBuilder")
        context_builder = OneToOneContextBuilder(
            memory_service=memory_service,
            foreshadow_service=foreshadow_service
        )
        chapter_context = await context_builder.build(
            chapter=chapter,
            project=project,
            outline=outline,
            user_id=user_id,
            db=db_session,
            target_word_count=target_word_count
        )
    else:
        # 1-N模式：使用独立的完整构建器
        logger.info(f"🔧 批量生成 - [1-N模式] 使用 OneToManyContextBuilder")
        context_builder = OneToManyContextBuilder(
            memory_service=memory_service,
            foreshadow_service=foreshadow_service
        )
        chapter_context = await context_builder.build(
            chapter=chapter,
            project=project,
            outline=outline,
            user_id=user_id,
            db=db_session,
            style_content=style_content,
            target_word_count=target_word_count,
            temp_narrative_perspective=temp_narrative_perspective
        )
    
    # 日志输出统计信息
    logger.info(f"📊 批量生成 - 优化上下文统计:")
    logger.info(f"  - 章节序号: {chapter.chapter_number}")
    logger.info(f"  - 衔接锚点长度: {len(chapter_context.continuation_point or '')} 字符")
    logger.info(f"  - 相关记忆: {chapter_context.context_stats.get('memory_count', 0)} 条")
    logger.info(f"  - 总上下文长度: {chapter_context.context_stats.get('total_length', 0)} 字符")
    
    # 🚀 根据大纲模式选择提示词模板（批量生成）
    # 统一使用 context_builder 构建的 chapter_context 结果，与单章生成保持一致
    if outline_mode == 'one-to-one':
        # 1-1模式
        if chapter_context.continuation_point:
            # 有上一章内容
            template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_ONE_NEXT", user_id, db_session)
            base_prompt = PromptService.format_prompt(
                template,
                project_title=project.title,
                chapter_number=chapter.chapter_number,
                chapter_title=chapter.title,
                chapter_outline=chapter_context.chapter_outline,
                target_word_count=target_word_count,
                genre=project.genre or '未设定',
                narrative_perspective=temp_narrative_perspective or project.narrative_perspective or '第三人称',
                previous_chapter_content=chapter_context.continuation_point,
                characters_info=chapter_context.chapter_characters or '暂无角色信息',
                chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                relevant_memories=chapter_context.relevant_memories or '暂无相关记忆',
                previous_chapter_summary=chapter_context.previous_chapter_summary or '',
                recent_chapters_context=chapter_context.recent_chapters_context or '暂无最近章节摘要'
            )
        else:
            # 第一章
            template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_ONE", user_id, db_session)
            base_prompt = PromptService.format_prompt(
                template,
                project_title=project.title,
                chapter_number=chapter.chapter_number,
                chapter_title=chapter.title,
                chapter_outline=chapter_context.chapter_outline,
                target_word_count=target_word_count,
                genre=project.genre or '未设定',
                narrative_perspective=temp_narrative_perspective or project.narrative_perspective or '第三人称',
                characters_info=chapter_context.chapter_characters or '暂无角色信息',
                chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                relevant_memories=chapter_context.relevant_memories or '暂无相关记忆'
            )
    else:
        # 1-n模式：使用 context_builder 构建的结果，与单章生成保持一致
        if chapter_context.continuation_point:
            # 有前置内容，使用 WITH_CONTEXT 模板
            # 优先使用 context_builder 的摘要，其次使用传入的 previous_summary_context
            final_prev_summary = "（无上一章摘要，请根据锚点续写）"
            
            if chapter_context.previous_chapter_summary:
                final_prev_summary = chapter_context.previous_chapter_summary
            elif previous_summary_context:
                final_prev_summary = previous_summary_context
                    
            template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_MANY_NEXT", user_id, db_session)
            base_prompt = PromptService.format_prompt(
                template,
                project_title=project.title,
                chapter_number=chapter.chapter_number,
                chapter_title=chapter.title,
                chapter_outline=chapter_context.chapter_outline,
                target_word_count=target_word_count,
                continuation_point=chapter_context.continuation_point,
                genre=project.genre or '未设定',
                narrative_perspective=temp_narrative_perspective or project.narrative_perspective or '第三人称',
                characters_info=chapter_context.chapter_characters or '暂无角色信息',
                chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                previous_chapter_summary=final_prev_summary,
                recent_chapters_context=chapter_context.recent_chapters_context or '',
                relevant_memories=chapter_context.relevant_memories or ''
            )
        else:
            # 第一章，使用无前置内容模板
            template = await PromptService.get_template("CHAPTER_GENERATION_ONE_TO_MANY", user_id, db_session)
            base_prompt = PromptService.format_prompt(
                template,
                project_title=project.title,
                chapter_number=chapter.chapter_number,
                chapter_title=chapter.title,
                chapter_outline=chapter_context.chapter_outline,
                target_word_count=target_word_count,
                genre=project.genre or '未设定',
                narrative_perspective=temp_narrative_perspective or project.narrative_perspective or '第三人称',
                characters_info=chapter_context.chapter_characters or '暂无角色信息',
                chapter_careers=chapter_context.chapter_careers or '暂无职业信息',
                foreshadow_reminders=chapter_context.foreshadow_reminders or '暂无需要关注的伏笔',
                relevant_memories=chapter_context.relevant_memories or '暂无相关记忆'
            )
    
    # 应用写作风格
    if style_content:
        prompt = WritingStyleManager.apply_style_to_prompt(base_prompt, style_content)
    else:
        prompt = base_prompt
    
    # 🎨 将 Skill / 写作风格注入到系统提示词（批量生成）
    system_prompt_with_style = None

    # ⚡ Skill 支持
    if skill_key:
        try:
            from app.services.skill_loader import get_all_skills_cached
            skills = get_all_skills_cached()
            skill = next((s for s in skills if s["template_key"] == skill_key), None)
            if skill:
                skill_content = skill["content"]
                skill_name = skill["template_name"]
                system_prompt_with_style = f"""【⚡ Skill 工作流：{skill_name}】

{skill_content}

⚠️ 请严格遵循上述 Skill 工作流指令进行创作！"""
                if style_content:
                    system_prompt_with_style += f"""

【🎨 写作风格要求 - 补充】

{style_content}"""
                logger.info(f"⚡ 批量生成 - 已将 Skill '{skill_name}' 注入系统提示词（{len(skill_content)}字符）")
            else:
                logger.warning(f"⚠️ 批量生成 - 未找到 Skill: {skill_key}")
        except Exception as skill_err:
            logger.warning(f"⚠️ 批量生成 - 加载 Skill 失败: {skill_err}")

    if not system_prompt_with_style and style_content:
        system_prompt_with_style = f"""【🎨 写作风格要求 - 最高优先级】

{style_content}

⚠️ 请严格遵循上述写作风格要求进行创作，这是最重要的指令！
确保在整个章节创作过程中始终保持风格的一致性。"""
        logger.info(f"✅ 批量生成 - 已将写作风格注入系统提示词（{len(style_content)}字符）")
    
    # 🔢 计算 max_tokens 限制（批量生成）
    # 中文字符约 1.5-2 个 token，使用 2.5 倍系数确保有足够空间完成段落
    # 同时设置上限防止过长，下限确保基本可用
    explicit_max = None  # 批量生成无 task_input；如需可加 max_tokens 参数
    if explicit_max:
        calculated_max_tokens = max(2000, min(int(explicit_max), 16000))
    else:
        calculated_max_tokens = int(target_word_count * 3)
        calculated_max_tokens = max(2000, min(calculated_max_tokens, 16000))  # 限制在 2000-16000 之间
    logger.info(f"📊 批量生成 - 目标字数: {target_word_count}, 计算 max_tokens: {calculated_max_tokens}")
    
    # 非流式生成内容
    full_content = ""
    # 若指定了 AI 服务配置，为本章创建对应服务（否则用请求注入的默认服务）
    if provider_config_id:
        from app.services.ai_provider_service import create_routed_ai_service
        ai_service = await create_routed_ai_service(
            db_session, user_id=user_id, usage_type="chapter_write",
            provider_config_id=provider_config_id, model=custom_model,
            project_id=chapter.project_id, chapter_id=chapter.id,
            task_trace_id=f"batch-{batch_id}", enable_mcp=bool(enable_mcp),
        )
        logger.info(f"  批量生成使用指定 AI 服务: {provider_config_id} model={custom_model}")
    # 准备生成参数
    generate_kwargs = {
        "prompt": prompt,
        "system_prompt": system_prompt_with_style,
        "tool_choice": "required",
        "max_tokens": calculated_max_tokens,
        "auto_mcp": bool(enable_mcp)
    }
    # 如果传入了自定义模型，使用指定的模型
    if custom_model:
        generate_kwargs["model"] = custom_model
        logger.info(f"  批量生成使用自定义模型: {custom_model}")
    
    async def _is_batch_cancelled() -> bool:
        if not batch_id:
            return False
        result = await db_session.execute(
            select(BatchGenerationTask.status).where(BatchGenerationTask.id == batch_id)
        )
        return result.scalar_one_or_none() == 'cancelled'

    # 批量生成中的流式生成（非SSE，不需要修改进度显示）
    chunk_count = 0
    async for chunk in ai_service.generate_text_stream(**generate_kwargs):
        if chunk_count % 10 == 0 and await _is_batch_cancelled():
            logger.info(f"🛑 批量生成单章流式生成被取消: batch={batch_id}, chapter={chapter.id}")
            raise Exception("批量生成任务已取消")
        full_content += chunk
        chunk_count += 1

    if await _is_batch_cancelled():
        logger.info(f"🛑 批量生成保存前被取消: batch={batch_id}, chapter={chapter.id}")
        raise Exception("批量生成任务已取消")
    
    # 将正文、字数、历史、计划伏笔和分析任务作为一个正式版本提交。
    async with write_lock:
        # 空内容/字数过短校验（推理型模型可能在 token 上限内只输出思考）
        new_word_count = len(full_content)
        if new_word_count < int(target_word_count * 0.7):
            logger.warning(f"  批量生成 - 章节内容过短({new_word_count}字 < 目标{target_word_count}的70%)，触发重试")
            raise ValueError(f"章节内容过短({new_word_count}字)，未达目标字数的70%")
        formal_result = await persist_formal_chapter_content(
            db=db_session,
            chapter_id=chapter.id,
            user_id=user_id,
            content=full_content,
            prompt=f"批量生成: 第{chapter.chapter_number}章 {chapter.title}",
            model=custom_model or "default",
            foreshadow_service=foreshadow_service,
            memory_service=memory_service,
            expected_content_hash=expected_content_hash,
        )
        chapter = formal_result.chapter
    
    logger.info(f"✅ 单章节生成完成: 第{chapter.chapter_number}章，共 {new_word_count} 字")
    
    # 生成简短摘要返回
    summary_preview = _build_lightweight_chapter_summary(full_content)
    
    return summary_preview, formal_result.analysis_task




# ==================== 章节重新生成相关API ====================

@router.post("/{chapter_id}/regenerate-stream", summary="流式重新生成章节内容")
async def regenerate_chapter_stream(
    chapter_id: str,
    request: Request,
    regenerate_request: ChapterRegenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    根据分析建议或自定义指令重新生成章节内容（流式返回）
    
    工作流程：
    1. 验证章节和分析结果
    2. 创建重新生成任务
    3. 构建修改指令
    4. 流式生成新内容
    5. 保存为版本历史
    6. 可选自动应用
    """
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    # 验证章节存在
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    if not chapter.content or chapter.content.strip() == "":
        raise HTTPException(status_code=400, detail="章节内容为空，无法重新生成")
    
    # 验证用户权限
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 获取分析结果（如果使用分析建议）
    analysis = None
    if regenerate_request.modification_source in ['analysis_suggestions', 'mixed']:
        analysis_result = await db.execute(
            select(PlotAnalysis)
            .where(PlotAnalysis.chapter_id == chapter_id)
            .order_by(PlotAnalysis.created_at.desc())
            .limit(1)
        )
        analysis = analysis_result.scalar_one_or_none()
        
        if not analysis:
            raise HTTPException(status_code=404, detail="该章节暂无分析结果")
    
    # 预先获取项目上下文数据和写作风格
    async for temp_db in get_db(request):
        try:
            # 获取项目信息
            project_result = await temp_db.execute(
                select(Project).where(Project.id == chapter.project_id)
            )
            project = project_result.scalar_one_or_none()
            
            # 获取角色信息（包含职业信息）
            characters_result = await temp_db.execute(
                select(Character).where(Character.project_id == chapter.project_id)
            )
            characters = characters_result.scalars().all()
            
            # 📝 根据大纲模式智能筛选相关角色（重新生成）
            outline_mode_result = await temp_db.execute(
                select(Project.outline_mode).where(Project.id == chapter.project_id)
            )
            outline_mode = outline_mode_result.scalar_one_or_none() or 'one-to-many'
            
            filter_character_names = None
            if outline_mode == 'one-to-one':
                # 1-1模式：从outline.structure中提取characters字段（优先使用 outline_id）
                if chapter.outline_id:
                    outline_result_temp = await temp_db.execute(
                        select(Outline.structure)
                        .where(Outline.id == chapter.outline_id)
                    )
                else:
                    outline_result_temp = await temp_db.execute(
                        select(Outline.structure)
                        .where(Outline.project_id == chapter.project_id)
                        .where(Outline.order_index == chapter.chapter_number)
                    )
                outline_structure = outline_result_temp.scalar_one_or_none()
                if outline_structure:
                    try:
                        structure = json.loads(outline_structure)
                        filter_character_names = structure.get('characters', [])
                        if filter_character_names:
                            logger.info(f"📋 重新生成 - 1-1模式：从structure提取角色列表 {filter_character_names}")
                    except json.JSONDecodeError:
                        logger.warning(f"⚠️ 重新生成 - outline.structure解析失败，使用全部角色")
            else:
                # 1-n模式：从chapter.expansion_plan中提取character_focus字段
                if chapter.expansion_plan:
                    try:
                        plan = json.loads(chapter.expansion_plan)
                        filter_character_names = plan.get('character_focus', [])
                        if filter_character_names:
                            logger.info(f"📋 重新生成 - 1-n模式：从expansion_plan提取角色焦点 {filter_character_names}")
                    except json.JSONDecodeError:
                        logger.warning(f"⚠️ 重新生成 - expansion_plan解析失败，使用全部角色")
            
            characters_info_with_careers = await build_characters_info_with_careers(
                db=temp_db,
                project_id=chapter.project_id,
                characters=characters,
                filter_character_names=filter_character_names
            )
            
            # 获取章节大纲（优先使用 chapter.outline_id 直接关联）
            if chapter.outline_id:
                outline_result = await temp_db.execute(
                    select(Outline).where(Outline.id == chapter.outline_id)
                )
            else:
                # 回退到按序号查找
                outline_result = await temp_db.execute(
                    select(Outline)
                    .where(Outline.project_id == chapter.project_id)
                    .where(Outline.order_index == chapter.chapter_number)
                )
            outline = outline_result.scalar_one_or_none()
            
            # 获取写作风格
            style_content = ""
            style_id = regenerate_request.style_id
            
            # 如果没有指定风格，尝试使用项目的默认风格
            if not style_id:
                from app.models.project_default_style import ProjectDefaultStyle
                default_style_result = await temp_db.execute(
                    select(ProjectDefaultStyle.style_id)
                    .where(ProjectDefaultStyle.project_id == chapter.project_id)
                )
                default_style_id = default_style_result.scalar_one_or_none()
                if default_style_id:
                    style_id = default_style_id
                    logger.info(f"📝 使用项目默认写作风格: {style_id}")
            
            # 获取风格内容
            if style_id:
                style_result = await temp_db.execute(
                    select(WritingStyle).where(WritingStyle.id == style_id)
                )
                style = style_result.scalar_one_or_none()
                if style:
                    # 验证风格是否可用：全局预设风格（user_id为NULL）或者当前用户的自定义风格
                    if style.user_id is None or style.user_id == user_id:
                        style_content = style.prompt_content or ""
                        style_type = "全局预设" if style.user_id is None else "用户自定义"
                        logger.info(f"✅ 使用写作风格: {style.name} ({style_type})")
                    else:
                        logger.warning(f"⚠️ 风格 {style_id} 不属于当前项目，跳过")
                else:
                    logger.warning(f"⚠️ 未找到风格 {style_id}")
            else:
                logger.info("ℹ️ 未指定写作风格，使用默认提示词")
            
            # 构建项目上下文
            project_context = {
                'project_title': project.title if project else '未知',
                'genre': project.genre if project else '未设定',
                'theme': project.theme if project else '未设定',
                'narrative_perspective': project.narrative_perspective if project else '第三人称',
                'time_period': project.world_time_period if project else '未设定',
                'location': project.world_location if project else '未设定',
                'atmosphere': project.world_atmosphere if project else '未设定',
                'characters_info': characters_info_with_careers,
                'chapter_outline': outline.content if outline else chapter.summary or '暂无大纲',
                'previous_context': ''  # 可以后续扩展添加前置章节上下文
            }
        finally:
            await temp_db.close()
        break
    
    async def event_generator():
        """流式生成事件生成器"""
        db_session = None
        db_committed = False
        
        # 初始化标准进度追踪器
        from app.utils.sse_response import WizardProgressTracker
        tracker = WizardProgressTracker("章节重新生成")
        
        try:
            yield await tracker.start()
            
            # 创建独立数据库会话
            async for db_session in get_db(request):
                yield await tracker.loading("加载章节信息...", 0.5)
                
                # 创建重新生成任务
                regen_task = RegenerationTask(
                    chapter_id=chapter_id,
                    analysis_id=analysis.id if analysis else None,
                    user_id=user_id,
                    project_id=chapter.project_id,
                    modification_instructions="",  # 稍后填充
                    original_suggestions=analysis.suggestions if analysis else None,
                    selected_suggestion_indices=regenerate_request.selected_suggestion_indices,
                    custom_instructions=regenerate_request.custom_instructions,
                    style_id=regenerate_request.style_id,
                    target_word_count=regenerate_request.target_word_count,
                    focus_areas=regenerate_request.focus_areas,
                    preserve_elements=regenerate_request.preserve_elements.model_dump() if regenerate_request.preserve_elements else None,
                    status='running',
                    original_content=chapter.content,
                    original_word_count=chapter.word_count or len(chapter.content),
                    version_note=regenerate_request.version_note,
                    started_at=datetime.now()
                )
                db_session.add(regen_task)
                await db_session.commit()
                await db_session.refresh(regen_task)
                
                task_id = regen_task.id
                logger.info(f"📝 创建重新生成任务: {task_id}")
                
                yield await tracker.preparing("准备重新生成...")
                
                yield await SSEResponse.send_event(
                    event='task_created',
                    data={'task_id': task_id}
                )
                
                # 初始化重新生成器（支持指定 AI 服务/模型）
                ai_service = user_ai_service
                if regenerate_request.provider_config_id or regenerate_request.model:
                    from app.services.ai_provider_service import create_routed_ai_service
                    ai_service = await create_routed_ai_service(
                        db_session,
                        user_id=user_id,
                        usage_type="chapter_write",
                        provider_config_id=regenerate_request.provider_config_id,
                        model=regenerate_request.model,
                        project_id=chapter.project_id,
                        chapter_id=chapter_id,
                        task_trace_id=task_id,
                        enable_mcp=False,
                    )
                regenerator = ChapterRegenerator(ai_service)
                
                # === 生成阶段 ===
                full_content = ""
                estimated_total = regenerate_request.target_word_count or len(chapter.content)
                
                yield await tracker.generating(
                    current_chars=0,
                    estimated_total=estimated_total
                )
                
                async for event in regenerator.regenerate_with_feedback(
                    chapter=chapter,
                    analysis=analysis,
                    regenerate_request=regenerate_request,
                    project_context=project_context,
                    style_content=style_content,
                    user_id=user_id,
                    db=db_session
                ):
                    # 处理不同类型的事件
                    if event['type'] == 'chunk':
                        # 内容块
                        chunk = event['content']
                        full_content += chunk
                        yield await tracker.generating_chunk(chunk)
                        
                        # 定期更新进度
                        if len(full_content) % 500 == 0:
                            yield await tracker.generating(
                                current_chars=len(full_content),
                                estimated_total=estimated_total,
                                message=f'重新生成中... 已生成 {len(full_content)} 字'
                            )
                    elif event['type'] == 'progress':
                        # 进度更新 - 映射到对应阶段
                        progress = event.get('progress', 0)
                        message = event.get('message', '')
                        if progress < 20:
                            yield await tracker.preparing(message)
                        elif progress < 85:
                            yield await tracker.generating(
                                current_chars=len(full_content),
                                estimated_total=estimated_total,
                                message=message
                            )
                        else:
                            yield await tracker.parsing(message)
                    
                    await asyncio.sleep(0)
                
                # === 保存阶段 ===
                yield await tracker.saving("保存重新生成的内容...", 0.5)
                
                # 更新任务状态
                regen_task.status = 'completed'
                regen_task.regenerated_content = full_content
                regen_task.regenerated_word_count = len(full_content)
                regen_task.completed_at = datetime.now()
                
                # 计算差异统计
                diff_stats = regenerator.calculate_content_diff(chapter.content, full_content)
                
                await db_session.commit()
                db_committed = True
                
                yield await tracker.saving("保存完成", 0.9)
                
                # === 完成阶段 ===
                yield await tracker.complete("重新生成完成！")
                
                # 发送结果数据
                yield await tracker.result({
                    'task_id': task_id,
                    'word_count': len(full_content),
                    'version_number': regen_task.version_number,
                    'auto_applied': regenerate_request.auto_apply,
                    'diff_stats': diff_stats
                })
                
                # 发送完成信号
                yield await tracker.done()
                
                logger.info(f"✅ 章节重新生成完成: {chapter_id}, 任务: {task_id}")
                
                break
        
        except Exception as e:
            logger.error(f"❌ 重新生成失败: {str(e)}", exc_info=True)
            
            # 更新任务状态为失败
            if db_session and not db_committed:
                try:
                    task_result = await db_session.execute(
                        select(RegenerationTask).where(RegenerationTask.chapter_id == chapter_id)
                        .order_by(RegenerationTask.created_at.desc()).limit(1)
                    )
                    task = task_result.scalar_one_or_none()
                    if task:
                        task.status = 'failed'
                        task.error_message = str(e)[:500]
                        task.completed_at = datetime.now()
                        await db_session.commit()
                except Exception as update_error:
                    logger.error(f"更新任务失败状态失败: {str(update_error)}")
            
            yield await tracker.error(str(e))
        
        finally:
            if db_session:
                try:
                    if not db_committed and db_session.in_transaction():
                        await db_session.rollback()
                    await db_session.close()
                except Exception as close_error:
                    logger.error(f"关闭数据库会话失败: {str(close_error)}")
    
    return create_sse_response(event_generator())


@router.get("/{chapter_id}/regeneration/tasks", summary="获取章节的重新生成任务列表")
async def get_regeneration_tasks(
    chapter_id: str,
    request: Request,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
    """获取指定章节的重新生成任务历史"""
    user_id = getattr(request.state, 'user_id', None)
    
    # 验证章节存在和权限
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 获取任务列表
    result = await db.execute(
        select(RegenerationTask)
        .where(RegenerationTask.chapter_id == chapter_id)
        .order_by(RegenerationTask.created_at.desc())
        .limit(limit)
    )
    tasks = result.scalars().all()
    
    return {
        "chapter_id": chapter_id,
        "total": len(tasks),
        "tasks": [
            {
                "task_id": task.id,
                "status": task.status,
                "version_number": task.version_number,
                "version_note": task.version_note,
                "original_word_count": task.original_word_count,
                "regenerated_word_count": task.regenerated_word_count,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None
            }
            for task in tasks
        ]
    }


@router.put("/{chapter_id}/expansion-plan", response_model=dict, summary="更新章节规划信息")
async def update_chapter_expansion_plan(
    chapter_id: str,
    expansion_plan: ExpansionPlanUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    更新章节的展开规划信息和情节概要
    
    Args:
        chapter_id: 章节ID
        expansion_plan: 规划信息更新数据(包含summary和expansion_plan字段)
    
    Returns:
        更新后的章节规划信息
    """
    # 获取章节
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 准备更新数据(排除None值)
    plan_data = expansion_plan.model_dump(exclude_unset=True, exclude_none=True)
    
    # 分离summary和expansion_plan数据
    summary_value = plan_data.pop('summary', None)
    
    # 更新summary字段(如果提供)
    if summary_value is not None:
        chapter.summary = summary_value
        logger.info(f"更新章节概要: {chapter_id}")
    
    # 更新expansion_plan字段(如果有其他字段)
    if plan_data:
        if chapter.expansion_plan:
            try:
                existing_plan = json.loads(chapter.expansion_plan)
                # 合并更新
                existing_plan.update(plan_data)
                chapter.expansion_plan = json.dumps(existing_plan, ensure_ascii=False)
            except json.JSONDecodeError:
                logger.warning(f"章节 {chapter_id} 的expansion_plan格式错误,将覆盖")
                chapter.expansion_plan = json.dumps(plan_data, ensure_ascii=False)
        else:
            chapter.expansion_plan = json.dumps(plan_data, ensure_ascii=False)
    
    await db.commit()
    await db.refresh(chapter)
    
    logger.info(f"章节规划更新成功: {chapter_id}")
    
    # 返回更新后的规划数据
    updated_plan = json.loads(chapter.expansion_plan) if chapter.expansion_plan else None
    
    return {
        "id": chapter.id,
        "summary": chapter.summary,
        "expansion_plan": updated_plan,
        "message": "规划信息更新成功"
    }


# ==================== 局部重写相关API ====================

@router.post("/{chapter_id}/ai-edit-stream", summary="AI对话式修改章节（SSE）")
async def chapter_ai_edit_stream(
    chapter_id: str,
    request: Request,
    payload: ChapterAIEditRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    指令驱动的最小修改：AI 读全文，只改指令涉及的段落，SSE 流式返回完整新正文。
    前端收到后 diff 对比确认应用。
    """
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    # 校验章节与权限
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    await verify_project_access(chapter.project_id, user_id, db)
    if not chapter.content or chapter.content.strip() == "":
        raise HTTPException(status_code=400, detail="章节内容为空，无法修改")

    # 预取上下文（项目/角色/大纲）
    project_result = await db.execute(select(Project).where(Project.id == chapter.project_id))
    project = project_result.scalar_one_or_none()
    characters = list((await db.scalars(
        select(Character).where(Character.project_id == chapter.project_id)
    )).all())
    characters_info = "\n".join(
        f"- {c.name}: {(c.background or '')[:200]}" for c in characters
    ) or "暂无角色信息"
    outline_context = ""
    if chapter.outline_id:
        o = (await db.execute(select(Outline).where(Outline.id == chapter.outline_id))).scalar_one_or_none()
        if o:
            outline_context = f"标题：{o.title}\n内容：{(o.content or '')[:500]}"
    if not outline_context:
        outline_context = "（无大纲信息）"

    project_id = chapter.project_id
    original_content = chapter.content

    async def event_generator():
        from app.services.ai_provider_service import create_routed_ai_service
        from app.services.skill_loader import build_skill_system_prompt
        from app.database import get_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as BgAsyncSession

        engine = await get_engine(user_id)
        AsyncSessionLocal = async_sessionmaker(engine, class_=BgAsyncSession, expire_on_commit=False)
        async with AsyncSessionLocal() as bg_db:
            try:
                yield await SSEResponse.send_event("progress", {"message": "正在准备修改...", "progress": 5})

                template = await PromptService.get_template("CHAPTER_AI_EDIT", user_id, bg_db)
                prompt = PromptService.format_prompt(
                    template,
                    title=project.title if project else "未命名",
                    genre=(project.genre if project else None) or "通用",
                    narrative_perspective=(project.narrative_perspective if project else None) or "第三人称",
                    characters_info=characters_info,
                    outline_context=outline_context,
                    chapter_content=original_content,
                    instruction=payload.instruction,
                )
                system_prompt = build_skill_system_prompt(payload.skill_key)
                if system_prompt:
                    logger.info(f"⚡ 已将 Skill '{payload.skill_key}' 注入系统提示词（AI对话修改）")

                service = await create_routed_ai_service(
                    bg_db,
                    user_id=user_id,
                    usage_type="chapter_write",
                    provider_config_id=payload.provider_config_id,
                    model=payload.model,
                    project_id=project_id,
                    chapter_id=chapter_id,
                    enable_mcp=False,
                )

                yield await SSEResponse.send_event("progress", {"message": "AI 正在修改中...", "progress": 15})
                full_content = ""
                async for chunk in service.generate_text_stream(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=0.7,
                ):
                    full_content += chunk
                    yield await SSEResponse.send_chunk(chunk)

                if not full_content.strip():
                    raise ValueError("AI 未返回内容")

                # 记录生成历史
                bg_db.add(GenerationHistory(
                    project_id=project_id,
                    chapter_id=chapter_id,
                    prompt=prompt,
                    generated_content=full_content[:500],
                    model=payload.model or "default",
                ))
                await bg_db.commit()

                yield await SSEResponse.send_result({"word_count": len(full_content)})
                yield await SSEResponse.send_done()
            except Exception as e:
                logger.error(f"❌ AI对话修改失败: {str(e)}")
                yield await SSEResponse.send_error(str(e))

    return create_sse_response(event_generator())


@router.post("/{chapter_id}/partial-regenerate-stream", summary="流式局部重写选中内容")
async def partial_regenerate_stream(
    chapter_id: str,
    request: Request,
    partial_request: PartialRegenerateRequest,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    对章节中选中的部分内容进行流式重写
    
    工作流程：
    1. 验证章节和选中内容的有效性
    2. 截取上下文（前后文）
    3. 根据用户要求构建提示词
    4. 流式生成重写内容
    5. 返回重写结果（不自动保存，由前端决定是否应用）
    """
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    # 验证章节存在
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    if not chapter.content or chapter.content.strip() == "":
        raise HTTPException(status_code=400, detail="章节内容为空")
    
    # 验证用户权限
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 验证位置参数
    content_length = len(chapter.content)
    if partial_request.start_position >= content_length:
        raise HTTPException(status_code=400, detail="起始位置超出内容范围")
    if partial_request.end_position > content_length:
        raise HTTPException(status_code=400, detail="结束位置超出内容范围")
    if partial_request.start_position >= partial_request.end_position:
        raise HTTPException(status_code=400, detail="起始位置必须小于结束位置")
    
    # 验证选中的文本是否匹配
    actual_selected = chapter.content[partial_request.start_position:partial_request.end_position]
    if actual_selected != partial_request.selected_text:
        # 位置可能有偏差，尝试在附近查找
        search_start = max(0, partial_request.start_position - 50)
        search_end = min(content_length, partial_request.end_position + 50)
        search_area = chapter.content[search_start:search_end]
        
        if partial_request.selected_text in search_area:
            # 找到了，更新位置
            offset = search_area.find(partial_request.selected_text)
            partial_request.start_position = search_start + offset
            partial_request.end_position = partial_request.start_position + len(partial_request.selected_text)
            logger.info(f"⚠️ 选中文本位置校正: {partial_request.start_position}-{partial_request.end_position}")
        else:
            raise HTTPException(
                status_code=400,
                detail="选中的文本与章节内容不匹配，请刷新页面后重试"
            )
    
    # 预先获取项目信息和写作风格
    project_result = await db.execute(
        select(Project).where(Project.id == chapter.project_id)
    )
    project = project_result.scalar_one_or_none()
    
    # 获取写作风格
    style_content = ""
    style_id = partial_request.style_id
    
    # 如果没有指定风格，尝试使用项目的默认风格
    if not style_id:
        from app.models.project_default_style import ProjectDefaultStyle
        default_style_result = await db.execute(
            select(ProjectDefaultStyle.style_id)
            .where(ProjectDefaultStyle.project_id == chapter.project_id)
        )
        default_style_id = default_style_result.scalar_one_or_none()
        if default_style_id:
            style_id = default_style_id
            logger.info(f"📝 局部重写 - 使用项目默认写作风格: {style_id}")
    
    # 获取风格内容
    if style_id:
        style_result = await db.execute(
            select(WritingStyle).where(WritingStyle.id == style_id)
        )
        style = style_result.scalar_one_or_none()
        if style:
            if style.user_id is None or style.user_id == user_id:
                style_content = style.prompt_content or ""
                style_type = "全局预设" if style.user_id is None else "用户自定义"
                logger.info(f"✅ 局部重写 - 使用写作风格: {style.name} ({style_type})")
            else:
                logger.warning(f"⚠️ 风格 {style_id} 不属于当前用户，跳过")
    
    async def event_generator():
        """流式生成事件生成器"""
        from app.utils.sse_response import WizardProgressTracker
        tracker = WizardProgressTracker("局部重写")
        
        try:
            yield await tracker.start()
            yield await tracker.loading("准备重写上下文...", 0.3)
            
            # 截取上下文
            context_chars = partial_request.context_chars
            start_pos = partial_request.start_position
            end_pos = partial_request.end_position
            
            # 前文：从start_pos往前截取context_chars个字符
            context_before_start = max(0, start_pos - context_chars)
            context_before = chapter.content[context_before_start:start_pos]
            
            # 后文：从end_pos往后截取context_chars个字符
            context_after_end = min(content_length, end_pos + context_chars)
            context_after = chapter.content[end_pos:context_after_end]
            
            # 原文
            original_text = partial_request.selected_text
            original_word_count = len(original_text)
            
            logger.info(f"📝 局部重写 - 原文: {original_word_count}字, 前文: {len(context_before)}字, 后文: {len(context_after)}字")
            
            yield await tracker.loading("构建提示词...", 0.5)
            
            # 构建字数要求
            length_requirement = ""
            if partial_request.length_mode == "similar":
                min_words = int(original_word_count * 0.8)
                max_words = int(original_word_count * 1.2)
                length_requirement = f"保持与原文相近的字数（约{original_word_count}字，允许{min_words}-{max_words}字浮动）"
            elif partial_request.length_mode == "expand":
                min_words = int(original_word_count * 1.2)
                max_words = int(original_word_count * 2.0)
                length_requirement = f"适当扩展内容（目标{min_words}-{max_words}字）"
            elif partial_request.length_mode == "condense":
                min_words = int(original_word_count * 0.5)
                max_words = int(original_word_count * 0.8)
                length_requirement = f"精简压缩内容（目标{min_words}-{max_words}字）"
            elif partial_request.length_mode == "custom" and partial_request.target_word_count:
                length_requirement = f"目标字数：约{partial_request.target_word_count}字（允许±20%浮动）"
            else:
                length_requirement = f"保持与原文相近的字数（约{original_word_count}字）"
            
            # 获取提示词模板
            template = await PromptService.get_template("PARTIAL_REGENERATE", user_id, db)
            if not template:
                template = PromptService.PARTIAL_REGENERATE
            
            # 构建提示词
            prompt = PromptService.format_prompt(
                template,
                context_before=context_before if context_before else "（这是章节开头）",
                original_word_count=original_word_count,
                selected_text=original_text,
                context_after=context_after if context_after else "（这是章节结尾）",
                user_instructions=partial_request.user_instructions,
                length_requirement=length_requirement,
                style_content=style_content if style_content else "保持与原文一致的叙事风格"
            )
            
            yield await tracker.preparing("开始生成...")
            
            # 计算 max_tokens
            if partial_request.length_mode == "expand":
                target_words = int(original_word_count * 2.0)
            elif partial_request.length_mode == "custom" and partial_request.target_word_count:
                target_words = partial_request.target_word_count
            else:
                target_words = int(original_word_count * 1.5)
            
            calculated_max_tokens = max(500, min(int(target_words * 3), 8000))
            
            # 流式生成
            full_content = ""
            chunk_count = 0
            
            yield await tracker.generating(
                current_chars=0,
                estimated_total=target_words
            )
            
            async for chunk in user_ai_service.generate_text_stream(
                prompt=prompt,
                max_tokens=calculated_max_tokens
            ):
                full_content += chunk
                chunk_count += 1
                
                # 发送内容块
                yield await tracker.generating_chunk(chunk)
                
                # 每5个chunk发送一次进度更新
                if chunk_count % 5 == 0:
                    yield await tracker.generating(
                        current_chars=len(full_content),
                        estimated_total=target_words,
                        message=f'正在重写中... 已生成 {len(full_content)} 字'
                    )
                
                await asyncio.sleep(0)
            
            # 清理输出（移除可能的前后缀）
            full_content = full_content.strip()
            
            # 移除常见的AI输出前缀
            prefixes_to_remove = [
                "重写后：", "重写后:", "改写后：", "改写后:",
                "以下是重写后的内容：", "以下是重写后的内容:",
                "重写内容：", "重写内容:"
            ]
            for prefix in prefixes_to_remove:
                if full_content.startswith(prefix):
                    full_content = full_content[len(prefix):].strip()
                    break
            
            # 移除首尾可能的引号
            if (full_content.startswith('"') and full_content.endswith('"')) or \
               (full_content.startswith("'") and full_content.endswith("'")):
                full_content = full_content[1:-1]
            if (full_content.startswith('「') and full_content.endswith('」')) or \
               (full_content.startswith('『') and full_content.endswith('』')):
                full_content = full_content[1:-1]
            
            new_word_count = len(full_content)
            
            logger.info(f"✅ 局部重写完成: 原文{original_word_count}字 -> 新文{new_word_count}字")
            
            # 完成
            yield await tracker.complete("重写完成！")
            
            # 发送结果数据
            yield await tracker.result({
                'new_text': full_content,
                'word_count': new_word_count,
                'original_word_count': original_word_count,
                'start_position': partial_request.start_position,
                'end_position': partial_request.end_position
            })
            
            yield await tracker.done()
            
        except Exception as e:
            logger.error(f"❌ 局部重写失败: {str(e)}", exc_info=True)
            yield await tracker.error(str(e))
    
    return create_sse_response(event_generator())


@router.post("/{chapter_id}/apply-partial-regenerate", summary="应用局部重写结果")
async def apply_partial_regenerate(
    chapter_id: str,
    request: Request,
    apply_request: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    将局部重写的结果应用到章节内容中
    
    请求体：
    - new_text: 重写后的新内容
    - start_position: 原文起始位置
    - end_position: 原文结束位置
    """
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    # 验证章节存在
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 验证用户权限
    await verify_project_access(chapter.project_id, user_id, db)
    
    # 获取参数
    new_text = apply_request.get('new_text', '')
    start_position = apply_request.get('start_position', 0)
    end_position = apply_request.get('end_position', 0)
    
    if not new_text:
        raise HTTPException(status_code=400, detail="新内容不能为空")
    
    # 验证位置有效性
    content_length = len(chapter.content)
    if start_position < 0 or end_position > content_length or start_position >= end_position:
        raise HTTPException(status_code=400, detail="位置参数无效")
    
    # 构建新内容
    old_word_count = chapter.word_count or 0
    new_content = chapter.content[:start_position] + new_text + chapter.content[end_position:]
    try:
        formal_result = await persist_formal_chapter_content(
            db=db,
            chapter_id=chapter.id,
            user_id=user_id,
            content=new_content,
            prompt=f"局部重写: 第{chapter.chapter_number}章 {chapter.title}",
            model="partial-regenerate",
            foreshadow_service=foreshadow_service,
            memory_service=memory_service,
            expected_content_hash=chapter_content_hash(chapter.content),
        )
    except FormalChapterConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    chapter = formal_result.chapter
    new_word_count = chapter.word_count

    _schedule_analysis_background(analyze_chapter_background(
        chapter_id=chapter.id,
        user_id=user_id,
        project_id=chapter.project_id,
        task_id=formal_result.analysis_task.id,
    ))
    
    logger.info(f"✅ 局部重写已应用: 章节{chapter_id}, {old_word_count}字 -> {new_word_count}字")
    
    return {
        "success": True,
        "chapter_id": chapter_id,
        "word_count": new_word_count,
        "old_word_count": old_word_count,
        "analysis_task_id": formal_result.analysis_task.id,
        "message": "局部重写已应用"
    }
