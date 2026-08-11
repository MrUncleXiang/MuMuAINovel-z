# AI请求被Cloudflare按UA指纹拦截导致分析间歇失败

## Goal

章节分析间歇性失败（6次尝试：空响应/截断/无效JSON/524）。排查：非模型问题——OpenCode Go 的 Cloudflare 拦截无UA/编程客户端UA请求（403 code 1010）。修复：httpx client 统一带浏览器UA。验证：flash 连续3次分析成功。模型路由恢复原配置。附带：分析失败提示友好化+伏笔设计内跳过不再误判。

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
