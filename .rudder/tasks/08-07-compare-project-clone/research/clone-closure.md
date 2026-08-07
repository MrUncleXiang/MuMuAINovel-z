# 项目克隆复制闭包

## 外部接口

克隆模块只暴露一个深接口：输入源项目、用户、新标题、模式和可选检查点，返回新项目与复制计数。调用方不决定复制哪些表，也不传任意截止章节号。

模式：

- `settings_only`：复制书籍元数据、创作配置、默认风格、职业/角色/关系/组织、大纲和章节骨架；正文及过程状态为空。
- `inherit_checkpoint`：必须提供源项目的有效检查点 ID；复制第 1～X 章正文和该检查点证明的项目状态。

## 关系数据库复制顺序

1. `projects`
2. `project_creation_configs`、`project_default_styles`
3. `outlines`、`chapters`
4. `careers`、`characters`、`character_careers`
5. `character_relationships`、`organizations`、`organization_members`
6. 继承模式：`analysis_tasks`、`plot_analysis`、`story_memories`、`foreshadows`、`generation_history`
7. 继承模式：`project_state_checkpoints`
8. `novel_pipelines`，固定为空闲状态，不复制源运行锁、错误、预算和检查点决策

不复制：后台任务、批量任务、重写任务、AI 调用日志、LLM 候选批次、Pipeline 运行检查点、API Key、MCP/Skill/模型/风格的用户级定义。

## ID 和 JSON 重映射

必须新建并重映射：项目、大纲、章节、职业、角色、角色职业、关系、组织、组织成员、分析任务、分析、记忆、伏笔、历史和状态检查点 ID。

需要递归处理的 JSON/Text JSON：

- `characters.relationships`、`characters.organization_members`、`characters.sub_careers`
- `outlines.structure`、`chapters.expansion_plan`
- `plot_analysis.character_states` 及其他分析 JSON
- `story_memories.related_characters`、`foreshadow_resolved_at`
- `foreshadows.source_memory_id`、`related_foreshadow_ids` 和章节引用
- 每个 `project_state_checkpoints.state_json`

字符串值只有在完全等于源 ID 时才替换，普通正文中的相似文本不做字符串替换。

## 两种状态来源

`settings_only` 使用源书当前记录的静态字段，但重置会随章节推进变化的字段：正文、摘要、字数、章节状态、角色心理/存活变化、关系结束状态、组织进度、职业进度和伏笔过程状态。

`inherit_checkpoint` 不读取源书当前角色等状态，而读取所选第 X 章检查点的 `state_json`。这样源书已推进到第 30 章时，继承第 10 章不会带入第 11～30 章的状态。

## 原子性与向量补偿

关系数据在一个事务内写入。继承模式把目标 `story_memories` 重新编码到目标项目自己的 Chroma collection，`vector_id` 使用新记忆 ID。向量写入不足、数据库提交失败或其他异常时回滚数据库，并删除目标 collection；绝不删除或修改源 collection。

## 验证不变量

- 目标项目与所有书内可写记录使用新 ID。
- 目标外键只指向目标项目闭包或用户级只读选择资源。
- 目标数据中不存在源项目 ID；已知书内源 ID 不残留在结构化 JSON。
- 第 X+1 章为空，且前置检查能识别第 X 章分析已完成。
- 修改或删除源书/副本任一方，不改变另一方关系数据和向量集合。
