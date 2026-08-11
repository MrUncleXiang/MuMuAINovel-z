# AI Provider Integration

> How this project talks to external AI providers (OpenCode Go / OpenAI-compatible, Anthropic, Gemini), and how to diagnose upstream failures.

---

## 1. Mandatory: Browser User-Agent on all AI HTTP requests

**Rule**: Every outbound AI request **must** carry a browser-like `User-Agent`.

- Implemented centrally in `app/services/ai_clients/base_client.py` (`httpx.AsyncClient(headers={"User-Agent": ...})`).
- **Forbidden**: removing or overriding that header, constructing a new client without it, or using a raw `urllib`/`requests` call without a UA.
- **Why**: OpenCode Go sits behind Cloudflare which fingerprint-blocks requests with missing/script-like UAs. A blocked request returns `403 error code: 1010`, or — intermittently — **empty responses, truncated output, invalid JSON, or 524 timeouts**. These all *look* like model instability but are transport-layer blocks.

## 2. Diagnosing AI failures: check the transport layer FIRST

Symptom checklist (in order):

| Symptom | First suspect | How to verify |
|---|---|---|
| Empty response (`AI响应为空或过短`) | Upstream WAF / timeout | `docker logs` for `AI HTTP 状态错误`, 403/524, HTML body preview |
| Truncated / invalid JSON (`Unexpected end of input`) | WAF interference or response cut | Raw body preview in logs; retry with browser UA from the server |
| `403 code 1010` | Cloudflare UA fingerprint block | Replay the request with/without UA to confirm |
| Repeated JSON parse failures on a "big JSON" task | **Model is usually fine** — check transport first | Test the model directly with the same prompt |

**Lesson (2026-08-11)**: six consecutive analysis failures (empty/truncated/invalid JSON) were initially blamed on `deepseek-v4-flash` being "unstable for long JSON". Root cause was the missing UA. After the fix, flash passed 3/3 full chapter analyses. See trellis task `08-11-ai-cloudflare-ua-intercept`.

## 3. Model selection notes

- `deepseek-v4-flash` is **reliable** for long structured JSON output (chapter analysis, outline expansion). Do not downgrade it preemptively.
- `deepseek-v4-pro` is available on OpenCode Go for higher-quality output when a user explicitly wants stronger reasoning.
- Model list is cached in `ai_provider_configs.models`; refresh via the settings UI if the provider ships new models (this list matched upstream on 2026-08-11 — no staleness seen).
- Usage routing lives in `ai_usage_routes` (`usage_type` → provider_config + model). Changing it directly in DB works but can be overwritten by the settings UI — prefer the UI.

## 4. Failure UX rules

- Analysis task failure messages must include the **specific reason** + an actionable hint (e.g. "retry with a stronger model"), never a bare "check logs". Implemented in `app/api/chapters.py` (`last_fail_reason`).
- A **designed-in skip** (e.g. referencing a deleted foreshadow during sync) must **not** fail the whole analysis. It was previously appended to `errors` which aborted materialization; it is now warning-level only (`foreshadow_service.py`).
