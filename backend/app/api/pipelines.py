"""自动化小说生产流水线 API（编排器入口）。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access
from app.api.settings import require_login
from app.database import get_db
from app.models.novel_pipeline import NovelPipeline, PipelineCheckpoint
from app.models.project import Project
from app.schemas.pipeline import (
    PipelineListResponse,
    PipelineResponse,
    PipelineStartRequest,
)
from app.services.pipeline_service import (
    PipelineNotFoundError,
    PipelineStateError,
    get_pipeline,
    pause_pipeline,
    resume_pipeline,
    start_pipeline,
    stop_pipeline,
)

router = APIRouter(prefix="/pipelines", tags=["小说流水线"])


async def _pipeline_response(db: AsyncSession, pipeline: NovelPipeline, user_id: str) -> PipelineResponse:
    # 先重查一次：避免 commit 后属性过期导致惰性加载报错
    fresh = await get_pipeline(db, pipeline.id, user_id)
    checkpoint = None
    if fresh.current_checkpoint_id:
        checkpoint = await db.get(PipelineCheckpoint, fresh.current_checkpoint_id)
    resp = PipelineResponse.model_validate(fresh)
    if checkpoint is not None:
        from app.schemas.pipeline import PipelineCheckpointResponse

        resp.current_checkpoint = PipelineCheckpointResponse.model_validate(checkpoint)
    return resp


@router.post("/start", response_model=PipelineResponse, summary="启动流水线")
async def start(
    data: PipelineStartRequest,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    await verify_project_access(data.project_id, user.user_id, db)
    try:
        pipeline = await start_pipeline(db, user_id=user.user_id, project_id=data.project_id, config=data.config)
        return await _pipeline_response(db, pipeline, user.user_id)
    except PipelineStateError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"启动失败：{exc}")


@router.get("/{pipeline_id}", response_model=PipelineResponse, summary="查询流水线状态")
async def get(
    pipeline_id: str,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    try:
        pipeline = await get_pipeline(db, pipeline_id, user.user_id)
        return await _pipeline_response(db, pipeline, user.user_id)
    except PipelineNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("", response_model=PipelineListResponse, summary="流水线列表")
async def list_pipelines(
    project_id: Optional[str] = Query(default=None),
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    filters = [
        NovelPipeline.project_id.in_(select(Project.id).where(Project.user_id == user.user_id))
    ]
    if project_id:
        await verify_project_access(project_id, user.user_id, db)
        filters.append(NovelPipeline.project_id == project_id)
    total = await db.scalar(select(func.count(NovelPipeline.id)).where(*filters)) or 0
    rows = list((await db.scalars(
        select(NovelPipeline).where(*filters).order_by(NovelPipeline.created_at.desc())
    )).all())
    return PipelineListResponse(
        items=[await _pipeline_response(db, row, user.user_id) for row in rows],
        total=total,
    )


@router.post("/{pipeline_id}/pause", response_model=PipelineResponse, summary="暂停流水线")
async def pause(pipeline_id: str, user=Depends(require_login), db: AsyncSession = Depends(get_db)):
    try:
        pipeline = await pause_pipeline(db, user_id=user.user_id, pipeline_id=pipeline_id)
        return await _pipeline_response(db, pipeline, user.user_id)
    except PipelineNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PipelineStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{pipeline_id}/resume", response_model=PipelineResponse, summary="恢复流水线")
async def resume(pipeline_id: str, user=Depends(require_login), db: AsyncSession = Depends(get_db)):
    try:
        pipeline = await resume_pipeline(db, user_id=user.user_id, pipeline_id=pipeline_id)
        return await _pipeline_response(db, pipeline, user.user_id)
    except PipelineNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PipelineStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{pipeline_id}/stop", response_model=PipelineResponse, summary="停止流水线")
async def stop(pipeline_id: str, user=Depends(require_login), db: AsyncSession = Depends(get_db)):
    try:
        pipeline = await stop_pipeline(db, user_id=user.user_id, pipeline_id=pipeline_id)
        return await _pipeline_response(db, pipeline, user.user_id)
    except PipelineNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
