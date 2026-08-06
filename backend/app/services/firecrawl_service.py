"""firecrawl 封装：AI 驱动的网页抓取（用于题材榜单采集）。"""
from typing import Optional

import httpx

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

FIRECRAWL_API = "https://api.firecrawl.dev/v1/scrape"


class FirecrawlError(ValueError):
    pass


async def scrape_url(url: str, api_key: Optional[str] = None, timeout: int = 90) -> str:
    """抓取一个网页并返回 markdown 正文。"""
    key = api_key or settings.firecrawl_api_key
    if not key:
        raise FirecrawlError("未配置 firecrawl API Key（环境变量 FIRECRAWL_API_KEY）")

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            FIRECRAWL_API,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
        )
    if resp.status_code != 200:
        raise FirecrawlError(f"firecrawl 抓取失败 HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if not data.get("success"):
        raise FirecrawlError(f"firecrawl 返回失败: {str(data)[:200]}")
    markdown = (data.get("data") or {}).get("markdown") or ""
    if not markdown.strip():
        raise FirecrawlError(f"抓取结果为空（目标页面可能反爬）：{url}")
    return markdown
