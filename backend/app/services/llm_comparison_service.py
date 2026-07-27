"""多 LLM 候选批次的共享生命周期服务。"""
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.ai_provider_config import AIProviderConfig
from app.models.llm_comparison import LLMComparisonBatch, LLMComparisonCandidate
from app.schemas.llm_comparison import LLMComparisonBatchCreate


class ComparisonNotFoundError(ValueError):
    pass


class ComparisonStateError(ValueError):
    pass


@dataclass
class CandidateGenerationResult:
    output_text: Optional[str] = None
    output_data: Optional[object] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
    ai_call_log_id: Optional[str] = None


async def get_owned_batch(
    db: AsyncSession,
    *,
    batch_id: str,
    user_id: str,
    lock: bool = False,
) -> LLMComparisonBatch:
    statement = select(LLMComparisonBatch).where(
        LLMComparisonBatch.id == batch_id,
        LLMComparisonBatch.user_id == user_id,
    )
    if lock:
        statement = statement.with_for_update()
    batch = await db.scalar(statement)
    if batch is None:
        raise ComparisonNotFoundError("比较批次不存在或无权访问")
    return batch


async def list_candidates(db: AsyncSession, batch_id: str) -> list[LLMComparisonCandidate]:
    return list((await db.scalars(
        select(LLMComparisonCandidate)
        .where(LLMComparisonCandidate.batch_id == batch_id)
        .order_by(LLMComparisonCandidate.created_at.asc())
    )).all())


async def create_batch(
    db: AsyncSession,
    *,
    user_id: str,
    data: LLMComparisonBatchCreate,
) -> tuple[LLMComparisonBatch, list[LLMComparisonCandidate]]:
    """校验所有选择并一次性保存冻结快照，不保存 API Key。"""
    config_ids = {item.provider_config_id for item in data.selections}
    providers = list((await db.scalars(
        select(AIProviderConfig).where(
            AIProviderConfig.user_id == user_id,
            AIProviderConfig.id.in_(config_ids),
            AIProviderConfig.enabled.is_(True),
        )
    )).all())
    provider_map = {item.id: item for item in providers}
    if len(provider_map) != len(config_ids):
        raise ComparisonStateError("部分 AI 服务不存在、已停用或不属于当前用户")

    batch = LLMComparisonBatch(
        id=str(uuid.uuid4()),
        user_id=user_id,
        project_id=data.project_id,
        target_type=data.target_type,
        target_id=data.target_id,
        usage_type=data.usage_type.strip().lower(),
        status="draft",
        input_snapshot=data.input_snapshot,
        prompt_snapshot=data.prompt_snapshot,
        parameters_snapshot=data.parameters_snapshot,
    )
    candidates = []
    for selection in data.selections:
        provider = provider_map[selection.provider_config_id]
        candidates.append(LLMComparisonCandidate(
            id=str(uuid.uuid4()),
            batch_id=batch.id,
            provider_config_id=provider.id,
            provider_name=provider.name,
            protocol=provider.protocol,
            model=selection.model,
            status="pending",
        ))
    db.add(batch)
    db.add_all(candidates)
    await db.commit()
    await db.refresh(batch)
    return batch, candidates


async def retry_candidate(
    db: AsyncSession,
    *,
    batch_id: str,
    candidate_id: str,
    user_id: str,
) -> LLMComparisonCandidate:
    batch = await get_owned_batch(db, batch_id=batch_id, user_id=user_id, lock=True)
    candidate = await db.scalar(
        select(LLMComparisonCandidate).where(
            LLMComparisonCandidate.id == candidate_id,
            LLMComparisonCandidate.batch_id == batch.id,
        ).with_for_update()
    )
    if candidate is None:
        raise ComparisonNotFoundError("候选结果不存在")
    if candidate.status != "failed":
        raise ComparisonStateError("只有失败的候选结果可以重试")
    if batch.adopted_candidate_id:
        raise ComparisonStateError("该批次已有正式采用结果，不能重试")

    candidate.status = "pending"
    candidate.error_type = None
    candidate.error_message = None
    candidate.started_at = None
    candidate.completed_at = None
    batch.status = "queued"
    batch.completed_at = None
    await db.commit()
    await db.refresh(candidate)
    return candidate


async def delete_batch(db: AsyncSession, *, batch_id: str, user_id: str) -> None:
    batch = await get_owned_batch(db, batch_id=batch_id, user_id=user_id, lock=True)
    if batch.status in {"queued", "running"}:
        raise ComparisonStateError("比较任务仍在运行，暂时不能删除")
    await db.delete(batch)
    await db.commit()


AdoptionCallback = Callable[[AsyncSession, LLMComparisonBatch, LLMComparisonCandidate], Awaitable[None]]


async def adopt_candidate(
    db: AsyncSession,
    *,
    batch_id: str,
    candidate_id: str,
    user_id: str,
    apply_target: AdoptionCallback,
) -> tuple[LLMComparisonBatch, LLMComparisonCandidate]:
    """锁定批次并采用候选；重复采用同一项会安全返回。"""
    batch = await get_owned_batch(db, batch_id=batch_id, user_id=user_id, lock=True)
    candidate = await db.scalar(
        select(LLMComparisonCandidate).where(
            LLMComparisonCandidate.id == candidate_id,
            LLMComparisonCandidate.batch_id == batch.id,
        ).with_for_update()
    )
    if candidate is None:
        raise ComparisonNotFoundError("候选结果不存在")
    if batch.adopted_candidate_id == candidate.id:
        return batch, candidate
    if batch.adopted_candidate_id:
        raise ComparisonStateError("该批次已经采用了其他结果")
    if candidate.status != "success":
        raise ComparisonStateError("只能采用生成成功的候选结果")

    try:
        await apply_target(db, batch, candidate)
        now = datetime.now()
        batch.adopted_candidate_id = candidate.id
        batch.status = "adopted"
        candidate.adopted_at = now
        await db.commit()
        return batch, candidate
    except Exception:
        await db.rollback()
        raise


async def refresh_batch_status(db: AsyncSession, batch: LLMComparisonBatch) -> None:
    statuses = list((await db.scalars(
        select(LLMComparisonCandidate.status).where(LLMComparisonCandidate.batch_id == batch.id)
    )).all())
    if not statuses:
        batch.status = "failed"
    elif any(status == "running" for status in statuses):
        batch.status = "running"
    elif any(status == "pending" for status in statuses):
        batch.status = "queued"
    elif all(status == "success" for status in statuses):
        batch.status = "completed"
        batch.completed_at = datetime.now()
    elif any(status == "success" for status in statuses):
        batch.status = "partial_failed"
        batch.completed_at = datetime.now()
    else:
        batch.status = "failed"
        batch.completed_at = datetime.now()


CandidateGenerator = Callable[
    [AsyncSession, LLMComparisonBatch, LLMComparisonCandidate],
    Awaitable[CandidateGenerationResult],
]


async def run_batch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    batch_id: str,
    user_id: str,
    generate: CandidateGenerator,
    concurrency: int = 2,
) -> None:
    """用独立数据库会话执行候选；一个失败不会丢掉其他成功结果。"""
    concurrency = max(1, min(concurrency, 2))
    async with session_factory() as db:
        batch = await get_owned_batch(db, batch_id=batch_id, user_id=user_id, lock=True)
        if batch.adopted_candidate_id:
            raise ComparisonStateError("该批次已有正式采用结果，不能再次生成")
        candidate_ids = list((await db.scalars(
            select(LLMComparisonCandidate.id).where(
                LLMComparisonCandidate.batch_id == batch.id,
                LLMComparisonCandidate.status == "pending",
            )
        )).all())
        if not candidate_ids:
            raise ComparisonStateError("没有等待生成的候选结果")
        batch.status = "queued"
        await db.commit()

    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(candidate_id: str) -> None:
        async with semaphore, session_factory() as db:
            candidate = await db.scalar(
                select(LLMComparisonCandidate)
                .where(LLMComparisonCandidate.id == candidate_id)
                .with_for_update()
            )
            batch = await db.scalar(select(LLMComparisonBatch).where(
                LLMComparisonBatch.id == batch_id,
                LLMComparisonBatch.user_id == user_id,
            ))
            if candidate is None or batch is None or candidate.batch_id != batch.id:
                await db.rollback()
                return
            candidate.status = "running"
            candidate.attempt_count += 1
            candidate.started_at = datetime.now()
            candidate.error_type = None
            candidate.error_message = None
            batch.status = "running"
            await db.commit()
            try:
                result = await generate(db, batch, candidate)
                candidate.output_text = result.output_text
                candidate.output_data = result.output_data
                candidate.prompt_tokens = result.prompt_tokens
                candidate.completion_tokens = result.completion_tokens
                candidate.total_tokens = result.total_tokens
                candidate.duration_ms = result.duration_ms
                candidate.ai_call_log_id = result.ai_call_log_id
                candidate.status = "success"
            except Exception as exc:
                await db.rollback()
                candidate = await db.scalar(select(LLMComparisonCandidate).where(
                    LLMComparisonCandidate.id == candidate_id
                ))
                if candidate is None:
                    return
                candidate.status = "failed"
                candidate.error_type = type(exc).__name__
                candidate.error_message = str(exc)[:2000]
            candidate.completed_at = datetime.now()
            await db.commit()

    await asyncio.gather(*(run_one(candidate_id) for candidate_id in candidate_ids))
    async with session_factory() as db:
        batch = await get_owned_batch(db, batch_id=batch_id, user_id=user_id, lock=True)
        await refresh_batch_status(db, batch)
        await db.commit()


async def generate_text_candidate(
    db: AsyncSession,
    batch: LLMComparisonBatch,
    candidate: LLMComparisonCandidate,
) -> CandidateGenerationResult:
    """默认纯文本生成器；目标子任务可换成自己的 JSON 解析器。"""
    from app.services.ai_provider_service import create_routed_ai_service

    service = await create_routed_ai_service(
        db,
        user_id=batch.user_id,
        usage_type=batch.usage_type,
        provider_config_id=candidate.provider_config_id,
        model=candidate.model,
        project_id=batch.project_id,
        chapter_id=batch.target_id if batch.target_type == "chapter" else None,
        task_trace_id=batch.id,
    )
    started = perf_counter()
    result = await service.generate_text(
        prompt=batch.prompt_snapshot,
        **(batch.parameters_snapshot or {}),
    )
    duration_ms = int((perf_counter() - started) * 1000)
    if isinstance(result, dict):
        usage = result.get("usage") or {}
        return CandidateGenerationResult(
            output_text=str(result.get("content") or ""),
            output_data=result,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            duration_ms=duration_ms,
        )
    return CandidateGenerationResult(output_text=str(result), duration_ms=duration_ms)


async def list_owned_batches(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[LLMComparisonBatch], int]:
    filters = [LLMComparisonBatch.user_id == user_id]
    if project_id:
        filters.append(LLMComparisonBatch.project_id == project_id)
    if target_type:
        filters.append(LLMComparisonBatch.target_type == target_type)
    if target_id:
        filters.append(LLMComparisonBatch.target_id == target_id)
    total = await db.scalar(select(func.count(LLMComparisonBatch.id)).where(*filters)) or 0
    rows = list((await db.scalars(
        select(LLMComparisonBatch)
        .where(*filters)
        .order_by(LLMComparisonBatch.created_at.desc())
        .offset(offset)
        .limit(limit)
    )).all())
    return rows, total
