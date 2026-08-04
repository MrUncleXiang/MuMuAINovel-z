# Hook Guidelines

- Use `useEffect` for initial API loading and clean timers/polling on unmount.
- Stabilize callback dependencies; avoid stale project/chapter IDs during background polling.
- Shared project synchronization belongs in existing store hooks; modal selections remain local state.
- Polling stops on terminal candidate/batch states and on modal/page exit.
