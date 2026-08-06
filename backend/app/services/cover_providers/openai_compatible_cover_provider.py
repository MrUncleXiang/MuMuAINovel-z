"""OpenAI 兼容封面图片 Provider：支持任意 OpenAI Images API 兼容的自定义生图服务。

调用 {base_url}/images/generations，标准参数 model/prompt/n/response_format。
兼容 b64_json 和 url 两种返回。可用作自定义中转/自建服务接入。
"""
from __future__ import annotations

import base64
import struct
from typing import Any

import httpx

from app.logger import get_logger, safe_preview, summarize_log_value
from app.services.cover_providers.base_cover_provider import BaseCoverProvider, CoverGenerationResult

logger = get_logger(__name__)


class OpenAICompatibleCoverProvider(BaseCoverProvider):
    """基于 OpenAI Images API 协议的通用封面生成实现"""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    async def generate_cover(
        self,
        *,
        prompt: str,
        model: str,
        width: int,
        height: int,
    ) -> CoverGenerationResult:
        result = await self._request_cover(
            prompt=prompt,
            model=model,
            width=width,
            height=height,
        )
        return self._to_public_result(result)

    async def _request_cover(
        self,
        *,
        prompt: str,
        model: str,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # 封面默认尺寸；若服务端报尺寸超预算，则自动降级重试
        sizes = [f"{width}x{height}"]
        if width * height > 768 * 1024:
            sizes.append("768x1024")
        if width * height > 512 * 768:
            sizes.append("512x768")

        last_error: Exception | None = None
        for size in sizes:
            payload: dict[str, Any] = {
                "model": model,
                "prompt": self._adapt_prompt(prompt=prompt, width=width, height=height),
                "n": 1,
                "size": size,
                "response_format": "b64_json",
            }
            logger.debug(
                "OpenAI 兼容封面生成请求: url=%s model=%s size=%s prompt_len=%s",
                url, model, size, len(prompt or ""),
            )
            try:
                async with httpx.AsyncClient(timeout=240.0) as client:
                    response = await client.post(url, headers=headers, json=payload)
                if response.status_code != 200:
                    detail = safe_preview(response.text, 300)
                    logger.warning("OpenAI 兼容封面响应异常: status=%s size=%s detail=%s", response.status_code, size, detail)
                    if response.status_code == 400 and ("size" in detail.lower() or "budget" in detail.lower()):
                        # 尺寸超预算 → 降级重试
                        last_error = ValueError(f"尺寸超预算: {detail}")
                        continue
                    raise ValueError(f"生图服务返回 HTTP {response.status_code}: {detail}")
                data = response.json()
            except httpx.TimeoutException:
                raise
            except httpx.HTTPStatusError as exc:
                raise ValueError(f"生图服务 HTTP 错误: {exc.response.status_code} {safe_preview(exc.response.text, 300)}")
            except Exception:
                logger.error("OpenAI 兼容封面请求异常", exc_info=True)
                raise
            break
        else:
            raise ValueError(f"生图服务拒绝所有尺寸（最近错误: {last_error}）")

        images = data.get("data") or []
        if not images:
            logger.error("OpenAI 兼容未返回图片: data=%s", summarize_log_value(data))
            raise ValueError("生图服务未返回图片结果")

        image_item = images[0]
        revised_prompt = image_item.get("revised_prompt")
        b64_json = image_item.get("b64_json")
        if b64_json:
            decoded_content = self._decode_base64_image(b64_json)
            w, h = self._detect_image_size(decoded_content)
            return {
                "content": decoded_content,
                "mime_type": "image/jpeg",
                "file_extension": "jpg",
                "revised_prompt": revised_prompt,
                "provider": "custom",
                "model": model,
                "image_width": w,
                "image_height": h,
            }

        image_url = image_item.get("url")
        if image_url:
            async with httpx.AsyncClient(timeout=180.0) as client:
                image_response = await client.get(image_url)
            image_response.raise_for_status()
            content_type = image_response.headers.get("content-type", "image/jpeg")
            w, h = self._detect_image_size(image_response.content)
            return {
                "content": image_response.content,
                "mime_type": content_type,
                "file_extension": self._guess_extension(content_type=content_type, image_url=image_url),
                "revised_prompt": revised_prompt,
                "provider": "custom",
                "model": model,
                "image_width": w,
                "image_height": h,
            }

        logger.error("生图服务返回既无 b64_json 也无 url: %s", summarize_log_value(data))
        raise ValueError("生图服务未返回可用的图片数据")

    @staticmethod
    def _to_public_result(result: dict[str, Any]) -> CoverGenerationResult:
        return {
            "content": result["content"],
            "mime_type": result["mime_type"],
            "file_extension": result["file_extension"],
            "revised_prompt": result.get("revised_prompt"),
            "provider": result["provider"],
            "model": result["model"],
        }

    @staticmethod
    def _detect_image_size(content: bytes) -> tuple[int, int]:
        if len(content) >= 24 and content[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", content[16:24])
            return int(width), int(height)
        if len(content) >= 2 and content[:2] == b"\xff\xd8":
            index = 2
            content_length = len(content)
            while index < content_length - 1:
                if content[index] != 0xFF:
                    index += 1
                    continue
                marker = content[index + 1]
                index += 2
                if marker in (0xD8, 0xD9):
                    continue
                if index + 2 > content_length:
                    break
                segment_length = struct.unpack(">H", content[index:index + 2])[0]
                if segment_length < 2 or index + segment_length > content_length:
                    break
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    if index + 7 <= content_length:
                        height, width = struct.unpack(">HH", content[index + 3:index + 7])
                        return int(width), int(height)
                    break
                index += segment_length
        return 0, 0

    @staticmethod
    def _decode_base64_image(value: str) -> bytes:
        if value.startswith("data:") and "," in value:
            value = value.split(",", 1)[1]
        return base64.b64decode(value)

    @staticmethod
    def _adapt_prompt(*, prompt: str, width: int, height: int) -> str:
        cleaned_prompt = " ".join((prompt or "").split())
        return f"{cleaned_prompt} Use a {width}x{height} vertical composition."

    @staticmethod
    def _guess_extension(*, content_type: str, image_url: str) -> str:
        lowered_content_type = (content_type or "").lower()
        lowered_url = (image_url or "").lower()
        if "png" in lowered_content_type or lowered_url.endswith(".png"):
            return "png"
        if "webp" in lowered_content_type or lowered_url.endswith(".webp"):
            return "webp"
        return "jpg"
