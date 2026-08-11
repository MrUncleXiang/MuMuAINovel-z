# Quality Guidelines

> Code standards and forbidden patterns for the backend.

## Automated checks (pre-commit, runs on every commit)

1. **pyflakes undefined-name scan** — zero tolerance (`undefined name` = runtime 500). Run: `python3 -m pyflakes app/ | grep "undefined name"`.
2. **Python syntax check** — `ast.parse` over all files.
3. **Frontend TS type check** — `cd frontend && npx tsc --noEmit`.

If a commit is blocked, fix the reported issue; do not `--no-verify` except for emergencies.

## Standards

- Type annotations on public functions; use Pydantic for request/response boundaries.
- Async-first: no blocking I/O in request handlers (DB/AI/HTTP all async).
- `async with write_lock:` for cross-task status transitions (per-user lock).
- Services are deep modules: thin API layer + logic in `services/`.
- New features follow the existing patterns: background tasks for long AI work, `task_id` returned to frontend, polling via `GET /api/tasks/{id}`.

## Forbidden patterns

- ❌ Synchronous AI calls in request handlers (long tasks must be background tasks).
- ❌ Reusing a request session in a background task (build your own via `get_engine`).
- ❌ Ignoring the `content_hash` guard — stale analysis results must never be materialized.
- ❌ Stripping the browser UA from AI clients (Cloudflare blocks).
- ❌ Direct DB writes for config that the UI owns (`ai_usage_routes`, provider configs).
- ❌ Reusing the generation service (user default model) for analysis — analysis must go through the `chapter_analysis` route.

## Common mistakes (from 2026-08-11)

- Background task function signatures: the executor calls `task_func(task_id, user_id, *extra_args)` — write `(task_id, user_id)` and build everything inside; don't expect auto-injected `db`/`tracker`.
- After a container restart, in-memory task queues die; ensure DB rows get marked failed (or the frontend shows them as stuck).
- Big-JSON tasks (analysis, outline expansion) need a stable model (pro) or an automatic fallback — flash-only is fine for creative streaming generation.
