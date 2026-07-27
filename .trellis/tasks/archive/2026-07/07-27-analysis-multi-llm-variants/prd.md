# 分析多模型候选与延迟应用

## Requirements
- Multiple models analyze the exact same chapter/entity/foreshadow snapshot.
- Candidate generation is strictly preview-only: no memory, character, relationship, organization or foreshadow writes.
- Show score/report/suggestions and proposed entity changes for comparison.
- Only confirmed adoption applies the selected proposed changes, once, and preserves all candidates.

## Acceptance Criteria
- [ ] Database side-effect tables are unchanged after candidate generation.
- [ ] Adoption applies only the selected candidate and is idempotent.
- [ ] Conflicts caused by project changes since snapshot are detected and explained instead of blindly applied.
- [ ] Existing direct analysis behavior remains available until the new path is proven/migrated.
