# PRD：大纲生成接入 SKILL（单选，三条路径确保生效）

## Goal

大纲生成支持选择 SKILL 并**真正生效**：UI 选择 → 后端注入系统提示词 → 覆盖全部生成路径。本期单选 SKILL（多技能已决策暂缓）。

## 背景（代码事实，2026-08-08 核实）

- 章节生成的 SKILL 注入已验证可行：`chapters.py` 1440-1463 行，`skill_key` → `get_all_skills_cached()` 找到技能 → 全文拼成「⚡ Skill 工作流：{name}」系统提示词 → 传入 `generate_text_stream(system_prompt=...)`（`ai_service.py` 支持 system_prompt 参数）。
- 大纲生成**无任何 skill 代码**：
  - `schemas/outline.py` `OutlineGenerateRequest` 无 `skill_key` 字段；
  - `api/outlines.py` 三条路径（SSE 流式 `new_outline_generator`/`continue_outline_generator`、后台任务 `_run_new_outline_bg`/`_run_continue_outline_bg`、多模型比较走 `services/outline_comparison_service.py`）调用 `generate_text_stream` 时均未传 `system_prompt`。
- 前端：`Chapters.tsx` 有现成「应用 Skill」下拉（`/api/skills/list` + 选中后显示描述），大纲弹窗（`Outline.tsx`）没有。
- 多模型比较：`OutlineComparisonCreateRequest` **继承** `OutlineGenerateRequest`（顶层加字段即自动支持）；`LLMMultiSelector` 的 selection 结构 `{provider_config_id, model}` 不含 skill_key，与章节页不同（章节页每个候选可单独选 skill）。

## SKILL 适用性分析（已核实 41 个 SKILL 内容）

| 候选 | 结论 |
|---|---|
| `outline`（Skill·大纲规划） | **推荐**。纯大纲方法论：全书主线→卷纲→章纲三层结构、伏笔总表、爽点节奏、平台节奏参考库（references/），与大纲生成场景直接对口 |
| `continuity`（Skill·大纲规划） | 连贯性**检查**型技能（核对档案/时间线），适合事后质检，不适合生成时注入；可在后续「AI 编辑」场景考虑 |
| `story-long-write` | **不推荐作默认**。定位是"从零开书总教练"（选题→设定→大纲→正文全流程），范围过大，注入大纲生成会稀释指令 |
| 其余 38 个 | 正文写作/人设爽点/审稿诊断/设定类，与大纲生成无直接关系，但作为自由选择项保留（用户可自行尝试） |

结论：**本期实现通用 SKILL 选择（任何 SKILL 可选），UI 上把 `outline` 排第一并标注"推荐"**。前端不做白名单过滤。

## Requirements

1. 后端 `OutlineGenerateRequest` 加 `skill_key: Optional[str]`（`OutlineComparisonCreateRequest` 自动继承，比较模式下所有候选共享同一 SKILL）。
2. `skill_loader.py` 抽公共函数 `build_skill_system_prompt(skill_key) -> Optional[str]`（复用章节已验证的注入格式），供大纲三条路径调用；`chapters.py` 改为调用该公共函数（消除重复，行为不变）。
3. 三条生成路径全部注入：
   - SSE 流式（`new_outline_generator` / `continue_outline_generator`）
   - 后台任务（`_run_new_outline_bg` / `_run_continue_outline_bg`）
   - 多模型比较（`outline_comparison_service.generate_outline_candidate`）
4. 前端大纲生成弹窗加「应用 Skill」下拉（`/api/skills/list`），单模型/多模型比较两种模式都显示，选中后展示该 SKILL 描述；提交时带 `skill_key`。
5. 不选 SKILL = 现状（不注入）。

## Acceptance Criteria

- [ ] `/api/skills/list` 可见全部 SKILL；`outline` 排第一（或带"推荐"标注）。
- [ ] 单模型模式选择 SKILL 后生成：后端日志出现「已将 Skill '大纲设计' 注入系统提示词」。
- [ ] 后台任务模式（断线续跑）同样有注入日志。
- [ ] 多模型比较模式：每个候选生成都注入同一 SKILL（日志可查）。
- [ ] 未选 SKILL 时无注入日志，行为与现状一致。
- [ ] 注入 SKILL 后生成的大纲仍能按原 JSON 结构入库（实测：输出可被 `_parse_ai_response` 解析）。
- [ ] 前端 typecheck/build 通过。

## 风险

- **格式冲突**：`outline` SKILL 输出为 Markdown 方法论，而 OUTLINE_CREATE 模板要求 JSON 数组。缓解：SKILL 以系统提示词注入（方法论指导），JSON 格式要求保留在用户提示词（现有模板）中，与章节做法一致；若实测被带偏，在注入头追加一句"输出必须严格遵守系统要求的 JSON 结构"。
- **上下文膨胀**：SKILL 全文（含 references 附录）注入会增大 token 消耗，接受（与章节一致）。
