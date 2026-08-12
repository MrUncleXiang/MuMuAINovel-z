# Component Guidelines

> Component conventions for the frontend (Ant Design based).

## Stack

- React 18 + Ant Design 5 + Vite. Dark mode via `theme.useToken()` + `useThemeMode`.

## Conventions

- **Ant Design primitives** for everything (Modal, Card, Form, Tabs, Select, Tag, Alert…); custom CSS only for special cases.
- **Modal interactions**: use controlled `<Modal open={...}>` with real component children when the content needs state/interaction. Avoid `modal.confirm` with static JSX for anything interactive (static-render trap — see `frontend-modal-interaction-guide.md`).
- **AI modification UX**: always "stream generation → diff confirmation (ReactDiffViewer) → apply on user confirm". Never apply AI edits silently. `ssePost` from `utils/sseClient` for streaming.
- **Model/service pickers**: reuse `AIServiceSelector` / `LLMMultiSelector`; display `供应商 · 模型`.
- **Big dialogs**: split by responsibility into Tabs (see the chapter editor's 4 tabs) and keep the save action global in the Modal footer. In `modal.confirm` dialogs, Tabs must be **uncontrolled** (`defaultActiveKey`); controlled `activeKey` silently breaks (static-render trap, 2026-08-11).
- **Dialog responsibility split** (2026-08-11 lesson from the continue-outline dialog): when a dialog mixes "form config" and "AI conversation" modes, split into Tabs — one Tab per mental model. Keep shared params (count/perspective/model) in a fixed bottom section outside the Tabs, so both tabs see them. One single submit button in the footer.
- **Button wording carries responsibility**: a dialog with a conversation area must NOT have a second submit-like button inside it ("采纳此方向，直接续写" was confusing vs footer "开始续写"). Conversation area's button should only feed the form ("确认此方向" → `form.setFieldsValue`), footer button is the only submit. User confirms step-by-step: choose → see it filled → click submit.
- **Field naming must match the domain**: the continue-outline dialog was labelled "续写章节数" while operating on outlines (卷), not chapters. Name fields after what they actually create ("续写大纲数（条）"), with a tooltip stating the real effect.
- Icons from `@ant-design/icons`; import only what's used (TS flags unused imports).
- `isMobile` adaptation: use `window.innerWidth <= 768` state + responsive layout (`isMobile ? ... : ...`).

## Anti-patterns

- ❌ New bespoke provider/model pickers per page.
- ❌ `modal.confirm` with stateful content (updates don't re-render; use controlled Modal).
- ❌ Directly applying AI output without diff review.
- ❌ Heavy pages as static imports in `App.tsx` (must be `React.lazy`).
