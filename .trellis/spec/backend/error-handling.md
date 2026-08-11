# Error Handling

> How errors are defined, propagated, logged, and returned to clients in the backend.

## Error types

- **API layer**: `HTTPException(status_code, detail)` — client-facing Chinese messages.
- **Business/services**: plain `Exception` / `RuntimeError`; the API layer catches and converts.
- **Background tasks**: never raise silently — catch at task top-level, call `tracker.error(str(e))`, set `task.status='failed'` + `task.error_message` (specific reason), and roll back the session.

## Propagation rules

1. **Requests**: `try/except` around AI/DB calls; re-raise `HTTPException`, log others and return 500 JSON (global handler in `main.py`).
2. **Background task function** signature `(task_id, user_id)`: wrap the whole body in `try/except`, `await tracker.error(...)` on failure.
3. **Non-fatal steps must not fail the whole task**:
   - A designed-in skip (e.g. analysis references a deleted foreshadow) → warning + counter, **not** `errors[]` (was once appended to `errors` and aborted the whole analysis — fixed 2026-08-11).
   - Review-step failures inside generation → `logger.warning` + continue (never block generation).
4. **AI failures**: layered diagnosis first (WAF/UA → streaming cutoff → provider 100s cap → model). See `ai-provider-integration.md`. `last_fail_reason` is captured via the retry callback so the final `error_message` says *why* and what to do (e.g. "retry with a stronger model") — never a bare "check logs".

## Client-facing messages

- Chinese, specific, actionable: `"AI分析失败：{reason}。可关闭后重新分析，或在弹窗中选择更强模型。"`
- Do not leak stack traces to clients (global 500 handler returns a generic message in production).

## Anti-patterns

- ❌ Swallowing exceptions with bare `pass` (unless the operation is genuinely optional and logged).
- ❌ Letting a background task die without marking the DB row failed (leaves tasks stuck in `running` after a container restart — the memory queue is lost on restart).
- ❌ Blaming the model for transport-layer failures without checking logs first.
