# 沉淀接手体检清单（教训：trellis在用但真相源缺失）

## Goal

教训：长期使用 trellis 但从未审查其完整性，导致 llms.txt/Docs/CONTEXT.md 缺失、AGENTS.md 引用不存在的文件、spec 13个占位未被发现。落地：新增 .trellis/spec/guides/onboarding-checklist.md（接手/新AI接入/新模板出现时的完整性体检清单），并在 guides/index.md 登记。

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
