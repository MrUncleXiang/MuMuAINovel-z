# Frontend Quality Guidelines

- Run `npm run build` (TypeScript plus Vite) before commit.
- Loading, empty, partial-failure and retry states are required for multi-model generation.
- Warn that N selected models create N billable calls before submission.
- Default maximum is four candidates and concurrency two; disable duplicate submission during batch creation.
- Verify desktop and mobile layouts. Use existing theme tokens instead of hard-coded light colors.
