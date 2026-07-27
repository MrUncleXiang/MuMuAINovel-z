# Technical Design

## Data Flow

`AIProviderManagement` -> provider API schema -> `ai_provider_configs.wire_api` -> `ResolvedAISelection` -> `AIService` -> `OpenAIClient` -> Chat or Responses endpoint -> normalized result consumed by `OpenAIProvider`.

The upper `AIService` and feature pages continue to consume the existing normalized contract:

```text
content, tool_calls, finish_reason, usage
```

## Storage And Compatibility

- Add non-null `wire_api` with server default `chat_completions` in PostgreSQL and SQLite migrations.
- ORM and Pydantic default to `chat_completions`.
- `wire_api` is meaningful only when `protocol == openai`; other protocols normalize it to the compatibility default.
- Legacy Settings-created clients receive the default and retain current behavior.

## Client Boundary

Keep one `OpenAIClient` and select its wire implementation from constructor configuration. Chat methods remain unchanged. Responses helpers own:

- Chat-style messages -> Responses `instructions` plus `input` conversion.
- Chat-style function tools -> flattened Responses function tools.
- Non-stream output items -> normalized content and Chat-style tool calls.
- SSE event types -> the client's existing stream chunk contract.
- Responses usage keys -> `prompt_tokens`, `completion_tokens`, `total_tokens`.

The provider layer remains protocol-neutral and requires no feature-page changes.

## Error Handling

- Preserve `httpx` status errors so the existing connection-test endpoint returns the decisive upstream error.
- Treat missing/empty Responses output as an invalid response rather than reporting success.
- Raise on `response.failed`, `response.incomplete` with a provider error, or SSE `error` events.
- Do not log API keys, full prompts, or full response bodies on success.

## Rollback

- Code rollback leaves the added database column harmless.
- Migration downgrade removes only `wire_api`.
- Existing rows are safe because the upgrade backfills `chat_completions`.
