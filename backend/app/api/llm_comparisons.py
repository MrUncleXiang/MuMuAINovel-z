"""多 LLM 候选比较的共享查询与生命周期 API。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access
from app.api.settings import require_login
from app.database import get_db
from app.models.llm_comparison import LLMComparisonBatch
from app.schemas.llm_comparison import (
    LLMComparisonBatchCreate,
    LLMComparisonBatchListResponse,
    LLMComparisonBatchResponse,
    LLMComparisonCandidateResponse,
)
from app.services.llm_comparison_service import (
    ComparisonNotFoundError,
    ComparisonStateError,
    create_batch,
    delete_batch,
    get_owned_batch,
    list_candidates,
    list_owned_batches,
    retry_candidate,
)


router = APIRouter(prefix="/llm-comparisons", tags=["多 LLM 候选比较"])


async def _batch_response(db: AsyncSession, batch: LLMComparisonBatch) -> LLMComparisonBatchResponse:
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


@router.post("", response_model=LLMComparisonBatchResponse, status_code=status.HTTP_201_CREATED)
async def create_comparison_batch(
    data: LLMComparisonBatchCreate,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    await verify_project_access(data.project_id, user.user_id, db)
    try:
        batch, _ = await create_batch(db, user_id=user.user_id, data=data)
        return await _batch_response(db, batch)
    except ComparisonStateError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=LLMComparisonBatchListResponse)
async def get_comparison_batches(
    project_id: Optional[str] = None,
    target_type: Optional[str] = Query(default=None, pattern="^(chapter|outline|analysis)$"),
    target_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    if project_id:
        await verify_project_access(project_id, user.user_id, db)
    rows, total = await list_owned_batches(
        db,
        user_id=user.user_id,
        project_id=project_id,
        target_type=target_type,
        target_id=target_id,
        limit=limit,
        offset=offset,
    )
    return LLMComparisonBatchListResponse(
        items=[await _batch_response(db, row) for row in rows],
        total=total,
    )


@router.get("/{batch_id}", response_model=LLMComparisonBatchResponse)
async def get_comparison_batch(
    batch_id: str,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    try:
        batch = await get_owned_batch(db, batch_id=batch_id, user_id=user.user_id)
        return await _batch_response(db, batch)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{batch_id}/candidates/{candidate_id}/retry", response_model=LLMComparisonCandidateResponse)
async def retry_comparison_candidate(
    batch_id: str,
    candidate_id: str,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    try:
        candidate = await retry_candidate(
            db,
            batch_id=batch_id,
            candidate_id=candidate_id,
            user_id=user.user_id,
        )
        return LLMComparisonCandidateResponse.model_validate(candidate)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ComparisonStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_comparison_batch(
    batch_id: str,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_batch(db, batch_id=batch_id, user_id=user.user_id)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ComparisonStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
