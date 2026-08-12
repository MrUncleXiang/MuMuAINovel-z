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

## JSX/TSX syntax-error debugging (2026-08-11 lesson)

When `tsc`/vite reports confusing errors (e.g. `TS1005 ';' expected` far from the real cause), bisect with esbuild's parser for fast, line-accurate feedback:

```js
node -e "const e=require('esbuild');try{e.transformSync(require('fs').readFileSync('src/pages/X.tsx','utf8'),{loader:'tsx'});console.log('OK')}catch(x){console.log(x.errors[0].location)}"
```

Then **isolate the failing block** into a minimal test file (wrap in `<>` fragment so JSX context is preserved — `return (<Tabs .../>)` directly after `{/*comment*/}` is parsed as plain JS, not JSX, and misleads the bisect). If the block still fails standalone, strip pieces (delete Tab2 → simplify Tab1 → empty `items={[]}`) until the error moves.

Real root cause found this way: JSX opening tag missing its closing `>` — `items={[...]}` followed directly by `</Tabs>` with no `>` to close `<Tabs ...>`. `esbuild` reports `Expected ">" but found "<"` at the `</Tabs>` position. Check `]}`→`>` transitions when attributes end with arrays/objects.
