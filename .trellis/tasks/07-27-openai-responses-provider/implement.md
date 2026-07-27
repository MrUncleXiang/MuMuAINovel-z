# Implementation Plan

1. [x] Add PostgreSQL/SQLite migrations, ORM field, API schema validation and response serialization for `wire_api`.
2. [x] Carry `wire_api` through selection and AI service/client construction while preserving legacy defaults.
3. [x] Implement Responses payload conversion, non-stream parsing and SSE event parsing in the OpenAI client.
4. [x] Add the OpenAI-only interface selector and type updates to AI Service Management.
5. [x] Add focused backend tests for payloads, normal responses, streaming, tools and compatibility.
6. [x] Run Python checks, migrations, frontend lint/build, then rebuild the application container.
7. [x] Configure vc-grok as `responses` and verify live non-stream/stream requests from a clean application baseline.

## Risk And Rollback Points

- Migration: verify both database families before deployment; default must preserve existing records.
- Stream parser: fixture-test event ordering and duplicated completion events.
- Tools: normalize function calls once in the client boundary so MCP code remains unchanged.
- Deployment: retain the current image tag and database backup before migration/recreate.
