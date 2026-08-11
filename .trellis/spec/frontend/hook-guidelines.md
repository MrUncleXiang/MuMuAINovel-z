# Hook Guidelines

> Custom hook conventions for the frontend.

## Existing hooks

- `hooks/useAnnouncements.ts` — global announcements.
- `theme/useThemeMode.ts` — resolved dark/light mode (`resolvedMode` used by ReactDiffViewer etc.).
- `store/hooks.ts` — store-wrapped data hooks.

## Conventions

- Name hooks `useXxx`; return plain values or a small object.
- **Event listeners/effects must clean up**: return cleanup from `useEffect` (remove listeners, clear intervals).
- Polling hooks: keep interval id + in-flight flag in `useRef`; guard against overlapping requests (a request-id counter); stop polling when no active items.
- Respect refs that mirror props (`currentProjectIdRef.current = currentProject?.id`) when async callbacks need the latest value without re-subscribing.

## Anti-patterns

- ❌ Hooks that create intervals without cleanup (leak + duplicate polls after unmount/remount).
- ❌ Async work in render; use `useEffect` + state.
- ❌ Recreating callbacks every render when they're used as effect deps (use `useCallback` with stable deps).
