# Database Guidelines

> ORM patterns, migrations, and query conventions for `backend/app/`.

## Stack

- **SQLAlchemy 2.0 async** + `asyncpg` (PostgreSQL), `aiosqlite` (tests/local).
- Alembic migrations: `alembic/postgres/versions/` (PostgreSQL) and `alembic/sqlite/versions/` (SQLite). Entrypoint runs `alembic upgrade head` at container start.

## Rules

### Models

- One file per domain in `app/models/`, columns typed explicitly; use `comment=` for business meaning.
- **Every new model must be imported in `app/models/__init__.py`** — `Base.metadata` (create_all) and router imports depend on it. Missing import = "table not found" at runtime.
- New column → **alembic migration** (never raw `ALTER TABLE` in code). Server defaults for non-nullable new columns.

### Sessions

- Request-scoped: `Depends(get_db)` yields `AsyncSession`.
- Background tasks: create their own session via `get_engine(user_id)` + `async_sessionmaker(...)` inside the task function. **Never** reuse the request session in a background task.
- Use `async with write_lock:` (per-user DB write lock from `get_db_write_lock`) for status transitions in concurrent tasks.

### Queries

- Prefer `select()` + `db.scalar()` / `db.scalars()` / `db.execute()`.
- `await db.refresh(obj)` after commit when returning the object.
- `db.expire_all()` (sync method on AsyncSession) is used between long polls in batch generation to re-read rows.

### Migrations (PostgreSQL)

```bash
cd backend
alembic revision --autogenerate -m "描述"        # create
alembic upgrade head                            # apply (container entrypoint does this too)
```

- `down_revision` must point at the current head. `op.create_index` collides with `Column(index=True)` — pick one (prefer the model declaration, drop the explicit index in the migration).

## Known pitfalls (2026-08-11)

- `chapter_review_records` migration initially failed with "index already exists" because the model declared `index=True` **and** the migration created the index explicitly. Remove the explicit `create_index` when the column already has `index=True`.
- Editing `review_config`/`ai_usage_routes` directly in DB works but can be overwritten by the settings UI — prefer UI for config, migrations for schema.
