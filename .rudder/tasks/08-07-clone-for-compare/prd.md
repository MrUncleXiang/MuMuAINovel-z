# PRD：同设定双模型对比创作（后端复制服务）

> 任务：08-07-clone-for-compare（P1）
> 状态：planning

## 目标

用户想比较两个模型（如 deepseek 和 mimo）写同一本书谁写得好。
系统创建两本书：**书 A 配模型 1、书 B 配模型 2**，两本书的**内容设定完全相同**，各自独立推进（写章节/分析/更新角色状态互不影响），用户对照阅读同一章节决定用哪本。

## 复制内容（从源书 → 新书）

| 数据 | 表/字段 | 是否复制 |
|---|---|---|
| 书名/简介/主题/类型 | projects.title/description/theme/genre | ✅ |
| 世界观（时代/地点/氛围/规则） | projects.world_* | ✅ |
| 叙事视角/目标字数/大纲模式 | projects.narrative_perspective 等 | ✅ |
| 角色 | characters（name/age/gender/role_type/personality/background/appearance/relationships） | ✅（新 id） |
| 角色关系 | character_relationships（按角色名映射） | ✅（新 id） |
| 组织 | organizations（含 parent 层级） | ✅（新 id） |
| 组织成员 | organization_members | ✅（新 id） |
| 大纲（含 structure） | outlines（title/content/structure/order_index） | ✅（新 id） |
| 章节标题 | chapters.title（作为骨架，正文为空） | ✅（仅标题骨架） |

**不复制**：正文内容、伏笔（foreshadows）、记忆（story_memories）、分析结果（plot_analysis）、生成历史——这些是"写出来的过程数据"，对比书从同一起点开始写。

## API

`POST /api/projects/{source_project_id}/clone-for-compare`
- 请求体：`{ "title_suffix": "（-模型名）", "model": "deepseek-v4-flash", "provider_config_id": "..." }`
- 动作：
  1. 校验源书属于当前用户
  2. 按上表复制设定到新书（新 id 全部重新生成，角色/关系/组织用名称映射关联）
  3. 新书标记 `wizard_status=completed`（避免被拉回向导页）
  4. 返回新书 id
- 幂等性：不自动启动流水线（由调用方决定何时启动哪本书）

## 复用

- `backend/scripts/make_test_book.py` 的 `copy_materials_from()` 已有复制逻辑（角色/关系/组织/大纲），提取为共享服务 `app/services/project_clone_service.py`
- 流水线启动已有 `POST /api/pipelines/start`（前端分别对两本书调用即可实现并行）

## 验收

1. 对《暗潮香江》调用 clone-for-compare → 新书设定完整（世界观/93角色/253关系/30组织/42大纲）
2. 新书无正文/伏笔/记忆/分析
3. 新书可正常启动流水线（不报缺参数/不跳向导）
4. 两本书并行跑时互不影响（各自的角色状态/伏笔独立）
