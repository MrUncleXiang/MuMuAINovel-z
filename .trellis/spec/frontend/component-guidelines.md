# Component Guidelines

> Component conventions for the frontend (Ant Design based).

## Stack

- React 18 + Ant Design 5 + Vite. Dark mode via `theme.useToken()` + `useThemeMode`.

## Conventions

- **Ant Design primitives** for everything (Modal, Card, Form, Tabs, Select, Tag, Alert…); custom CSS only for special cases.
- **Modal interactions**: use controlled `<Modal open={...}>` with real component children when the content needs state/interaction. Avoid `modal.confirm` with static JSX for anything interactive (static-render trap — see `frontend-modal-interaction-guide.md`).
- **AI modification UX**: always "stream generation → diff confirmation (ReactDiffViewer) → apply on user confirm". Never apply AI edits silently. `ssePost` from `utils/sseClient` for streaming.
- **Model/service pickers**: reuse `AIServiceSelector` / `LLMMultiSelector`; display `供应商 · 模型`.
- **Big dialogs**: split by responsibility into Tabs (see the chapter editor's 4 tabs) and keep the save action global in the Modal footer.
- Icons from `@ant-design/icons`; import only what's used (TS flags unused imports).
- `isMobile` adaptation: use `window.innerWidth <= 768` state + responsive layout (`isMobile ? ... : ...`).

## Anti-patterns

- ❌ New bespoke provider/model pickers per page.
- ❌ `modal.confirm` with stateful content (updates don't re-render; use controlled Modal).
- ❌ Directly applying AI output without diff review.
- ❌ Heavy pages as static imports in `App.tsx` (must be `React.lazy`).
