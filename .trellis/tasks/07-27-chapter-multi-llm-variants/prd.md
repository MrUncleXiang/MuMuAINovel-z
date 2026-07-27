# 章节多模型候选版本

## Requirements
- Freeze the same chapter context, outline, characters, style, prompt and parameters for all selected LLMs.
- Store all outputs as candidates without changing the formal chapter during generation.
- Show card and two-result comparison/diff views with provider/model/metrics.
- Let the user retry one result, edit/copy it, and adopt one candidate as formal chapter content.
- Adoption preserves all other candidates and records the prior formal content/history.

## Acceptance Criteria
- [ ] 2–4 candidates can coexist for one chapter and survive refresh.
- [ ] Formal chapter is unchanged before adoption and updated exactly once after confirmation.
- [ ] Later chapters use only the adopted formal chapter, not arbitrary candidates.
- [ ] Partial failure and individual retry work.
