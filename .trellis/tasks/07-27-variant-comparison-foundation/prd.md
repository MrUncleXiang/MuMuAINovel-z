# 候选比较共享数据与基础能力

## Requirements
- Add user-isolated batch/candidate persistence, PostgreSQL and SQLite migrations.
- Freeze input/prompt/parameters once per batch and snapshot provider/model per candidate.
- Provide create/list/detail/retry/delete/adopt-safe service primitives and per-candidate task states.
- Limit 2–4 unique selections and concurrency to two; retain successful results on partial failure.

## Acceptance Criteria
- [ ] Constraints enforce ownership, valid uniqueness and a single adopted candidate.
- [ ] Refresh/restart does not lose state; config edits do not alter candidate history.
- [ ] Unauthorized users cannot view or mutate a batch.
- [ ] Migrations and existing single-model calls pass regression checks.
