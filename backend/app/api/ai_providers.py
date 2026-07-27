"""多 LLM 服务配置、任务默认路由和调用记录。"""
from typing import Optional
import uuid
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.settings import require_login
from app.database import get_db
from app.models.ai_call_log import AICallLog
from app.models.ai_provider_config import AIProviderConfig, AIUsageRoute
from app.schemas.ai_provider import (
    AICallLogListResponse,
    AICallLogResponse,
    AIProviderConfigCreate,
    AIProviderConfigResponse,
    AIProviderConfigUpdate,
    AISelectionResponse,
    AIUsageRouteResponse,
    AIUsageRouteUpdate,
    AIUsageSummaryResponse,
)
from app.security import validate_public_http_url
from app.services.ai_provider_service import resolve_ai_selection
from app.services.ai_provider_service import create_routed_ai_service


router = APIRouter(prefix="/ai-providers", tags=["AI 服务管理"])


def _provider_response(row: AIProviderConfig) -> AIProviderConfigResponse:
    key = row.api_key or ""
    hint = f"****{key[-4:]}" if len(key) >= 4 else ("已配置" if key else None)
    return AIProviderConfigResponse(
        id=row.id,
        name=row.name,
        protocol=row.protocol,
        wire_api=row.wire_api,
        base_url=row.base_url,
        api_key_configured=bool(key),
        api_key_hint=hint,
        default_model=row.default_model,
        models=row.model_catalog or [],
        enabled=row.enabled,
        is_default=row.is_default,
        sort_order=row.sort_order,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _clear_other_defaults(db: AsyncSession, user_id: str, keep_id: str) -> None:
    rows = (await db.scalars(
        select(AIProviderConfig).where(
            AIProviderConfig.user_id == user_id,
            AIProviderConfig.id != keep_id,
            AIProviderConfig.is_default.is_(True),
        )
    )).all()
    for row in rows:
        row.is_default = False


@router.get("", response_model=list[AIProviderConfigResponse])
async def list_provider_configs(user=Depends(require_login), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(
        select(AIProviderConfig)
        .where(AIProviderConfig.user_id == user.user_id)
        .order_by(AIProviderConfig.sort_order.asc(), AIProviderConfig.created_at.asc())
    )).all()
    return [_provider_response(row) for row in rows]


@router.post("", response_model=AIProviderConfigResponse)
async def create_provider_config(
    data: AIProviderConfigCreate,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    base_url = validate_public_http_url(data.base_url).rstrip("/")
    values = data.model_dump(exclude={"models"})
    if data.protocol != "openai":
        values["wire_api"] = "chat_completions"
    row = AIProviderConfig(
        id=str(uuid.uuid4()),
        user_id=user.user_id,
        **{**values, "model_catalog": data.models, "base_url": base_url},
    )
    if data.is_default:
        await _clear_other_defaults(db, user.user_id, row.id)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="AI 服务名称已存在")
    await db.refresh(row)
    return _provider_response(row)


@router.put("/{config_id}", response_model=AIProviderConfigResponse)
async def update_provider_config(
    config_id: str,
    data: AIProviderConfigUpdate,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(AIProviderConfig).where(
        AIProviderConfig.id == config_id,
        AIProviderConfig.user_id == user.user_id,
    ))
    if not row:
        raise HTTPException(status_code=404, detail="AI 服务不存在")

    values = data.model_dump(exclude_unset=True)
    if "models" in values:
        values["model_catalog"] = values.pop("models")
    if "base_url" in values:
        values["base_url"] = validate_public_http_url(values["base_url"]).rstrip("/")
    # 前端编辑时不传 api_key 表示保留旧值；传空字符串表示清除。
    if values.get("api_key") is None:
        values.pop("api_key", None)
    final_protocol = values.get("protocol", row.protocol)
    if final_protocol != "openai":
        values["wire_api"] = "chat_completions"
    for key, value in values.items():
        setattr(row, key, value)
    if values.get("is_default"):
        await _clear_other_defaults(db, user.user_id, row.id)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="AI 服务名称已存在")
    await db.refresh(row)
    return _provider_response(row)


@router.delete("/{config_id}")
async def delete_provider_config(
    config_id: str,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(AIProviderConfig).where(
        AIProviderConfig.id == config_id,
        AIProviderConfig.user_id == user.user_id,
    ))
    if not row:
        raise HTTPException(status_code=404, detail="AI 服务不存在")
    await db.delete(row)
    await db.commit()
    return {"message": "AI 服务已删除"}


async def _get_owned_provider(config_id: str, user_id: str, db: AsyncSession) -> AIProviderConfig:
    row = await db.scalar(select(AIProviderConfig).where(
        AIProviderConfig.id == config_id,
        AIProviderConfig.user_id == user_id,
    ))
    if not row:
        raise HTTPException(status_code=404, detail="AI 服务不存在")
    return row


@router.post("/{config_id}/test")
async def test_provider_config(
    config_id: str,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """发起一次极短请求，验证地址、密钥和模型是否真的可用。"""
    try:
        service = await create_routed_ai_service(
            db,
            user_id=user.user_id,
            usage_type="connection_test",
            provider_config_id=config_id,
            enable_mcp=False,
        )
        result = await service.generate_text(
            prompt="只回复 OK",
            temperature=0,
            max_tokens=8,
            auto_mcp=False,
        )
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        return {"success": True, "message": f"连接成功，模型返回：{content[:80]}"}
    except httpx.TimeoutException:
        raise HTTPException(status_code=400, detail="供应商响应超时，请稍后重试")
    except httpx.HTTPStatusError as exc:
        response = exc.response
        upstream_message = None
        if response is not None:
            try:
                payload = response.json()
                error = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(error, dict):
                    upstream_message = error.get("message")
                elif isinstance(payload, dict):
                    upstream_message = payload.get("message") or payload.get("detail")
            except ValueError:
                upstream_message = None
        status = response.status_code if response is not None else "未知"
        detail = f"供应商返回 HTTP {status}"
        if upstream_message:
            detail += f"：{upstream_message}"
        raise HTTPException(status_code=400, detail=detail)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"连接失败：{str(exc)}")


@router.post("/{config_id}/sync-models")
async def sync_provider_models(
    config_id: str,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """从供应商的模型列表接口同步模型；不支持时仍可在页面手工填写。"""
    row = await _get_owned_provider(config_id, user.user_id, db)
    if not row.api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")
    base_url = validate_public_http_url(row.base_url).rstrip("/")
    headers = {"Accept": "application/json"}
    params = None
    if row.protocol == "anthropic":
        url = f"{base_url}/v1/models" if not base_url.endswith("/v1") else f"{base_url}/models"
        headers.update({"x-api-key": row.api_key, "anthropic-version": "2023-06-01"})
    elif row.protocol == "gemini":
        url = f"{base_url}/models"
        params = {"key": row.api_key}
    else:
        url = f"{base_url}/models"
        headers["Authorization"] = f"Bearer {row.api_key}"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()
        entries = payload.get("data") or payload.get("models") or []
        models = []
        for item in entries:
            model_id = item.get("id") or item.get("name") if isinstance(item, dict) else None
            if model_id:
                model_id = str(model_id).removeprefix("models/")
                if model_id not in models:
                    models.append(model_id)
        if not models:
            raise ValueError("供应商返回了空模型列表")
        row.model_catalog = sorted(models)
        if not row.default_model:
            row.default_model = row.model_catalog[0]
        await db.commit()
        return {"models": row.model_catalog, "count": len(row.model_catalog)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"同步失败：{str(exc)}")


@router.get("/routes", response_model=list[AIUsageRouteResponse])
async def list_usage_routes(user=Depends(require_login), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(AIUsageRoute, AIProviderConfig.name)
        .outerjoin(AIProviderConfig, AIUsageRoute.provider_config_id == AIProviderConfig.id)
        .where(AIUsageRoute.user_id == user.user_id)
        .order_by(AIUsageRoute.usage_type.asc())
    )).all()
    return [AIUsageRouteResponse(
        usage_type=route.usage_type,
        provider_config_id=route.provider_config_id,
        provider_name=provider_name,
        model=route.model,
    ) for route, provider_name in rows]


@router.put("/routes/{usage_type}", response_model=AIUsageRouteResponse)
async def save_usage_route(
    usage_type: str,
    data: AIUsageRouteUpdate,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    usage_type = usage_type.strip().lower()
    if not usage_type or len(usage_type) > 50:
        raise HTTPException(status_code=422, detail="任务类型不正确")
    provider = None
    if data.provider_config_id:
        provider = await db.scalar(select(AIProviderConfig).where(
            AIProviderConfig.id == data.provider_config_id,
            AIProviderConfig.user_id == user.user_id,
        ))
        if not provider:
            raise HTTPException(status_code=404, detail="AI 服务不存在")

    row = await db.scalar(select(AIUsageRoute).where(
        AIUsageRoute.user_id == user.user_id,
        AIUsageRoute.usage_type == usage_type,
    ))
    if row is None:
        row = AIUsageRoute(user_id=user.user_id, usage_type=usage_type)
        db.add(row)
    row.provider_config_id = data.provider_config_id
    row.model = data.model
    await db.commit()
    return AIUsageRouteResponse(
        usage_type=usage_type,
        provider_config_id=row.provider_config_id,
        provider_name=provider.name if provider else None,
        model=row.model,
    )


@router.get("/selection/{usage_type}", response_model=AISelectionResponse)
async def get_resolved_selection(
    usage_type: str,
    provider_config_id: Optional[str] = None,
    model: Optional[str] = None,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    try:
        selected = await resolve_ai_selection(
            db,
            user_id=user.user_id,
            usage_type=usage_type,
            provider_config_id=provider_config_id,
            model=model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AISelectionResponse(
        source=selected.source,
        usage_type=selected.usage_type,
        provider_config_id=selected.provider_config_id,
        provider_name=selected.provider_name,
        protocol=selected.protocol,
        wire_api=selected.wire_api,
        model=selected.model,
    )


@router.get("/logs", response_model=AICallLogListResponse)
async def list_call_logs(
    project_id: Optional[str] = None,
    usage_type: Optional[str] = None,
    provider_config_id: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    filters = [AICallLog.user_id == user.user_id]
    if project_id:
        filters.append(AICallLog.project_id == project_id)
    if usage_type:
        filters.append(AICallLog.usage_type == usage_type)
    if provider_config_id:
        filters.append(AICallLog.provider_config_id == provider_config_id)
    if model:
        filters.append(AICallLog.actual_model == model)
    if status:
        filters.append(AICallLog.status == status)
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(or_(AICallLog.provider_name.ilike(pattern), AICallLog.actual_model.ilike(pattern)))

    total = await db.scalar(select(func.count(AICallLog.id)).where(*filters)) or 0
    rows = (await db.scalars(
        select(AICallLog)
        .where(*filters)
        .order_by(AICallLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )).all()
    return AICallLogListResponse(
        items=[AICallLogResponse.model_validate(row) for row in rows],
        total=total,
    )


@router.get("/logs/summary", response_model=AIUsageSummaryResponse)
async def get_call_log_summary(
    project_id: Optional[str] = None,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    filters = [AICallLog.user_id == user.user_id]
    if project_id:
        filters.append(AICallLog.project_id == project_id)
    row = (await db.execute(select(
        func.count(AICallLog.id),
        func.count(AICallLog.id).filter(AICallLog.status == "success"),
        func.count(AICallLog.id).filter(AICallLog.status == "failed"),
        func.coalesce(func.sum(AICallLog.total_tokens), 0),
        func.avg(AICallLog.duration_ms),
    ).where(*filters))).one()
    return AIUsageSummaryResponse(
        total_calls=row[0] or 0,
        success_calls=row[1] or 0,
        failed_calls=row[2] or 0,
        total_tokens=row[3] or 0,
        average_duration_ms=int(row[4]) if row[4] is not None else None,
    )
