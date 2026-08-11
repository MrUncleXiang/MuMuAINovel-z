# Quality Guidelines (Frontend)

> Code quality standards for the frontend.

## Automated checks

- `npm run build` runs `tsc -b` + `vite build` — **must pass before commit** (also enforced by the pre-commit hook's TS check).
- Build memory: on constrained servers use `NODE_OPTIONS=--max-old-space-size=4096` (vite/rollup OOMs at ~3.4G otherwise).
- Output goes to `backend/static/` (`vite.config.ts` outDir); deploy via `docker cp backend/static/. mumuainovel:/app/static/` + restart.

## Standards

- Types on all props/state; no unused imports (TS6133 blocks the build).
- Keep the main bundle small: lazy routes, vendor chunks via `manualChunks`, watch bundle-size warnings.
- Semantic component names, small focused components, share UI via `components/`.
- Match the existing visual language (AntD tokens, dark-mode support).

## Common mistakes

- ❌ Building without `NODE_OPTIONS` on this server → rollup "Aborted (core dumped)".
- ❌ Static imports for pages → 1.4MB main bundle (fixed 2026-08-11 with lazy routes; main bundle now ~65KB).
- ❌ Not running `npm run build` locally before `docker cp` — deploy stale bundles and then misdiagnose missing features as bugs (caching lesson: `index.html` is `no-cache`, assets `immutable`).
