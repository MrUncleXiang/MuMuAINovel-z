# Error Handling

- Raise `HTTPException` with short Chinese messages for expected HTTP failures (401/404/409/422).
- Services may raise narrow `ValueError` for selection/config errors; API boundaries translate them.
- Roll back before returning a database integrity conflict.
- Background tasks always enter a terminal state (`completed` or `failed`) with a concise `error_message`.
- Never hide a failed migration, adoption, or state mutation behind a success response.
- Never include API keys, full prompts, or novel content in errors.
