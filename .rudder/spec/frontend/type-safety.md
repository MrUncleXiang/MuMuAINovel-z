# Type Safety

- Declare shared API contracts in `frontend/src/types/index.ts` and use typed methods in `services/api.ts`.
- Avoid `any`; JSON snapshots use explicit interfaces or `unknown` plus narrowing.
- Candidate status, target type and adoption state are string unions matching backend schemas.
- Provider, project and chapter IDs are strings, not numbers.
