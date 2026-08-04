# Backend Directory Structure

- `backend/app/api/`: FastAPI routers and HTTP permission checks. Register routers in `app/main.py`.
- `backend/app/schemas/`: Pydantic request/response contracts; never expose ORM rows or API keys directly.
- `backend/app/models/`: one SQLAlchemy model module per domain; register new models in `models/__init__.py` and `database.py` when mapper discovery requires it.
- `backend/app/services/`: reusable business logic. Cross-route LLM routing belongs here, as in `services/ai_provider_service.py`.
- `backend/alembic/postgres` and `backend/alembic/sqlite`: parallel migration chains.

Routes validate ownership, delegate reusable logic to services, and return schemas. Long LLM calls run outside request-held write locks or as tracked background tasks.
