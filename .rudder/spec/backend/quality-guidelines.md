# Backend Quality Guidelines

- Run `python3 -m compileall -q backend/app backend/alembic` and `git diff --check`.
- Import the app and configure ORM mappers in the runtime image before deployment.
- Verify migration heads and execute a clean SQLite upgrade; back up PostgreSQL before production migration.
- Multi-LLM comparison caps selections at four and concurrency at two by default to protect the VPS.
- Partial provider failure does not discard successful candidates; expose per-candidate state.
- Analysis candidates are preview-only. No memory, character, relationship, organization or foreshadow mutation before explicit adoption.
