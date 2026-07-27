"""OpenAI 客户端"""
import json
from typing import Any, AsyncGenerator, Dict, Optional

from app.logger import get_logger, summarize_log_value
from app.services.ai_config import AIClientConfig
from .base_client import BaseAIClient

logger = get_logger(__name__)

OPENAI_WIRE_CHAT_COMPLETIONS = "chat_completions"
OPENAI_WIRE_RESPONSES = "responses"


def _message_content_length(content: Any) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    return len(json.dumps(content, ensure_ascii=False, default=str))


def _log_request_summary(payload: Dict[str, Any]) -> None:
    messages = payload.get("messages") or []
    message_chars = sum(_message_content_length(message.get("content")) for message in messages if isinstance(message, dict))
    logger.debug(
        "📤 OpenAI 请求摘要: model=%s, messages=%s, message_chars=%s, tools=%s, stream=%s, max_tokens=%s",
        payload.get("model"),
        len(messages),
        message_chars,
        len(payload.get("tools") or []),
        bool(payload.get("stream")),
        payload.get("max_tokens"),
    )


def _log_response_summary(data: Dict[str, Any]) -> None:
    choices = data.get("choices") or []
    first_choice = choices[0] if choices else {}
    message = first_choice.get("message") or {}
    content = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []
    usage = data.get("usage") or {}
    logger.debug(
        "📥 OpenAI 响应摘要: choices=%s, finish_reason=%s, content_length=%s, tool_calls=%s, usage=%s",
        len(choices),
        first_choice.get("finish_reason"),
        len(content) if isinstance(content, str) else _message_content_length(content),
        len(tool_calls),
        summarize_log_value(usage),
    )


def _responses_usage(usage: Optional[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    usage = usage or {}
    return {
        "prompt_tokens": usage.get("input_tokens"),
        "completion_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _responses_finish_reason(data: Dict[str, Any], has_tool_calls: bool) -> str:
    if has_tool_calls:
        return "tool_calls"
    incomplete = data.get("incomplete_details") or {}
    if incomplete.get("reason") == "max_output_tokens":
        return "length"
    return "stop" if data.get("status") == "completed" else str(data.get("status") or "stop")


def _parse_responses_result(data: Dict[str, Any]) -> Dict[str, Any]:
    if data.get("error"):
        error = data["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise ValueError(f"Responses API 返回错误：{message}")

    content_parts = []
    tool_calls = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                    content_parts.append(str(part.get("text") or ""))
        elif item.get("type") == "function_call":
            call_id = item.get("call_id") or item.get("id") or ""
            tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": item.get("name") or "",
                    "arguments": item.get("arguments") or "",
                },
            })

    content = "".join(content_parts)
    if not content and not tool_calls:
        raise ValueError("Responses API 返回空 output")
    return {
        "content": content,
        "tool_calls": tool_calls or None,
        "finish_reason": _responses_finish_reason(data, bool(tool_calls)),
        "usage": _responses_usage(data.get("usage")),
    }


class OpenAIClient(BaseAIClient):
    """OpenAI API 客户端"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        config: Optional[AIClientConfig] = None,
        wire_api: str = OPENAI_WIRE_CHAT_COMPLETIONS,
    ):
        if wire_api not in {OPENAI_WIRE_CHAT_COMPLETIONS, OPENAI_WIRE_RESPONSES}:
            raise ValueError(f"不支持的 OpenAI wire API：{wire_api}")
        self.wire_api = wire_api
        super().__init__(api_key, base_url, config)

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: Optional[list] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stream:
            payload["stream"] = True
        if tools:
            # 清理 $schema 字段
            cleaned = []
            for t in tools:
                tc = t.copy()
                if "function" in tc and "parameters" in tc["function"]:
                    tc["function"]["parameters"] = {
                        k: v for k, v in tc["function"]["parameters"].items() if k != "$schema"
                    }
                cleaned.append(tc)
            payload["tools"] = cleaned
            if tool_choice:
                payload["tool_choice"] = tool_choice
        return payload

    def _build_responses_payload(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: Optional[list] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        instructions = []
        input_messages = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role in {"system", "developer"}:
                instructions.append(str(message.get("content") or ""))
            else:
                input_messages.append({"role": role, "content": message.get("content") or ""})

        payload: Dict[str, Any] = {
            "model": model,
            "input": input_messages,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "store": False,
        }
        if instructions:
            payload["instructions"] = "\n\n".join(instructions)
        if stream:
            payload["stream"] = True
        if tools:
            converted_tools = []
            for tool in tools:
                function = tool.get("function") or {}
                parameters = {
                    key: value
                    for key, value in (function.get("parameters") or {}).items()
                    if key != "$schema"
                }
                converted_tools.append({
                    "type": "function",
                    "name": function.get("name") or "",
                    "description": function.get("description") or "",
                    "parameters": parameters,
                })
            payload["tools"] = converted_tools
            if tool_choice:
                if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
                    function_choice = tool_choice.get("function") or {}
                    payload["tool_choice"] = {"type": "function", "name": function_choice.get("name") or ""}
                else:
                    payload["tool_choice"] = tool_choice
        return payload

    async def chat_completion(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: Optional[list] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.wire_api == OPENAI_WIRE_RESPONSES:
            return await self._responses_completion(
                messages, model, temperature, max_tokens, tools, tool_choice
            )
        payload = self._build_payload(messages, model, temperature, max_tokens, tools, tool_choice)
        
        _log_request_summary(payload)
        
        data = await self._request_with_retry("POST", "/chat/completions", payload)
        
        _log_response_summary(data)

        choices = data.get("choices", [])
        if not choices or len(choices) == 0:
            raise ValueError("API 返回空 choices 或 choices 为空列表")

        choice = choices[0]
        message = choice.get("message", {})
        usage = data.get("usage") or {}
        return {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls"),
            "finish_reason": choice.get("finish_reason"),
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
        }

    async def _responses_completion(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: Optional[list] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = self._build_responses_payload(
            messages, model, temperature, max_tokens, tools, tool_choice
        )
        logger.debug(
            "📤 OpenAI Responses 请求摘要: model=%s input=%s tools=%s max_output_tokens=%s",
            model,
            len(payload.get("input") or []),
            len(payload.get("tools") or []),
            max_tokens,
        )
        data = await self._request_with_retry("POST", "/responses", payload)
        result = _parse_responses_result(data)
        logger.debug(
            "📥 OpenAI Responses 响应摘要: status=%s content_length=%s tool_calls=%s usage=%s",
            data.get("status"),
            len(result["content"]),
            len(result.get("tool_calls") or []),
            summarize_log_value(result["usage"]),
        )
        return result

    async def chat_completion_stream(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: Optional[list] = None,
        tool_choice: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式生成，支持工具调用
        
        Yields:
            Dict with keys:
            - content: str - 文本内容块
            - tool_calls: list - 工具调用列表（如果有）
            - done: bool - 是否结束
        """
        if self.wire_api == OPENAI_WIRE_RESPONSES:
            async for chunk in self._responses_completion_stream(
                messages, model, temperature, max_tokens, tools, tool_choice
            ):
                yield chunk
            return

        payload = self._build_payload(messages, model, temperature, max_tokens, tools, tool_choice, stream=True)
        
        tool_calls_buffer = {}  # 收集工具调用块
        
        try:
            async with await self._request_with_retry("POST", "/chat/completions", payload, stream=True) as response:
                response.raise_for_status()
                try:
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                # 流结束，检查是否有工具调用需要处理
                                if tool_calls_buffer:
                                    yield {"tool_calls": list(tool_calls_buffer.values()), "done": True}
                                yield {"done": True}
                                break
                            try:
                                data = json.loads(data_str)
                                choices = data.get("choices", [])
                                if choices and len(choices) > 0:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content", "")
                                    
                                    # 检查工具调用
                                    tc_list = delta.get("tool_calls")
                                    if tc_list:
                                        for tc in tc_list:
                                            index = tc.get("index", 0)
                                            if index not in tool_calls_buffer:
                                                tool_calls_buffer[index] = tc
                                            else:
                                                existing = tool_calls_buffer[index]
                                                # 合并 function.arguments
                                                if "function" in tc and "function" in existing:
                                                    if tc["function"].get("arguments"):
                                                        existing["function"]["arguments"] = (
                                                            existing["function"].get("arguments", "") +
                                                            tc["function"]["arguments"]
                                                        )

                                    usage = data.get("usage")
                                    if usage:
                                        yield {
                                            "usage": {
                                                "prompt_tokens": usage.get("prompt_tokens"),
                                                "completion_tokens": usage.get("completion_tokens"),
                                                "total_tokens": usage.get("total_tokens"),
                                            }
                                        }
                                    
                                    if content:
                                        yield {"content": content}
                                        
                            except json.JSONDecodeError:
                                continue
                except GeneratorExit:
                    # 生成器被关闭，这是正常的清理过程
                    logger.debug("流式响应生成器被关闭(GeneratorExit)")
                    raise
                except Exception as iter_error:
                    logger.error(f"流式响应迭代出错: {str(iter_error)}")
                    raise
        except GeneratorExit:
            # 重新抛出GeneratorExit，让调用方处理
            raise
        except Exception as e:
            logger.error(f"流式请求出错: {str(e)}")
            raise

    async def _responses_completion_stream(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: Optional[list] = None,
        tool_choice: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        payload = self._build_responses_payload(
            messages, model, temperature, max_tokens, tools, tool_choice, stream=True
        )
        completed = False
        function_items: Dict[str, Dict[str, Any]] = {}
        async with await self._request_with_retry("POST", "/responses", payload, stream=True) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")
                if event_type == "response.output_text.delta" and event.get("delta"):
                    yield {"content": event["delta"]}
                elif event_type == "response.output_item.added":
                    item = event.get("item") or {}
                    if item.get("type") == "function_call":
                        key = str(item.get("id") or item.get("call_id") or event.get("output_index", 0))
                        function_items[key] = dict(item)
                elif event_type == "response.function_call_arguments.delta":
                    key = str(event.get("item_id") or event.get("output_index", 0))
                    item = function_items.setdefault(key, {"type": "function_call"})
                    item["arguments"] = str(item.get("arguments") or "") + str(event.get("delta") or "")
                elif event_type == "response.output_item.done":
                    item = event.get("item") or {}
                    if item.get("type") == "function_call":
                        key = str(item.get("id") or item.get("call_id") or event.get("output_index", 0))
                        function_items[key] = dict(item)
                elif event_type == "response.completed":
                    final_response = event.get("response") or {}
                    result = _parse_responses_result(final_response)
                    if result.get("tool_calls"):
                        yield {"tool_calls": result["tool_calls"]}
                    yield {"usage": result["usage"]}
                    yield {"finish_reason": result["finish_reason"], "done": True}
                    completed = True
                    break
                elif event_type in {"response.failed", "error"}:
                    error = event.get("error") or (event.get("response") or {}).get("error") or {}
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    raise ValueError(f"Responses API 流式请求失败：{message or event_type}")

        if not completed:
            buffered = {"output": list(function_items.values()), "status": "completed"}
            if function_items:
                result = _parse_responses_result(buffered)
                yield {"tool_calls": result["tool_calls"]}
            yield {"finish_reason": "tool_calls" if function_items else "stop", "done": True}
