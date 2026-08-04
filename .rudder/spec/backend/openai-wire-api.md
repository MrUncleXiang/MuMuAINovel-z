# OpenAI Wire API Contract

## 1. Scope / Trigger

Use this contract whenever an OpenAI-compatible provider is created, edited, selected, tested, or invoked. “OpenAI-compatible” does not imply that a provider supports both Chat Completions and Responses.

## 2. Signatures

- Database: `ai_provider_configs.wire_api VARCHAR(30) NOT NULL DEFAULT 'chat_completions'`.
- Provider API: `wire_api: 'chat_completions' | 'responses'`.
- Connection test: `POST /api/ai-providers/{config_id}/test`; the frontend gives only this request a 300-second timeout.
- Runtime: `AIService(openai_wire_api='chat_completions')` passes the value to `OpenAIClient(..., wire_api=...)`.
- Endpoints:
  - `chat_completions` -> `POST {base_url}/chat/completions`
  - `responses` -> `POST {base_url}/responses`

## 3. Contracts

- `base_url` is the version root, for example `https://provider.example/v1`; it is not a full operation URL.
- Existing rows and legacy Settings always default to `chat_completions`.
- Responses requests use `input`, `instructions`, `max_output_tokens`, and `store: false`.
- Function tools are flattened to Responses fields: `type`, `name`, `description`, and `parameters`.
- The client boundary normalizes both wire APIs to `content`, `tool_calls`, `finish_reason`, and `usage` so providers and feature services remain wire-neutral.
- Connection-test UI state is component-local only. Each provider row may show `testing`, `success`, or `failed`, completion time, duration, and message; refresh clears it.
- The test request suppresses the global error toast because its row owns the visible result. Other API requests retain normal toast behavior.

## 4. Validation & Error Matrix

- Unknown `wire_api` at the HTTP schema -> validation error.
- Unknown `wire_api` at direct client construction -> `ValueError`.
- `responses` with empty `output` and no function call -> `ValueError`.
- Responses `error`, `response.failed`, or SSE `error` -> request failure; never report a successful connection.
- Upstream HTTP error during connection test -> HTTP 400 with `供应商返回 HTTP {status}：{upstream message}` when a JSON message exists.
- Provider HTTP client timeout -> HTTP 400 with `供应商响应超时，请稍后重试`.
- Browser reaches the dedicated 300-second test timeout -> row failure with `等待超过 5 分钟，供应商仍未响应，本次测试已超时`.
- Anthropic or Gemini configuration -> normalize `wire_api` to `chat_completions` and ignore it at runtime.

## 5. Good / Base / Bad Cases

- Good: provider supports `/v1/responses`; save `base_url=https://provider.example/v1` and `wire_api=responses`.
- Base: an existing OpenAI provider has no historical setting; migration backfills `chat_completions`.
- Bad: appending `/responses` to `base_url`, or retrying another wire API automatically after a billable request fails.
- Good: a slow test completes in 120-300 seconds and remains visible as a row success without a popup.
- Bad: reporting a 503 response as a timeout, or showing both global and local error popups for one test.

## 6. Tests Required

- Assert Chat providers retain `/chat/completions` behavior after migration.
- Assert Responses payload conversion includes `store: false` and removes tool `$schema`.
- Assert non-stream parsing covers text, function calls, finish reason, and input/output/total tokens.
- Assert SSE parsing covers `response.output_text.delta`, `response.completed`, tool calls, usage, and error events.
- Run PostgreSQL and SQLite migration-head checks plus a clean SQLite upgrade.
- Verify each configured wire API through the application connection-test endpoint, not only with direct provider calls.
- Assert connection tests preserve an upstream JSON error message and map provider timeouts explicitly.
- Build the frontend and verify the test request uses 300 seconds while the shared client remains at 120 seconds.

## 7. Wrong vs Correct

Wrong: choose the URL by guessing or treat `/models` success as proof that `/chat/completions` works.

```text
base_url=https://provider.example/v1/responses
wire_api omitted
```

Correct: store the version root and select the actual wire protocol explicitly.

```text
base_url=https://provider.example/v1
wire_api=responses
```

Wrong: increase the shared Axios timeout and rely on a temporary popup for the result.

Correct: override only the provider test to 300 seconds, suppress its global toast, and render the result in the provider row.
