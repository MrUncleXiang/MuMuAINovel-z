# Logging Guidelines

- Use `get_logger(__name__)`; lifecycle events are info, recoverable anomalies warning, and failures error with `exc_info=True` where useful.
- Include stable identifiers (`task_id`, `project_id`, `chapter_id`, comparison batch/candidate ID), not full content.
- LLM auditing belongs in `AICallLog`: provider/model snapshots, duration, tokens, status and trace IDs.
- Do not log API keys, authorization headers, full prompts, generated chapters, or private user text.
