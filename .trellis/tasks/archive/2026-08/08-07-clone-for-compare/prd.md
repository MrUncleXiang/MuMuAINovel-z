# PRD：同设定双模型对比创作（后端复制服务）

> **已冻结，禁止实施。** 本文只保留为历史决策证据。其“只复制静态设定、清空全部过程数据”的规则不能满足可选继承和完整续写，后续由 `08-07-compare-state-snapshots`、`08-07-compare-project-clone` 替代。

> 任务：08-07-clone-for-compare（P1）
> 状态：planning

## 目标与边界

源书只作为设定模板，不直接参与模型对比。调用方从同一本源书分别创建对比书 A、B，再为 A、B 启动不同模型的流水线。这样即使源书已经写过正文，两本对比书仍从同一个干净起点开始。

本任务只负责复制一本书，不保存模型配置、不启动流水线。模型、章节数和双书启动编排由 `08-07-compare-ui` 负责。

## 复制规则

### 项目

复制：`title`（追加后缀）、`description`、`theme`、`genre`、`target_words`、`outline_mode`、世界观 4 字段、`chapter_count`、`narrative_perspective`、`character_count`。

新书固定初始化：`current_words=0`、`status=planning`、`wizard_status=completed`、`wizard_step=4`；封面和生成过程字段不复制。

### 角色和组织

- 角色生成新 UUID；复制人物/组织的静态设定字段，包括名称、年龄、性别、类型、性格、背景、外貌、组织属性、头像和 traits。
- 不复制章节推进产生的 `current_state`、`state_updated_chapter`、`status_changed_chapter` 和职业进度；新角色状态初始化为 `active`。
- 维护明确的“旧角色 ID → 新角色 ID”映射，禁止按名称关联。
- 角色关系使用角色 ID 映射重建，并复制关系类型、名称、亲密度、状态、描述和时间线字段。
- 组织先创建无父级记录，再用“旧组织 ID → 新组织 ID”映射回填 `parent_org_id`。
- 组织成员同时使用组织和角色的 ID 映射重建，保留职位、等级、状态、时间、忠诚度、贡献度、来源和备注。

### 大纲和章节骨架

- 大纲生成新 UUID，复制 `title/content/structure/order_index`，维护“旧大纲 ID → 新大纲 ID”映射。
- 章节生成新 UUID，复制 `chapter_number/title/sub_index/expansion_plan`，并用大纲映射重建 `outline_id`。
- 章节过程数据清空：`content=NULL`、`summary=NULL`、`word_count=0`、`status=draft`。

### 明确不复制

正文、摘要、伏笔、故事记忆、剧情分析、生成历史、AI 调用记录、后台任务、流水线及检查点、封面生成状态。这些都是创作过程数据。

## API 契约

`POST /api/projects/{source_project_id}/clone-for-compare`

请求体：

```json
{ "title_suffix": "（模型 A）" }
```

规则：

1. 登录用户必须拥有源书，否则返回 `404`；未登录返回 `401`。
2. `title_suffix` 去除首尾空格后长度为 1-80；非法返回 `422`。
3. 源书必须具备项目 4 字段、世界观 4 字段、至少 1 个角色和 1 个大纲；不完整返回 `422`，错误说明缺少什么。
4. 整个复制在一个数据库事务内完成；任一步失败全部回滚，不留下半本书。
5. 接口是**非幂等**创建操作：每次成功调用都会创建一本新书。前端必须在请求期间禁用重复提交。

成功返回 `201`：

```json
{
  "project_id": "uuid",
  "title": "源书名（模型 A）",
  "counts": {
    "characters": 93,
    "relationships": 253,
    "organizations": 30,
    "organization_members": 80,
    "outlines": 42,
    "chapters": 42
  }
}
```

## 实现约束

- 新建 `app/services/project_clone_service.py`，使用 async SQLAlchemy；API 层只负责鉴权、校验错误转换和响应。
- 不直接提取 `backend/scripts/make_test_book.py` 的 SQL。该脚本没有复制组织、组织成员或章节，且按名称映射，只能作为历史参考。
- 服务返回前刷新新项目；日志只记录源/目标项目 ID 和数量，不记录小说正文。

## 验收

1. 用测试夹具创建含重名角色、父子组织和章节骨架的完整源书，复制后各表数量相同，所有外键指向新书数据。
2. 新章节保留编号、标题、大纲关联、子序号和展开计划，但正文、摘要、字数和状态已重置。
3. 新书没有伏笔、记忆、分析、生成历史或流水线数据，且能正常启动流水线、不跳回向导。
4. 故意让复制中途失败，事务回滚后项目及所有子表均无残留。
5. 其他用户访问返回 `404`；缺世界观/角色/大纲返回可读的 `422`。
6. PostgreSQL 为主要验收环境；服务级测试同时覆盖 SQLite。
