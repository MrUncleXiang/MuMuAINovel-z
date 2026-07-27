# Implementation Plan

1. Finish and validate shared foundation task.
2. Deliver chapter candidates as the first end-to-end vertical slice.
3. Extend the proven abstraction to outline candidates.
4. Refactor analysis into preview generation plus explicit side-effect adoption.
5. Run backend compile/import, PostgreSQL and clean SQLite migration checks, frontend build, authorization/idempotency tests, and low-resource deployment checks.
6. Back up production, deploy the lightweight GHCR image, verify health/migration/UI, retain rollback image.

Each child is reviewed and archived before the dependent child starts. Analysis cannot start until foundation and chapter adoption behavior are proven.
