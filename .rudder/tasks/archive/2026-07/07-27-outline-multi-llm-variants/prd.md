# 大纲多模型候选方案

## Requirements
- Generate multiple outline proposals from one frozen project/request snapshot.
- Keep proposals separate from the formal outline until adoption.
- Compare structure and content, retain all proposals, and adopt one formal proposal.
- Existing single-outline generation remains available.

## Acceptance Criteria
- [ ] Multiple proposals coexist with provider/model/metrics.
- [ ] Formal outline changes only after confirmed adoption.
- [ ] Adoption does not silently overwrite chapters derived from a different outline; warn or block according to project state.
