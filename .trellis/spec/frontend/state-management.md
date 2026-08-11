# State Management

> Global vs local state conventions for the frontend.

## Global store (Zustand)

- `store/index.ts`: `useStore` via `create<AppState>()` — holds cross-page data: `currentProject`, `projects`, `outlines`, `chapters`, `currentChapter`, setters for each.
- `store/hooks.ts`: typed convenience hooks that wrap `useStore` + API calls (e.g. load project list into store).
- `store/eventBus.ts`: lightweight pub/sub for cross-component events (e.g. background task completion).

### When to put state in the store

- Data shared across pages/sidebar/header: project, outlines, chapters.
- Cross-component coordination (task status, refresh triggers).

### When to keep state local (`useState`)

- Modal/form state, tab active keys, transient UI flags, polling refs.
- Page-specific data that other pages don't read.

## Data fetching

- Pages call `services/api.ts` objects (`chapterApi.getChapters(...)`) then push into the store or local state.
- Long-running AI tasks: create background task → poll `GET /api/tasks/{id}` (or dedicated status endpoints) → on completion refresh local data. Use `useRef` for polling interval + in-flight guards, and clear intervals on unmount.

## Anti-patterns

- ❌ Duplicating the same list data in many local `useState`s when the store already has it.
- ❌ Polling without cleanup (interval leaks after unmount).
- ❌ Blocking re-renders with heavy synchronous work in render.
