# PRD：单条大纲 AI 润色 + AI 生成起草

## Goal

编辑大纲弹窗支持 **AI 润色**（基于当前大纲内容改写），手动创建弹窗支持 **AI 起草**（AI 根据项目上下文先起草一条大纲）。AI 结果**只填入表单，不直接入库**，由用户确认/修改后再保存。

## 背景（代码事实，2026-08-08 核实）

- 编辑弹窗（`Outline.tsx` 313 行起）：`modalApi.confirm` 内嵌 `editForm`，字段：标题、内容、涉及角色、涉及组织、场景信息、情节要点、情感基调、叙事目标。纯手动，无任何 AI 能力。
- 手动创建弹窗：`manualCreateForm`，字段：大纲序号、大纲标题、大纲内容。
- 后端大纲接口只有：增删改查、展开、整卷生成/续写（SSE+后台+多模型比较）。**无单条大纲的 AI 编辑接口**。
- 可复用基建：`PromptService.get_template`（系统默认模板 + 用户可覆盖）、`_build_outline_continue_context`（项目信息+角色+最近大纲上下文构造）、`generate_text`（非流式，支持 system_prompt）、子任务 2 的 `build_skill_system_prompt`、子任务 1 的 AIServiceSelector。
- 参考：`api/polish.py`（AI 去味，普通 POST 一次性返回，不入库），模式可借鉴。

## Requirements

1. **编辑弹窗 AI 润色**：
   - 表单底部加「🤖 AI 润色」操作区：润色方向输入（可选）、「应用 Skill」下拉（可选，复用子任务 2 组件逻辑）、模型选择（复用 AIServiceSelector，服务商→模型两级，与全局一致）、润色按钮。
   - 后端新接口 `POST /api/outlines/{outline_id}/ai-edit`：加载该大纲 + 项目上下文（项目信息、角色、前后各若干条大纲），构造提示词（模板 OUTLINE_AI_EDIT，系统默认注册、允许用户模板覆盖），可选注入 SKILL，调用 `generate_text`，返回 `{title, content}` 建议。**不入库**。
   - 前端收到结果后 `setFieldsValue` 填入标题/内容，提示用户"已填入，请确认后再保存"。
2. **手动创建弹窗 AI 起草**：
   - 表单底部加「🤖 AI 起草」操作区：起草要求输入（可选）、Skill 下拉（可选）、模型选择（同润色）、起草按钮。
   - 后端新接口 `POST /api/outlines/ai-draft`：项目上下文 + 指定插入位置的前后大纲，构造提示词（模板 OUTLINE_AI_DRAFT），返回 `{order_index, title, content}` 建议。**不入库**。
   - 前端填入表单（序号、标题、内容），用户确认后再点「创建」。
3. 两个接口的请求体均含：`skill_key`、`provider_config_id`、`model`（均可选，不选走默认路由）。
4. 未选模型/未选 SKILL 时行为 = 默认模型标准流程。

## Acceptance Criteria

- [ ] 编辑弹窗可对单条大纲执行 AI 润色；结果填入表单（标题/内容），**点「更新」后才入库**（直接验证 DB 无写入）。
- [ ] 手动创建弹窗可 AI 起草；结果可修改，点「创建」才入库。
- [ ] 润色/起草带 SKILL 时后端日志出现「已将 Skill」注入记录；不带时无注入。
- [ ] 润色/起草使用未选模型时走后端默认路由，接口正常返回。
- [ ] 两个新模板（OUTLINE_AI_EDIT / OUTLINE_AI_DRAFT）注册进模板体系（模板管理页可见）。
- [ ] 前端 typecheck/build 通过。
