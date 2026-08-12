# 大纲续写方向 AI 抉择（灵感模式式对话）

## Goal

在「AI生成/续写大纲」弹窗中，新增灵感模式式的对话抉择区：AI 基于项目已有大纲/角色/世界观，生成多方向续写建议，用户通过多轮点选/反馈确认方向，最终**采纳后 AI 自动填入方向并直接启动续写**。

## Background（现状事实）

- 续写弹窗中「故事发展方向」是空输入框，需用户手填；留空后端默认"自然延续"（无信息量）。
- 后端续写 prompt（`_build_outline_continue_context`）已包含：项目信息 + 最近10卷大纲 structure + 全部角色 + 用户输入。AI 具备分析续写方向的能力，但界面未暴露。
- 灵感模式（`frontend/src/pages/Inspiration.tsx` + `backend/app/api/inspiration.py`）已有成熟机制：
  - `POST /api/inspiration/generate-options`：按 step 用不同模板生成 `{prompt, options: string[]}`，带自动重试与格式校验（3~10 个选项）。
  - 前端：AI 消息带 `options` 渲染为可点击卡片（hover 动画、选中后 disabled），支持多轮、反馈优化（TextArea 输入调整选项）、确认按钮。
- 现有"不入库建议"模式先例：`POST /outlines/{outline_id}/expand-advice`（AI 建议不入库，展示供采纳），支持 Skill 注入（`build_skill_system_prompt`）。
- 续写执行：前端 `handleGenerate(values)` → `generateOutlineBackground(requestData)`（后台任务，含 `story_direction`、`chapter_count`、`narrative_perspective`、`mode: 'continue'` 等）。

## Requirements（已与用户确认）

1. 入口：续写弹窗内嵌「✨ AI 建议发展方向」对话区，不跳转新页面。
2. **动态对话多轮（轮数不锁死）**：AI 每轮给"发展方向/落点"选项（标题+解释），用户点选后可继续深入；每轮选项下方提供**反馈输入框**（用户可打字调整方向，AI 按反馈重新给选项）；用户认为方向 OK 时**随时**点「采纳此方向」结束对话。
3. 选项形式：**选项标题 + 一段解释**（点选时解释一起带上），便于用户理解每个方向的含义。
4. 采纳后动作：确认的方向文字**自动填入「故事发展方向」输入框**，并**直接触发续写**（复用现有 handleGenerate 后台任务），用户无需再点"开始续写"。
5. 选项卡片交互沿用灵感模式风格（可点击卡片、hover 效果、选中后禁用）。
6. AI 建议**不入库**（复用 expand-advice 模式），只有最终确认才执行续写。
7. **LLM 一致性**：对话区建议生成使用弹窗中「本次使用的AI服务」选定的 provider_config_id + model（与续写同一模型，不另设选择器）。

## Technical Approach

### 后端（backend/app/api/outlines.py + prompt 模板）
新增 `POST /outlines/continue-advice`（不入库建议）：
- 请求：`project_id`、`context`（上一轮选择的选项/方向文字，可空）、可选 `feedback`（用户反馈文字，重新生成选项时携带）、`skill_key`、`provider_config_id`、`model`、`instruction`。
  - 无 context = 第1轮方向生成；有 context 无 feedback = 基于所选方向深入（落点）；有 feedback = 按反馈重新生成。**不设固定轮数**，由前端对话状态驱动。
- 响应：`{ prompt: str, options: [{ title: str, description: str }, ...] }`（JSON，3~4 条，标题≤20字、解释≤200字；参考灵感模式 validate_options_response 做格式校验与重试）。
- 上下文：复用 `_build_outline_continue_context` 的项目/大纲/角色信息 + 上一轮选项 + 用户反馈。
- 新增 PromptService 模板：`OUTLINE_CONTINUE_ADVICE`（统一模板，按 context/feedback 字段决定输出侧重；不建多套模板），存模板表（参照现有 OUTLINE_EXPAND_ADVICE 模板注册方式）。
- Skill 注入：`build_skill_system_prompt(payload.skill_key)`（与 expand-advice 一致）。

### 前端（frontend/src/pages/Outline.tsx）
1. 弹窗（showGenerateModal 的 content）中「故事发展方向」Form.Item 下方新增对话区容器：
   - 折叠面板/按钮「✨ AI 建议发展方向」→ 展开对话区。
   - 对话区：AI prompt 气泡 + 选项卡片列表（沿用灵感模式 Card 样式），点选后请求下一轮（`continue-advice`，携带 context）。
   - 每轮选项下方提供反馈输入框 + 「采纳此方向」确认按钮。
2. 采纳处理：`generateForm.setFieldsValue({ story_direction: 最终方向文字 })` → 校验表单 → 直接调 `handleGenerate(values)`（与"开始续写"按钮同逻辑，包含多模型比较分支）。
3. 对话区状态管理：本地 state（方向对话消息列表、loading、已禁用选项），不持久化（弹窗关闭即重置）。
4. 选项内容为 `{title, description}`：卡片显示标题（加粗）+ 描述（小字灰色）。
5. API 封装：`outlineApi.getContinueAdvice(data)`（services/api.ts）。

### 复用与不动
- 不动灵感模式页面/接口。
- 不动现有续写后台任务链路（handleGenerate / generateOutlineBackground / _build_outline_continue_context）。
- 不动大纲总览页（本次改动与上一任务独立）。

## Acceptance Criteria

- [ ] 续写弹窗（有已有大纲时）出现「✨ AI 建议发展方向」入口，点击展开对话区。
- [ ] AI 基于当前项目大纲/角色/世界观返回 3~4 个方向选项（标题+解释），选项格式错误时自动重试。
- [ ] 点选选项后可继续深入（轮数不限）；任意轮均可通过反馈输入框打字让 AI 重新生成选项。
- [ ] 任意轮出现「采纳此方向」确认；采纳后自动填入「故事发展方向」输入框并直接启动续写后台任务（无需再点开始续写）。
- [ ] 对话区建议使用弹窗「本次使用的AI服务」选定的 provider+model；切换后建议与续写一致。
- [ ] 对话中选项选中后禁用，AI 响应期间有 loading，不可重复提交。
- [ ] 建议不入库；刷新/关闭弹窗后对话区重置。
- [ ] 多模型比较模式（generation_mode=compare）下采纳后走 handleGenerateComparison 分支。
- [ ] 前端 tsc + build 通过；后端语法检查通过；部署后接口实测返回结构正确。

## Notes

- 数据完整性：此功能不建书、不改数据，只新增"建议"接口与 UI，无数据完整性风险。
- 选项格式校验参考 `inspiration.py` 的 `validate_options_response`（数量、类型、长度、重试）。
- 后端新增接口需保持与现有 `create_routed_ai_service` 用法一致（usage_type="outline"）。
