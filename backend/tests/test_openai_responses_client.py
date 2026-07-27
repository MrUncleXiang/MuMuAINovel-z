import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.api.ai_providers import test_provider_config
from app.services.ai_clients.openai_client import (
    OPENAI_WIRE_RESPONSES,
    OpenAIClient,
    _parse_responses_result,
)


class FakeStreamResponse:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for event in self.events:
            yield f"event: {event['type']}"
            yield f"data: {json.dumps(event)}"


class OpenAIResponsesClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = OpenAIClient(
            "test-key",
            "https://example.test/v1",
            wire_api=OPENAI_WIRE_RESPONSES,
        )

    async def asyncTearDown(self):
        await self.client.http_client.aclose()

    def test_builds_responses_payload_and_flattens_tools(self):
        payload = self.client._build_responses_payload(
            messages=[
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Hello"},
            ],
            model="gpt-test",
            temperature=0.2,
            max_tokens=123,
            tools=[{
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Look up a value",
                    "parameters": {"type": "object", "$schema": "ignored"},
                },
            }],
            tool_choice="auto",
            stream=True,
        )

        self.assertEqual(payload["instructions"], "Be concise.")
        self.assertEqual(payload["input"], [{"role": "user", "content": "Hello"}])
        self.assertEqual(payload["max_output_tokens"], 123)
        self.assertFalse(payload["store"])
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["tools"][0]["name"], "lookup")
        self.assertNotIn("$schema", payload["tools"][0]["parameters"])

    def test_parses_text_tools_and_usage(self):
        result = _parse_responses_result({
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "Done"}]},
                {"type": "function_call", "call_id": "call_1", "name": "lookup", "arguments": '{"id":1}'},
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        })

        self.assertEqual(result["content"], "Done")
        self.assertEqual(result["tool_calls"][0]["id"], "call_1")
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "lookup")
        self.assertEqual(result["finish_reason"], "tool_calls")
        self.assertEqual(result["usage"]["total_tokens"], 15)

    async def test_stream_normalizes_text_completion_and_usage(self):
        final_response = {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}],
            "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10},
        }
        events = [
            {"type": "response.output_text.delta", "delta": "O"},
            {"type": "response.output_text.delta", "delta": "K"},
            {"type": "response.completed", "response": final_response},
        ]
        calls = []

        async def fake_request(method, endpoint, payload, stream=False):
            calls.append((method, endpoint, payload, stream))
            return FakeStreamResponse(events)

        self.client._request_with_retry = fake_request
        chunks = [chunk async for chunk in self.client.chat_completion_stream(
            messages=[{"role": "user", "content": "Say OK"}],
            model="gpt-test",
            temperature=0,
            max_tokens=8,
        )]

        self.assertEqual(calls[0][1], "/responses")
        self.assertTrue(calls[0][3])
        self.assertEqual([chunk["content"] for chunk in chunks if "content" in chunk], ["O", "K"])
        self.assertEqual(next(chunk["usage"] for chunk in chunks if "usage" in chunk)["total_tokens"], 10)
        self.assertEqual(chunks[-1], {"finish_reason": "stop", "done": True})

    async def test_non_stream_uses_responses_endpoint(self):
        calls = []

        async def fake_request(method, endpoint, payload, stream=False):
            calls.append((method, endpoint, payload, stream))
            return {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}],
                "usage": {},
            }

        self.client._request_with_retry = fake_request
        result = await self.client.chat_completion(
            messages=[{"role": "user", "content": "Say OK"}],
            model="gpt-test",
            temperature=0,
            max_tokens=8,
        )

        self.assertEqual(calls[0][1], "/responses")
        self.assertEqual(result["content"], "OK")

    async def test_stream_normalizes_function_call(self):
        events = [{
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [{
                    "type": "function_call",
                    "call_id": "call_stream",
                    "name": "lookup",
                    "arguments": '{"id":2}',
                }],
                "usage": {"input_tokens": 9, "output_tokens": 3, "total_tokens": 12},
            },
        }]

        async def fake_request(method, endpoint, payload, stream=False):
            return FakeStreamResponse(events)

        self.client._request_with_retry = fake_request
        chunks = [chunk async for chunk in self.client.chat_completion_stream(
            messages=[{"role": "user", "content": "Use lookup"}],
            model="gpt-test",
            temperature=0,
            max_tokens=32,
            tools=[{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
        )]

        tool_chunk = next(chunk for chunk in chunks if "tool_calls" in chunk)
        self.assertEqual(tool_chunk["tool_calls"][0]["id"], "call_stream")
        self.assertEqual(chunks[-1], {"finish_reason": "tool_calls", "done": True})

    async def test_stream_raises_provider_error(self):
        async def fake_request(method, endpoint, payload, stream=False):
            return FakeStreamResponse([{
                "type": "response.failed",
                "response": {"error": {"message": "upstream failed"}},
            }])

        self.client._request_with_retry = fake_request
        with self.assertRaisesRegex(ValueError, "upstream failed"):
            async for _ in self.client.chat_completion_stream(
                messages=[{"role": "user", "content": "Hello"}],
                model="gpt-test",
                temperature=0,
                max_tokens=8,
            ):
                pass

    async def test_default_client_keeps_chat_completions_endpoint(self):
        chat_client = OpenAIClient("chat-key", "https://example.test/v1")
        calls = []

        async def fake_request(method, endpoint, payload, stream=False):
            calls.append(endpoint)
            return {
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {},
            }

        chat_client._request_with_retry = fake_request
        try:
            await chat_client.chat_completion(
                messages=[{"role": "user", "content": "Say OK"}],
                model="gpt-test",
                temperature=0,
                max_tokens=8,
            )
        finally:
            await chat_client.http_client.aclose()
        self.assertEqual(calls, ["/chat/completions"])


class ProviderConnectionTestErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_upstream_http_error_message(self):
        response = httpx.Response(
            503,
            request=httpx.Request("POST", "https://provider.test/v1/responses"),
            json={"error": {"message": "Service temporarily unavailable"}},
        )

        class FailingService:
            async def generate_text(self, **kwargs):
                raise httpx.HTTPStatusError("upstream error", request=response.request, response=response)

        with patch("app.api.ai_providers.create_routed_ai_service", return_value=FailingService()):
            with self.assertRaises(HTTPException) as raised:
                await test_provider_config(
                    "provider-id",
                    user=SimpleNamespace(user_id="user-id"),
                    db=object(),
                )

        self.assertEqual(
            raised.exception.detail,
            "供应商返回 HTTP 503：Service temporarily unavailable",
        )

    async def test_reports_provider_timeout(self):
        class TimeoutService:
            async def generate_text(self, **kwargs):
                raise httpx.ReadTimeout("timed out")

        with patch("app.api.ai_providers.create_routed_ai_service", return_value=TimeoutService()):
            with self.assertRaises(HTTPException) as raised:
                await test_provider_config(
                    "provider-id",
                    user=SimpleNamespace(user_id="user-id"),
                    db=object(),
                )

        self.assertEqual(raised.exception.detail, "供应商响应超时，请稍后重试")


if __name__ == "__main__":
    unittest.main()
