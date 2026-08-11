# Type Safety

> TypeScript conventions for the frontend.

## Conventions

- All shared shapes live in `types/index.ts` (146+ interfaces) — request/response payloads, `Chapter`, `Project`, `Outline`, `LLMComparison*`, etc.
- API methods are typed via generics: `api.get<unknown, T>(url)` — the response type is `T`.
- **Prefer strict typing over `as` casts**: `useState<Chapter[]>([])`, typed props interfaces for every component.
- `tsconfig` strict mode is enforced by `npm run build` (tsc -b) — zero `any` leaks in committed code.

## Patterns

```tsx
interface Props { chapterId: string; onApply: (content: string) => void; }
export default function MyComp({ chapterId, onApply }: Props) { ... }
```

- API object responses that are unions/narrowed: define explicit types rather than `Record<string, any>`.
- `AIServiceSelection` / `ReviewProblem` / `ChapterReviewRecord` — exported from their components, import the type where needed.

## Anti-patterns

- ❌ `(result as any).xxx` in committed code (temporary debugging only).
- ❌ Inline `Record<string, any>` when the shape is known.
- ❌ `import { api } from '../services/api'` — `api` is the **default** export; named exports are the per-domain objects (`chapterApi`, `aiProviderApi`…).
