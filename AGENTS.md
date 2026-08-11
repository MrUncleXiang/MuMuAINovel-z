<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

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

---

# 项目速览（真相源入口）

MuMuAINovel：AI 辅助中文网文创作平台（大纲→展开→生成→审查→分析的状态化创作管线）。

## 目录速览

| 路径 | 职责 |
|---|---|
| `backend/app/api/` | FastAPI 路由（projects/outlines/chapters/foreshadows/tasks 等） |
| `backend/app/services/` | 核心业务：ai_provider 路由、chapter_review（审查）、chapter_analysis_materialization（分析物化）、memory（向量记忆）、background_task（任务队列） |
| `backend/app/models/` | SQLAlchemy 模型（42 张表） |
| `backend/app/skills/` | 正文写作/审稿 SKILL 包（proofread/aidetect/human/review/continuity 等） |
| `frontend/src/pages/` | 页面（大纲/章节/剧情分析/伏笔/审查配置/流水线等） |
| `frontend/src/components/` | 组件（AI 修改 diff、卷检查弹窗、审查报告弹窗、多模型对比） |
| `Docs/` | 架构真相源（architecture.md + adr/） |
| `.trellis/` | 任务治理 + spec 规范 |

## 构建 / 测试 / 检查入口

- 后端启动：`docker compose up -d`（容器 mumuainovel；alembic 迁移自动执行）
- 数据库迁移：`alembic upgrade head`（backend/ 下，postgres 迁移在 `alembic/postgres/versions/`）
- 前端构建：`cd frontend && npm run build`（产物 `backend/static/`；内存不足时 `NODE_OPTIONS=--max-old-space-size=4096`）
- 前端部署：`docker cp backend/static/. mumuainovel:/app/static/ && docker restart mumuainovel`
- 后端代码更新部署：`docker cp backend/app mumuainovel:/app/ && docker restart mumuainovel`
- 提交前检查（pre-commit 自动）：pyflakes 未定义名称 / Python 语法 / 前端 TS 类型

## 架构红线（详见 Docs/architecture.md）

1. 生成/分析必须在后台任务执行（返回 task_id，前端轮询），禁止请求内同步调 AI。
2. 后台任务函数签名 `(task_id, user_id)`，session/ai_service/tracker 内部自建。
3. 正文变更走 content_hash 校验，过期分析结果一律丢弃。
4. 顺序：展开→生成→审查（定稿）→分析→后续章；审查必须先于分析。
5. AI 请求必须带浏览器 UA（Cloudflare 按 UA 指纹拦截，见 .trellis/spec/backend/ai-provider-integration.md）。
6. 不要直接改数据库；结构变更走 alembic，配置走设置 UI。
7. AI 修改一律"流式生成 → diff 确认 → 应用"。
