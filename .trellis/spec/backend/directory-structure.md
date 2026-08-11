# Directory Structure

> Module organization for the backend (`backend/app/`).

## Top-level layout

| Path | Responsibility | Notes |
|---|---|---|
| `api/` | FastAPI routers (one file per domain) | Routers mounted in `main.py` under `/api`; chapters router also serves SPA fallback? No — SPA fallback lives in `main.py` |
| `services/` | Business logic (thick modules) | See module map below |
| `models/` | SQLAlchemy ORM models | One file per domain; all imported in `models/__init__.py` so `Base.metadata` discovers them |
| `schemas/` | Pydantic request/response models | `model_config = ConfigDict(from_attributes=True)` for ORM responses |
| `skills/` | Writing/review SKILL packages | `SKILL.md` + `references/`; loaded via `skill_loader` |
| `middleware/` | Custom ASGI middleware | Auth, request ID, etc. |
| `mcp/` | MCP tool infrastructure | — |
| `utils/`, `security.py`, `user_manager.py` | Helpers | — |
| `database.py` | Engine + session factory + `get_db` | Per-user engine cache |
| `config.py` | Pydantic-settings app config | `default_max_tokens`, DB pool, http timeouts |

## Key services (module map)

| Module | Role |
|---|---|
| `ai_provider_service.py` | Model routing (`ai_usage_routes` per usage_type); `create_routed_ai_service` / `resolve_ai_selection` |
| `ai_clients/` | HTTP clients (OpenAI-compatible / Anthropic / Gemini); **browser UA mandatory** |
| `ai_service.py` | High-level `generate_text` / `generate_text_stream` wrappers + MCP + metrics |
| `background_task_service.py` | Per-user FIFO background queue; task funcs signature `(task_id, user_id)` |
| `chapter_review_service.py` | 3-step review pipeline (proofread → expression/AI-flavor → plot) |
| `chapter_analysis_materialization_service.py` | Persist analysis (memories, states, foreshadows) with content-hash guard |
| `memory_service.py` | Chroma vector memory, per-chapter slices |
| `foreshadow_service.py` / `career_update_service.py` / `character_state_update_service.py` | State sync from analysis |
| `formal_chapter_service.py` | Chapter "formalization" (content validation + persist + checkpoint invalidation) |

## Conventions

- Add new routers to `app/api/`, register in `main.py` with `prefix="/api"` (or skill routers without prefix).
- New tables: model in `models/`, migration in `alembic/postgres/versions/`, **and** import in `models/__init__.py` (create_all/migrations depend on it).
- Background task functions live next to their API endpoint or in the service that owns them; signature `(task_id, user_id)` only — they build their own session/tracker/AI service.
