# OpenAI Wire API Contract

## 1. Scope / Trigger

Use this contract whenever an OpenAI-compatible provider is created, edited, selected, tested, or invoked. “OpenAI-compatible” does not imply that a provider supports both Chat Completions and Responses.

## 2. Signatures

- Database: `ai_provider_configs.wire_api VARCHAR(30) NOT NULL DEFAULT 'chat_completions'`.
- Provider API: `wire_api: 'chat_completions' | 'responses'`.
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

## 4. Validation & Error Matrix

- Unknown `wire_api` at the HTTP schema -> validation error.
- Unknown `wire_api` at direct client construction -> `ValueError`.
- `responses` with empty `output` and no function call -> `ValueError`.
- Responses `error`, `response.failed`, or SSE `error` -> request failure; never report a successful connection.
- Anthropic or Gemini configuration -> normalize `wire_api` to `chat_completions` and ignore it at runtime.

## 5. Good / Base / Bad Cases

- Good: provider supports `/v1/responses`; save `base_url=https://provider.example/v1` and `wire_api=responses`.
- Base: an existing OpenAI provider has no historical setting; migration backfills `chat_completions`.
- Bad: appending `/responses` to `base_url`, or retrying another wire API automatically after a billable request fails.

## 6. Tests Required

- Assert Chat providers retain `/chat/completions` behavior after migration.
- Assert Responses payload conversion includes `store: false` and removes tool `$schema`.
- Assert non-stream parsing covers text, function calls, finish reason, and input/output/total tokens.
- Assert SSE parsing covers `response.output_text.delta`, `response.completed`, tool calls, usage, and error events.
- Run PostgreSQL and SQLite migration-head checks plus a clean SQLite upgrade.
- Verify each configured wire API through the application connection-test endpoint, not only with direct provider calls.

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
