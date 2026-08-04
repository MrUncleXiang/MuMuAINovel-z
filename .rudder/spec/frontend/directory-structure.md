# Frontend Directory Structure

- `frontend/src/pages/`: routed or major shell views.
- `frontend/src/components/`: reusable dialogs, selectors and comparison widgets.
- `frontend/src/services/api.ts`: shared Axios API methods; components do not duplicate base request logic.
- `frontend/src/types/index.ts`: shared backend-facing contracts.
- `frontend/src/store/`: Zustand global project state and hooks.

Reuse `AIServiceSelector` concepts for provider/model selection; introduce a multi-selection component instead of copying provider loading into each page.
