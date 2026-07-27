"""LLM 服务配置选择逻辑。

优先级：本次手选 > 任务默认 > 用户默认服务 > 旧版 Settings 配置。
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_provider_config import AIProviderConfig, AIUsageRoute
from app.models.settings import Settings
from app.config import settings as app_settings
from app.models.mcp_plugin import MCPPlugin
from app.services.ai_service import AIService, create_user_ai_service_with_mcp


@dataclass
class ResolvedAISelection:
    source: str
    usage_type: str
    provider_config_id: Optional[str]
    provider_name: str
    protocol: str
    wire_api: str
    api_key: str
    base_url: str
    model: str


def protocol_to_runtime_provider(protocol: str) -> str:
    return protocol if protocol in {"anthropic", "gemini"} else "openai"


async def resolve_ai_selection(
    db: AsyncSession,
    *,
    user_id: str,
    usage_type: str = "default",
    provider_config_id: Optional[str] = None,
    model: Optional[str] = None,
) -> ResolvedAISelection:
    selected = None
    source = "legacy_default"
    route_model = None

    if provider_config_id:
        selected = await db.scalar(
            select(AIProviderConfig).where(
                AIProviderConfig.id == provider_config_id,
                AIProviderConfig.user_id == user_id,
                AIProviderConfig.enabled.is_(True),
            )
        )
        if selected is None:
            raise ValueError("选择的 AI 服务不存在或已停用")
        source = "request"
    elif usage_type and usage_type != "default":
        route = await db.scalar(
            select(AIUsageRoute).where(
                AIUsageRoute.user_id == user_id,
                AIUsageRoute.usage_type == usage_type,
            )
        )
        if route and route.provider_config_id:
            selected = await db.scalar(
                select(AIProviderConfig).where(
                    AIProviderConfig.id == route.provider_config_id,
                    AIProviderConfig.user_id == user_id,
                    AIProviderConfig.enabled.is_(True),
                )
            )
            if selected:
                source = "usage_route"
                route_model = route.model

    if selected is None:
        selected = await db.scalar(
            select(AIProviderConfig)
            .where(
                AIProviderConfig.user_id == user_id,
                AIProviderConfig.enabled.is_(True),
                AIProviderConfig.is_default.is_(True),
            )
            .order_by(AIProviderConfig.sort_order.asc(), AIProviderConfig.created_at.asc())
        )
        if selected:
            source = "provider_default"

    if selected:
        resolved_model = model or route_model or selected.default_model
        if not resolved_model:
            raise ValueError(f"AI 服务“{selected.name}”尚未设置默认模型")
        if not selected.api_key:
            raise ValueError(f"AI 服务“{selected.name}”尚未设置 API Key")
        return ResolvedAISelection(
            source=source,
            usage_type=usage_type,
            provider_config_id=selected.id,
            provider_name=selected.name,
            protocol=selected.protocol,
            wire_api=selected.wire_api,
            api_key=selected.api_key,
            base_url=selected.base_url,
            model=resolved_model,
        )

    legacy = await db.scalar(select(Settings).where(Settings.user_id == user_id))
    protocol = (legacy.api_provider if legacy else app_settings.default_ai_provider or "openai").lower()
    if protocol in {"mumu", "xiaomi_mimo", "custom", "azure"}:
        protocol = "openai"
    env_key = app_settings.openai_api_key
    env_base_url = app_settings.openai_base_url or "https://api.openai.com/v1"
    if protocol == "anthropic":
        env_key = app_settings.anthropic_api_key
        env_base_url = app_settings.anthropic_base_url or "https://api.anthropic.com"
    elif protocol == "gemini":
        env_key = app_settings.gemini_api_key
        env_base_url = app_settings.gemini_base_url or "https://generativelanguage.googleapis.com/v1beta"
    return ResolvedAISelection(
        source="legacy_default",
        usage_type=usage_type,
        provider_config_id=None,
        provider_name="旧版默认配置",
        protocol=protocol,
        wire_api="chat_completions",
        api_key=(legacy.api_key if legacy else None) or env_key or "",
        base_url=(legacy.api_base_url if legacy else None) or env_base_url,
        model=model or (legacy.llm_model if legacy else None) or app_settings.default_model,
    )


async def create_routed_ai_service(
    db: AsyncSession,
    *,
    user_id: str,
    usage_type: str,
    provider_config_id: Optional[str] = None,
    model: Optional[str] = None,
    project_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    task_trace_id: Optional[str] = None,
    enable_mcp: bool = True,
) -> AIService:
    """解析本次选择并创建带审计上下文的 AIService。"""
    selected = await resolve_ai_selection(
        db,
        user_id=user_id,
        usage_type=usage_type,
        provider_config_id=provider_config_id,
        model=model,
    )
    legacy = await db.scalar(select(Settings).where(Settings.user_id == user_id))
    if enable_mcp:
        enabled_plugin = await db.scalar(
            select(MCPPlugin.id).where(
                MCPPlugin.user_id == user_id,
                MCPPlugin.enabled.is_(True),
            ).limit(1)
        )
        enable_mcp = enabled_plugin is not None

    return create_user_ai_service_with_mcp(
        api_provider=protocol_to_runtime_provider(selected.protocol),
        api_key=selected.api_key,
        api_base_url=selected.base_url,
        openai_wire_api=selected.wire_api,
        model_name=selected.model,
        temperature=(legacy.temperature if legacy else None) or app_settings.default_temperature,
        max_tokens=(legacy.max_tokens if legacy else None) or app_settings.default_max_tokens,
        user_id=user_id,
        db_session=db,
        system_prompt=legacy.system_prompt if legacy else None,
        enable_mcp=enable_mcp,
        usage_type=usage_type,
        provider_config_id=selected.provider_config_id,
        provider_name=selected.provider_name,
        project_id=project_id,
        chapter_id=chapter_id,
        task_trace_id=task_trace_id,
    )
