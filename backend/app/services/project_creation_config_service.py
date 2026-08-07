"""Project-owned creation config resolution, validation and runtime freezing."""

import hashlib
import json

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_provider_config import AIProviderConfig, AIUsageRoute
from app.models.mcp_plugin import MCPPlugin
from app.models.project import Project
from app.models.project_creation_config import ProjectCreationConfig
from app.models.project_default_style import ProjectDefaultStyle
from app.models.writing_style import WritingStyle
from app.schemas.project_creation_config import (
    FrozenResourceSnapshot,
    ProjectCreationConfigData,
    ProjectCreationConfigResponse,
    ProjectCreationRuntimeSnapshot,
)
from app.services.skill_loader import get_skill_detail


def _version_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _legacy_config(db: AsyncSession, project: Project, user_id: str) -> ProjectCreationConfigData:
    routes = list((await db.scalars(select(AIUsageRoute).where(
        AIUsageRoute.user_id == user_id,
        AIUsageRoute.usage_type.in_(["chapter_write", "chapter_analysis"]),
    ))).all())
    route_map = {route.usage_type: route for route in routes}
    style_id = await db.scalar(select(ProjectDefaultStyle.style_id).where(
        ProjectDefaultStyle.project_id == project.id
    ))
    plugin_ids = list((await db.scalars(select(MCPPlugin.id).where(
        MCPPlugin.user_id == user_id,
        MCPPlugin.enabled.is_(True),
    ))).all())

    def selection(usage: str):
        route = route_map.get(usage)
        return {
            "provider_config_id": route.provider_config_id if route else None,
            "model": route.model if route else None,
        }

    return ProjectCreationConfigData.model_validate({
        "chapter": selection("chapter_write"),
        "analysis": selection("chapter_analysis"),
        "writing_style_id": style_id,
        "mcp": {"enabled": bool(plugin_ids), "plugin_ids": plugin_ids},
        "narrative_perspective": project.narrative_perspective,
    })


async def validate_project_creation_config(
    db: AsyncSession,
    *,
    user_id: str,
    config: ProjectCreationConfigData,
) -> list[str]:
    errors: list[str] = []
    for label, selection in (("章节模型", config.chapter), ("分析模型", config.analysis)):
        if not selection.provider_config_id:
            continue
        provider = await db.scalar(select(AIProviderConfig).where(
            AIProviderConfig.id == selection.provider_config_id,
            AIProviderConfig.user_id == user_id,
        ))
        if provider is None:
            errors.append(f"{label}服务不存在或不属于当前用户")
        elif not provider.enabled:
            errors.append(f"{label}服务“{provider.name}”已禁用")
        elif not (selection.model or provider.default_model):
            errors.append(f"{label}服务“{provider.name}”未指定模型")

    if config.skill_key and get_skill_detail(config.skill_key) is None:
        errors.append(f"Skill“{config.skill_key}”不存在")

    if config.writing_style_id is not None:
        style = await db.scalar(select(WritingStyle).where(
            WritingStyle.id == config.writing_style_id,
            or_(WritingStyle.user_id.is_(None), WritingStyle.user_id == user_id),
        ))
        if style is None:
            errors.append("写作风格不存在或不可用")

    if config.mcp.plugin_ids:
        plugins = list((await db.scalars(select(MCPPlugin).where(
            MCPPlugin.id.in_(config.mcp.plugin_ids),
            MCPPlugin.user_id == user_id,
        ))).all())
        plugins_by_id = {plugin.id: plugin for plugin in plugins}
        for plugin_id in config.mcp.plugin_ids:
            plugin = plugins_by_id.get(plugin_id)
            if plugin is None:
                errors.append(f"MCP 插件 {plugin_id} 不存在或不属于当前用户")
            elif not plugin.enabled:
                errors.append(f"MCP 插件“{plugin.display_name}”已禁用")
    return errors


async def get_project_creation_config(
    db: AsyncSession,
    *,
    project: Project,
    user_id: str,
) -> ProjectCreationConfigResponse:
    row = await db.scalar(select(ProjectCreationConfig).where(
        ProjectCreationConfig.project_id == project.id
    ))
    config = (
        ProjectCreationConfigData.model_validate(row.config)
        if row else await _legacy_config(db, project, user_id)
    )
    errors = await validate_project_creation_config(db, user_id=user_id, config=config)
    return ProjectCreationConfigResponse(
        project_id=project.id,
        config_version=row.config_version if row else 1,
        config=config,
        persisted=row is not None,
        validation_errors=errors,
        updated_at=row.updated_at.isoformat() if row and row.updated_at else None,
    )


async def save_project_creation_config(
    db: AsyncSession,
    *,
    project: Project,
    user_id: str,
    config: ProjectCreationConfigData,
) -> ProjectCreationConfigResponse:
    errors = await validate_project_creation_config(db, user_id=user_id, config=config)
    if errors:
        raise ValueError("；".join(errors))
    row = await db.scalar(select(ProjectCreationConfig).where(
        ProjectCreationConfig.project_id == project.id
    ).with_for_update())
    if row is None:
        row = ProjectCreationConfig(project_id=project.id, config_version=1, config={})
        db.add(row)
    else:
        row.config_version += 1
    row.config = config.model_dump(mode="json")
    await db.commit()
    await db.refresh(row)
    return await get_project_creation_config(db, project=project, user_id=user_id)


async def freeze_project_creation_config(
    db: AsyncSession,
    *,
    project: Project,
    user_id: str,
) -> ProjectCreationRuntimeSnapshot:
    response = await get_project_creation_config(db, project=project, user_id=user_id)
    if response.validation_errors:
        raise ValueError("；".join(response.validation_errors))
    config = response.config

    async def provider_snapshot(selection) -> FrozenResourceSnapshot:
        if not selection.provider_config_id:
            return FrozenResourceSnapshot(model=selection.model)
        provider = await db.scalar(select(AIProviderConfig).where(
            AIProviderConfig.id == selection.provider_config_id,
            AIProviderConfig.user_id == user_id,
        ))
        model = selection.model or provider.default_model
        return FrozenResourceSnapshot(
            id=provider.id,
            name=provider.name,
            provider_protocol=provider.protocol,
            model=model,
            version_hash=_version_hash([provider.id, provider.name, provider.protocol, model]),
        )

    skill_snapshot = None
    if config.skill_key:
        skill = get_skill_detail(config.skill_key)
        skill_snapshot = FrozenResourceSnapshot(
            id=config.skill_key,
            name=skill.get("template_name"),
            version_hash=_version_hash([
                skill.get("raw_content", ""),
                skill.get("standalone_references", {}),
            ]),
        )

    style_snapshot = None
    if config.writing_style_id is not None:
        style = await db.scalar(select(WritingStyle).where(WritingStyle.id == config.writing_style_id))
        style_snapshot = FrozenResourceSnapshot(
            id=str(style.id),
            name=style.name,
            version_hash=_version_hash(style.prompt_content),
        )

    plugins = []
    if config.mcp.enabled and config.mcp.plugin_ids:
        rows = list((await db.scalars(select(MCPPlugin).where(
            MCPPlugin.id.in_(config.mcp.plugin_ids),
            MCPPlugin.user_id == user_id,
        ))).all())
        plugins = [FrozenResourceSnapshot(
            id=plugin.id,
            name=plugin.display_name,
            version_hash=_version_hash([plugin.id, plugin.display_name, plugin.plugin_type]),
        ) for plugin in rows]

    return ProjectCreationRuntimeSnapshot(
        config_version=response.config_version,
        chapter=await provider_snapshot(config.chapter),
        analysis=await provider_snapshot(config.analysis),
        skill=skill_snapshot,
        writing_style=style_snapshot,
        mcp_plugins=plugins,
        parameters={
            "mcp_enabled": config.mcp.enabled,
            "narrative_perspective": config.narrative_perspective,
            "target_word_count": config.target_word_count,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "pipeline": config.pipeline.model_dump(mode="json"),
        },
    )
