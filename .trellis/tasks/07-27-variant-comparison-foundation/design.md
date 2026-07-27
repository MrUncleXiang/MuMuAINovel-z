# Technical Design

Implement additive batch/candidate ORM models, schemas, a shared comparison service and router. Store input/output as JSON plus optional text, never secrets. Use bounded async workers and independent task sessions. Adoption primitives use row locking/idempotency; target-specific mutation is injected through adapters.
