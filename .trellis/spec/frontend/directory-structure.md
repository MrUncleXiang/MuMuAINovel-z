# Directory Structure

> Frontend organization (`frontend/src/`).

## Layout

| Path | Responsibility |
|---|---|
| `pages/` | Route-level pages (Outline, Chapters, ChapterAnalysis, ReviewConfig, PipelinePanel, Settings…) — lazy-loaded via `React.lazy` in `App.tsx` |
| `components/` | Reusable components (AIServiceSelector, ChapterAIChatEdit, VolumeReviewModal, ChapterReviewModal, LLMCandidate*, PartialRegenerateToolbar…) |
| `store/` | Zustand global store (`index.ts` + typed hooks in `hooks.ts`) + `eventBus.ts` |
| `services/api.ts` | Axios instance (`api` default export) + per-domain API objects (`chapterApi`, `aiProviderApi`, …) |
| `types/index.ts` | Shared TS interfaces (146+ exports) |
| `hooks/` | Generic hooks (`useAnnouncements.ts`) |
| `theme/` | Theme system (`useThemeMode`, ThemeProvider, storage) |
| `utils/` | Utilities (e.g. `sseClient.ts` — SSE streaming helper) |
| `config/` | Config constants |

## Conventions

- Pages are **lazy-loaded routes** — never add a page as a static import in `App.tsx` (defeats code-splitting; main bundle must stay small).
- AI interactions reuse the shared selector components (`AIServiceSelector`, `LLMMultiSelector`) instead of each page building its own provider/model pickers.
- Model display must always include **provider + model** (`OpenCode Go · deepseek-v4-pro`), including placeholders.
