<!-- RUDDER:START -->
# Rudder Instructions

These instructions are for AI assistants working in this project.

This project is managed by Rudder. The working knowledge you need lives under `.rudder/`:

- `.rudder/workflow.md` — development phases, when to create tasks, skill routing
- `.rudder/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.rudder/workspace/` — per-developer journals and session traces
- `.rudder/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Rudder command is available on your platform (e.g. `/rudder:finish-work`, `/rudder:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Rudder skills
- `.codex/agents/` — optional custom subagents

Managed by Rudder. Edits outside this block are preserved; edits inside may be overwritten by a future `rudder update`.

<!-- RUDDER:END -->

<!-- MATT-SKILLS:START -->
# 工作流分工约定（Wayfinder / Grilling × Rudder）

本项目同时配备两套工具，按下面的规则路由，不要混用：

- **Matt Pocock 技能包**（规划/澄清层）：`/wayfinder`（大项目导航）、`/grilling`（追问澄清）、`/research`、`/prototype` 等，装在 `~/.agents/skills/`
- **Rudder**（执行/记忆层）：任务、spec、workspace 记忆，命令形如 `python3 ./.rudder/scripts/task.py create`，hooks 自动注入上下文

## 什么时候用什么

1. **超级大项目 / 路线模糊**（跨多个会话、一次想不清楚怎么走）→ 先用 `/wayfinder` 画决策地图，走完地图再开工。
2. **单个功能需求模糊** → 用 Rudder 自带的 brainstorm（等价于 grilling 的一问一答），产出 `prd.md` 后再进入 implement。
3. **需求已清楚的日常开发** → 直接走 Rudder 标准流程：建任务 → implement → check。

## wayfinder 与 Rudder 的衔接

wayfinder 地图走完后：

- 每张已解决的决策票 → 用 `python3 ./.rudder/scripts/task.py create "<票名>"` 建成 Rudder 任务，让 Rudder 接管后续记忆与执行。
- 地图产生的规格/设计结论 → 落盘到 `.rudder/spec/` 对应位置，不要只留在聊天记录里。

## 硬规则

- 需求未澄清前不要直接动手写代码（除非用户明确要求）。
- 不要为单个小改动启动 wayfinder；wayfinder 只用于跨会话的大项目。
- **开工前必查**：问"开始吗？"之前，先回答三个问题——
  ① 这是新功能/多模块改动吗？② Rudder 任务建了吗？③ prd.md 写了吗？
  任一为否，先补，再问开工。
- **任务登记判定标准**：
  - 涉及"新数据表/新接口/新页面/跨 2 个以上模块/行为变化"的改动 → 必须 `task.py create` 建任务 + 写 prd.md（含验收标准），认领后再实施。
  - 纯 bug 修复、单点配置调整、文案/样式微调 → 可以简化，但改动要在会话记录/日志里写明。
  - 承诺"写进规范/记入文档"必须当轮执行完并提交，不能只口头承诺。
- **需求讨论要具体**：用大白话描述改动（例：写"复制目标书籍的世界观、角色、关系、组织、大纲到新书"，不写"复制设定"这类模糊词）；UI 改动尽量沿用现有组件风格。
<!-- MATT-SKILLS:END -->

## 建书数据完整性（必读）

创建项目、一键开书、建测试/演示/对比数据时，必须保证一本书的"完整设定"齐全：**项目 4 字段（含简介）、世界观 4 字段、角色、大纲**；对比测试必须完整复制原版设定（世界观+角色+大纲+标题），否则对比不公平。详见 `.rudder/spec/guides/pipeline-data-integrity-guide.md`。

## Agent skills

### Issue tracker

问题/规格（PRD）以 markdown 文件存放在 `.scratch/<功能名>/` 下，不用 GitHub Issues。参见 `docs/agents/issue-tracker.md`。

### Triage labels

五个分类角色，标签串与角色同名：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。参见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文布局：仓库根目录一个 `CONTEXT.md` + `docs/adr/`。参见 `docs/agents/domain.md`。
