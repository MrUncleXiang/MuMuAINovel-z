# Technical Design

## Domain Model

- `llm_comparison_batches`: user/project/target ownership, target type/id, immutable input snapshot, prompt/parameter snapshot, aggregate status and adopted candidate.
- `llm_comparison_candidates`: batch, provider/model snapshots, output JSON/text, status, metrics, error, attempt and adoption metadata.
- `ai_call_logs` gains an optional candidate/batch trace association without storing prompt or output content.

## State Flow

`draft -> queued/running -> completed|failed`; batch derives `running|partial|completed|failed`. Adoption locks the batch row, validates a completed candidate, updates formal content, then marks exactly one adopted candidate.

## Boundaries

- Shared service owns batch creation, concurrency semaphore, status persistence and generic queries.
- Target adapters own snapshot building, candidate generation and adoption.
- Chapter/outline adoption writes formal content. Analysis generation is side-effect free; its adoption alone applies memory/entity/foreshadow mutations.
- Frontend uses a reusable multi-LLM selector and comparison viewer.

## Compatibility and Rollback

Additive tables/API only. Existing single-generation endpoints remain. Database downgrade removes only unused comparison records; deployment keeps a PostgreSQL backup and prior image tag.
