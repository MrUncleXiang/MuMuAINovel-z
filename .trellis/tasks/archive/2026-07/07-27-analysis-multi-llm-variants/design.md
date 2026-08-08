# Technical Design

Split current analysis into a pure extraction phase returning analysis plus a proposed mutation set, and an apply phase. Record a snapshot fingerprint/version. Adoption locks the batch, checks current state compatibility, then applies memory/entity/foreshadow changes transactionally and marks the candidate adopted.
