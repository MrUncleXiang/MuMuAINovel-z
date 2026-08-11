# AI Provider Integration

> How this project talks to external AI providers (OpenCode Go / OpenAI-compatible, Anthropic, Gemini), and how to diagnose upstream failures.

---

## 1. Mandatory: Browser User-Agent on all AI HTTP requests

**Rule**: Every outbound AI request **must** carry a browser-like `User-Agent`.

- Implemented centrally in `app/services/ai_clients/base_client.py` (`httpx.AsyncClient(headers={"User-Agent": ...})`).
- **Forbidden**: removing or overriding that header, constructing a new client without it, or using a raw `urllib`/`requests` call without a UA.
- **Why**: OpenCode Go sits behind Cloudflare which fingerprint-blocks requests with missing/script-like UAs. A blocked request returns `403 error code: 1010`, or — intermittently — **empty responses, truncated output, invalid JSON, or 524 timeouts**. These all *look* like model instability but are transport-layer blocks.

## 2. Diagnosing AI failures: layered checklist (transport → connection → model)

The 2026-08-11 analysis saga proved that upstream failures have **multiple layers**. Diagnose in this order; each layer masks the next.

| # | Layer | Symptom | Root cause | Fix |
|---|---|---|---|---|
| 1 | WAF / UA | `403 code 1010`, empty response, truncated, 524 (intermittent) | Cloudflare UA fingerprint block | Browser UA on every request (`base_client.py`) |
| 2 | Streaming connection | Output truncated at ~100s while model *did* generate (billing tokens ≫ received chars) | Cloudflare kills long-lived SSE streams (~100s) | Use **non-streaming** (`generate_text`) for background tasks that don't need streaming |
| 3 | Response timeout | `524: A timeout occurred` on non-streaming | Cloudflare 100s response cap on the free plan | Keep total generation < 100s: smaller input, or use a faster model (pro) |
| 4 | Model capability | Early stop (1 output token), empty reply, very slow TTFT (>90s) | Lightweight model on large/complex structured-output tasks | Use pro for big-JSON tasks, or add automatic pro fallback |

**Key evidence (2026-08-11)**:
- flash analysis: 13–14K input chars → 63–71s **success**; 16K input → 4/4 failures (1-token early stop, 95s TTFT + truncated stream, empty replies).
- pro same task: 35–45s, stable.
- A "truncated at 4.3K chars" call billed **11997 output tokens** — the model finished; only the transport was cut.

## 3. Model selection & routing

- **Task-based split**: chapter analysis / outline expansion / other big-JSON structured output → **`deepseek-v4-pro`** (stable <100s); creative generation (chapter writing, streaming) → `deepseek-v4-flash` (cheap).
- `chapter_analysis` usage route is the single place that decides the analysis model (DB `ai_usage_routes`). **Batch pipeline's internal analysis must use this route** (`create_routed_ai_service(usage_type="chapter_analysis")`), NOT `get_user_ai_service` (the user's global default, often flash) — this was the root cause of batch analysis stalling on 524s.
- **Automatic fallback**: primary model fails (3 retries) → retry once with the `chapter_analysis` route model (`pro`). Implemented in `analyze_chapter_background` (step 3b). Keeps flash-first economics with a pro safety net.
- Model list is cached in `ai_provider_configs.models`; refresh via the settings UI if the provider ships new models.
- Changing `ai_usage_routes` directly in DB works but can be overwritten by the settings UI — prefer the UI.

## 4. Failure UX rules

- Analysis task failure messages must include the **specific reason** + an actionable hint (e.g. "retry with a stronger model"), never a bare "check logs". Implemented in `app/api/chapters.py` (`last_fail_reason`).
- A **designed-in skip** (e.g. referencing a deleted foreshadow during sync) must **not** fail the whole analysis. It was previously appended to `errors` which aborted materialization; it is now warning-level only (`foreshadow_service.py`).
- Frontend must always display **provider name + model** together (e.g. `OpenCode Go · deepseek-v4-pro`), including placeholders/defaults — never a bare model name or a bare "default".

## 5. Operational notes

- Deploying = `docker restart` = a 30–60s no-service window. Clients see 502 during it (gateway-level, not backend logs). Batch deployments, avoid active use windows, warn the user.
- Static assets: `index.html` served with `no-cache`; `/assets/*` with `immutable` (hash filenames). Never strip these headers (cached old UI was misdiagnosed as "feature missing" once).
