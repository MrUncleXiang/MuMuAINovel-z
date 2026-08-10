# 编辑弹窗AI对话修改（指令驱动+最小修改+diff确认）

## Goal

编辑正文弹窗新增「AI修改」对话区：用户输入自然语言指令（如'把开头改紧张'），AI读全文只改指令涉及段落（其余一字不动），SSE流式返回，前端diff对比确认应用，可连续对话迭代。不做对话历史持久化。后端新接口+提示词模板，前端复用模型/Skill选择与diff组件。

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
