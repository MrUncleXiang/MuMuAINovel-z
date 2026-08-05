"""题材模板库 API：AI 分析示例 → 模板 → 保存/列表/选用。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.settings import require_login
from app.database import get_db
from app.models.theme_template import ThemeTemplate
from app.schemas.theme_template import (
    ThemeAnalyzeRequest,
    ThemeAnalyzeResponse,
    ThemeTemplateCreate,
    ThemeTemplateResponse,
)
from app.services.json_helper import loads_json

router = APIRouter(prefix="/theme-templates", tags=["题材模板库"])


@router.post("/analyze", response_model=ThemeAnalyzeResponse, summary="AI 分析示例提炼题材模板")
async def analyze_examples(
    data: ThemeAnalyzeRequest,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """给几个示例（书名/链接/简介），AI 提炼一套题材模板。"""
    from app.services.ai_provider_service import create_routed_ai_service

    examples_text = "\n".join(f"- {e}" for e in data.examples)
    genre_hint = data.genre_hint or "不限"
    prompt = f"""你是网文题材分析师。请分析以下热门小说示例，提炼它们的共同成功公式，输出严格 JSON（不要任何其他文字）：

【示例】
{examples_text}

【输出 JSON 格式】
{{
  "title": "题材模板名（如：都市重生流）",
  "genre": "小说类型",
  "tags": ["标签1", "标签2", "标签3"],
  "description": "题材一句话描述",
  "world_formula": "世界观设定公式（时代背景、力量体系、核心冲突）",
  "character_prototypes": [
    {{"name": "角色原型名", "role": "主角/反派/女主等", "traits": "核心性格特质", "backstory": "背景公式"}}
  ],
  "volume_structure": "常见卷结构节奏（如：第一卷崛起→第二卷冲突升级→第三卷反转）"
}}

只输出 JSON。"""

    service = await create_routed_ai_service(
        db,
        user_id=user.user_id,
        usage_type="theme_analysis",
        task_trace_id="theme-analyze",
    )
    result = await service.generate_text(prompt=prompt, temperature=0.4, max_tokens=3000, auto_mcp=False)
    raw = result.get("content", "") if isinstance(result, dict) else str(result)
    parsed = loads_json(raw)
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="AI 分析结果无法解析，请重试")
    # 补全必填字段
    parsed.setdefault("title", data.examples[0][:50])
    parsed.setdefault("genre", data.genre_hint)
    parsed.setdefault("tags", [])
    parsed.setdefault("description", "")
    parsed.setdefault("world_formula", "")
    parsed.setdefault("character_prototypes", [])
    parsed.setdefault("volume_structure", "")
    parsed["source_refs"] = data.examples
    return ThemeAnalyzeResponse(**parsed)


@router.post("", response_model=ThemeTemplateResponse, summary="保存题材模板")
async def create_template(
    data: ThemeTemplateCreate,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    template = ThemeTemplate(
        **data.model_dump(),
        source="manual",
        created_by=user.user_id,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@router.get("", response_model=list[ThemeTemplateResponse], summary="题材模板列表")
async def list_templates(
    genre: str | None = None,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ThemeTemplate).order_by(ThemeTemplate.usage_count.desc(), ThemeTemplate.created_at.desc())
    if genre:
        stmt = stmt.where(ThemeTemplate.genre == genre)
    return list((await db.scalars(stmt)).all())


@router.delete("/{template_id}", status_code=204, summary="删除题材模板")
async def delete_template(
    template_id: str,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    template = await db.get(ThemeTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    await db.delete(template)
    await db.commit()


@router.post("/{template_id}/use", response_model=ThemeTemplateResponse, summary="标记模板被选用")
async def use_template(
    template_id: str,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    template = await db.get(ThemeTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    template.usage_count = (template.usage_count or 0) + 1
    await db.commit()
    await db.refresh(template)
    return template
