# 章节正文审查引擎（3步流水线+打回重写）

## Goal

批量生成/单章生成后自动审查：①proofread错别字②aidetect+human表达/细节/AI味（含信息完整性规则）③review剧情/伏笔/人设。每步检测→问题提取→原地最小修改；major问题打回重写（注入问题清单，同生成配置）；每章最多2轮。审查报告入库。SKILL.md补充：aidetect加信息完整性检测项、human加补全上下文要求。

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
