# Database Guidelines

- Use async SQLAlchemy (`AsyncSession`, `select`, `scalar/scalars`) and explicit `commit`/`rollback` boundaries.
- Every user-owned query filters by `user_id`; project/chapter routes call existing access checks such as `verify_project_access`.
- IDs are UUID strings (`String(36)`), matching existing models.
- Add constraints and indexes for invariants, not only application checks. Example: `uq_ai_usage_routes_user_usage`.
- Produce both PostgreSQL and SQLite migrations with the correct current heads. Test `alembic heads` and a clean SQLite upgrade.
- PostgreSQL is deployment truth. Never stamp a migration without applying its schema.
- Candidate generation uses immutable JSON input snapshots. Persist provider/model snapshots so later config edits do not rewrite history.
- Adoption is transactional and idempotent. Only one candidate in a comparison batch can be adopted at a time.
