# Logging Guidelines

> Structured logging conventions for the backend.

## Setup

```python
from app.logger import get_logger
logger = get_logger(__name__)   # name = module path, e.g. app.api.chapters
```

## Levels

| Level | Use for |
|---|---|
| `INFO` | Key lifecycle events: task created/started/completed, chapter generated, analysis done, retries (`🔄`/`✅`/`📦`/`🔍` emoji prefixes are common) |
| `WARNING` | Recoverable issues: step failures that don't block, designed-in skips, retry attempts (`⚠️`) |
| `ERROR` | Real failures with context; use `exc_info=True` for tracebacks |

## Conventions

- Include identifiers in every log: `task_id`, `chapter_id`, `project_id`, `batch_id` (truncated ids like `{task_id[:8]}` for readability).
- Use consistent emoji markers (`📦 创建任务`, `🔍 开始分析`, `✅ 完成`, `❌ 失败`, `⚠️ 重试`) — they make log scanning fast.
- AI call summaries are logged by `ai_service` with metrics: model, status, durations, input/output chars, stream blocks. Use these (`docker logs | grep AI调用完成`) to distinguish transport vs model issues.
- Background tasks must log their final outcome (`✅ 任务完成` / `❌ 任务失败 + 原因`) so ops can tell success from stuck.

## Anti-patterns

- ❌ `print()` — always use the logger.
- ❌ Logging full API keys/secrets (log `api_key_hint` only).
- ❌ Silent failures: if you catch, log at WARNING/ERROR with reason.
