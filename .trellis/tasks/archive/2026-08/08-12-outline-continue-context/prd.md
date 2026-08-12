# 大纲续写方向 AI 上下文增强（分层注入 + 关系注入）

## Goal

增强 `POST /outlines/continue-advice` 接口的上下文质量，从"每卷截断 120 字 content + 无关系"升级为"最近 3 卷解析 structure 完整注入 + 更早卷一行速览 + 全量关系"，让 AI 方向建议更贴合故事情节和人物网络。

## Background（现状事实）

当前 `outline_continue_advice` 接口的上下文构建（`backend/app/api/outlines.py` 2331 行附近）：

| 类别 | 当前做法 | 问题 |
|---|---|---|
| 大纲 | `_build_outlines_brief`：每卷取 content 前 120 字 | 只看到"开头"，卷尾高潮/转折信息丢失；未利用 structure 的结构化字段（summary/key_points/goal/emotion/scenes） |
| 关系 | ❌ 无 | AI 不知道人物关系网（续写方向的核心参考） |
| 组织 | ❌ 无 | 组织信息未注入 |

数据库实际数据（《替死者言》实测）：
- 每卷 content ≈ 400 字，structure ≈ 800+ 字（含 summary、key_points、scenes、characters、emotion、goal）
- 关系表 5 条，单条描述 30~200 字，带时间线标记（`[第1章]`）
- 项目有 6 个角色，3 卷大纲

## Requirements（已与用户讨论确认）

1. **大纲分层注入**：最近 3 卷（`outlines[-3:]`，按 order_index 升序后取末尾）→ 解析 structure 完整注入（summary + key_points + scenes 前 2 个 + goal + emotion + 重点角色/组织）；更早卷（`outlines[:-3]`）→ 一行速览（标题 + goal 或 summary 前 80 字）。
2. **关系全量注入**：查询 `CharacterRelationship` 表全量（不按卷过滤），格式：`角色A ↔ 角色B：关系名（亲密度N），描述前 100 字`。无关系数据时优雅降级为"（无记录的关系）"。
3. **续写执行端不动**（审查发现）：`_build_outline_continue_context` 已把关系网络挂在每个角色下（"关系网络：与X：关系名"），并已有完整 structure 解析（summary/key_points/emotion/goal/scenes/角色/组织/职业/组织成员）。无需改动。
4. **复用现成解析**：提取续写端已有的 structure 解析逻辑为通用 helper，建议接口与续写接口共用，不重复实现。
5. **token 预算**：近 3 卷 detail ≤ 约 700 字/卷（scenes 取前 2 个）；older 每卷 ≤ 80 字；关系描述 ≤ 100 字/条；总注入 ≤ 约 4000 字（轻量模型防截断）。
6. prompt 模板 `OUTLINE_CONTINUE_ADVICE` 与 `OUTLINE_CONTINUE` 适配新参数，并同步 `get_all_system_templates()` 注册表 parameters。
7. 已展开的章节数信息**暂不注入**（过度设计，可后续加）。

## Technical Approach

### 后端（backend/app/api/outlines.py）

0. **提取通用 structure 解析 helper `_build_outline_structure_text(outline)`**：
   - 解析 structure JSON，输出 summary/key_points/重点角色/涉及组织（复用 `_build_outline_continue_context` 现有内联逻辑，提取为公共函数）

1. **新增 helper `_build_outlines_detail(outlines, max_scenes=2)`**（最近卷完整注入）：
   - 对每卷解析 structure，输出：
     ```
     【第N卷《标题》】
     概要：{summary}
     要点：{key_points 逗号连接}
     重点角色：{characters}
     涉及组织：{organizations}
     场景：{scenes 前 2 个}
     目标：{goal}
     情感：{emotion}
     ```
   - structure 为空/解析失败时 fallback 到 `content[:200]`

2. **新增 helper `_build_outlines_older_brief(outlines, max_per=80)`**（更早卷速览）：
   - 每卷一行：`第N卷《标题》——{goal 或 summary 前 80 字}`

3. **新增 helper `_build_relationships_info(project_id, db)`**：
   - 查询 CharacterRelationship，join characters 两次取 from/to 名称
   - 每条约 100 字：`{A} ↔ {B}：{关系名}（亲密度{intimacy_level}），{描述前100字}`
   - 无数据返回"（无记录的关系）"

4. **修改 `outline_continue_advice`（2331 行附近）**：
   - `outlines_brief=_build_outlines_brief(outlines)` → `outlines_detail=_build_outlines_detail(outlines[-3:])` + `older_outlines=_build_outlines_older_brief(outlines[:-3])`
   - 新增 `relationships_info=_build_relationships_info(payload.project_id, db)`

5. **修改 `_build_outline_continue_context`**：**不修改**（审查确认已含关系网络 + 完整 structure 解析）

### prompt 模板（backend/app/services/prompt_service.py）

更新 `OUTLINE_CONTINUE_ADVICE`：占位符 `{outlines_brief}` → `{outlines_detail}`（最近 3 卷）+ `{older_outlines}`（更早卷速览），新增 `<relationships>` 块。同步 `get_all_system_templates()` 注册表 parameters。

更新 `OUTLINE_CONTINUE`（续写执行模板）：新增 `<relationships>` 块（`{relationships_info}`），同步注册表 parameters。

### 涉及模型
- `Outline`、`Character`：已有
- `CharacterRelationship`：新增 join 查询

### 不动
- 不新增接口路由（同一个 `/outlines/continue-advice`）
- 不改变前端（只改上下文注入质量）
- 不影响灵感模式、expand-advice、大纲总览等功能

## Acceptance Criteria

- [ ] 最近 3 卷（`outlines[-3:]`）以 structure 概要（summary + key_points + goal + emotion + scenes 前 2）注入 prompt；3 卷以内全部走 detail
- [ ] 更早卷（`outlines[:-3]`）以一行速览注入（≤80 字/卷），不丢失但低占用
- [ ] 关系全量注入（角色对 + 关系名 + 亲密度 + 描述≤100字），无关系时优雅降级
- [ ] 续写执行端 `_build_outline_continue_context` **无需改动**（已含关系网络 + structure 解析；验收时确认不回归）
- [ ] **实测验证注入内容**：调用接口时打印/核对 prompt 前 300 字，确认含 structure 字段与关系网络
- [ ] 实测《替死者言》：3 卷全走 detail（`[-3:]`），5 条关系全量注入
- [ ] prompt 总注入 ≤ 约 4000 字，不触发轻量模型截断警告
- [ ] 模板注册表 parameters 已同步（提示词工坊显示正确）
- [ ] 后端语法通过（py_compile）；前端构建不受影响

## Notes

- `outlines` 按 order_index 排序后取 `[-3:]` 取最近 3 卷（不是在取到的列表里按序取），`[:-3]` 取更早卷
- 如果卷数 ≤ 3，全部走 detail，`older_outlines` 为"（无）"
- 关系使用 `character_from_id`/`character_to_id` join characters 取 name
- `_build_characters_info` 已有 character_id → name 映射可复用
- max_per 参数：older outlines 每卷 ≤ 80 字（一行速览）
