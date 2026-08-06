"""题材模板库 API：AI 分析示例 → 模板 → 保存/列表/选用。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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


class FirecrawlImportRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=500, description="目标榜单页 URL（番茄/起点等）")
    limit: int = Field(5, ge=1, le=10, description="要提炼的模板数量")
    api_key: Optional[str] = Field(default=None, max_length=200, description="firecrawl API Key（缺省用环境变量）")


@router.post("/import-firecrawl", summary="从榜单页自动采集热门题材")
async def import_firecrawl(
    data: FirecrawlImportRequest,
    user=Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """firecrawl 抓取榜单页 → AI 提炼 N 套热门题材模板 → 入库（source=firecrawl）。"""
    from app.services.firecrawl_service import FirecrawlError, scrape_url
    from app.services.ai_provider_service import create_routed_ai_service
    from app.services.json_helper import loads_json

    try:
        markdown = await scrape_url(data.url, api_key=data.api_key)
    except FirecrawlError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # 截取正文（避免超长，取前 1.5 万字符即可提炼）
    content = markdown[:15000]
    prompt = f"""你是网文题材分析师。下面是某个小说平台的热门榜单页面抓取内容。
请分析其中热度靠前的小说，提炼 {data.limit} 套热门题材模板，输出严格 JSON 数组（不要任何其他文字）：

【榜单内容】
{content}

【输出 JSON 格式】
[
  {{
    "title": "题材模板名（如：都市重生流）",
    "genre": "小说类型",
    "tags": ["标签1", "标签2"],
    "description": "题材一句话描述",
    "world_formula": "世界观设定公式",
    "character_prototypes": [{{"name": "角色原型", "role": "主角/反派等", "traits": "核心特质"}}],
    "volume_structure": "常见卷结构节奏"
  }}
]

只输出 JSON 数组。"""

    service = await create_routed_ai_service(
        db, user_id=user.user_id, usage_type="theme_analysis", task_trace_id="theme-import-firecrawl",
    )
    templates = []
    import asyncio
    for attempt in range(3):
        result = await service.generate_text(prompt=prompt, temperature=0.4, max_tokens=6000, auto_mcp=False)
        raw = result.get("content", "") if isinstance(result, dict) else str(result)
        try:
            parsed = loads_json(raw)
        except Exception:  # noqa: BLE001
            parsed = None
        candidates = parsed if isinstance(parsed, list) else (parsed.get("templates", []) if isinstance(parsed, dict) else [])
        if candidates:
            templates = candidates
            break
        await asyncio.sleep(5 * (attempt + 1))
    if not templates:
        raise HTTPException(status_code=502, detail="AI 未能从榜单提炼出模板，请换一个榜单页重试")

    created = []
    for t in templates[: data.limit]:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        template = ThemeTemplate(
            title=str(t["title"])[:200],
            genre=(str(t.get("genre") or "")[:50]) or None,
            tags=[str(x)[:50] for x in (t.get("tags") or []) if x],
            description=str(t.get("description") or ""),
            world_formula=str(t.get("world_formula") or ""),
            character_prototypes=[x for x in (t.get("character_prototypes") or []) if isinstance(x, dict)],
            volume_structure=str(t.get("volume_structure") or ""),
            source="firecrawl",
            source_refs=[data.url],
            created_by=user.user_id,
        )
        db.add(template)
        created.append(template)
    await db.commit()
    return {"imported": len(created), "templates": [ThemeTemplateResponse.model_validate(t) for t in created]}



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
