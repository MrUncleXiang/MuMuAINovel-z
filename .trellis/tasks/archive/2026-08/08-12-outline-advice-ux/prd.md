# 续写方向对话区交互重构（灵感模式化）

## Goal

重构「AI 方向抉择」对话区交互：解决产出粒度不明确、交互语义混乱、页面膨胀、Skill 不可见四个问题，视觉与交互借鉴灵感模式（对话流 + 点选延深 + 当前轮唯一确认）。

## Background（现状问题，用户反馈）

1. **产出粒度不明确**：AI 把"方向建议"写成章节剧情梗概，用户分不清选项是"一卷"还是"一章"→ 模板未约束产出为卷级大纲规划。
2. **效果一般 / Skill 不可见**：Skill 已随表单传入建议生成，但选择器在"直接续写"Tab，切换后看不见也改不了。
3. **页面膨胀 / 上下文过多**：每轮对话消息全部堆叠展示；后端 context 每轮累积全量历史，轮数多了膨胀。
4. **交互语义混乱**：点选项 = 延深，但画成"已选"高亮；每轮都有"确认此方向"按钮 → 两套语义打架。

## Requirements（已与用户确认 5 点）

1. **模板产出卷级规划**：每条选项 = 一条新卷的规划方向，固定结构（标题 + 这卷讲什么 + 核心冲突 + 推进哪条人物线），不再写大段故事梗概。
2. **对话区顶部加 Skill 选择器**：复用现有 SkillSelector，默认推荐"中文网文大纲设计"，可见可切换，切换后建议生成即用新 Skill。
3. **历史轮折叠 + context 限制 + 轮数上限**：
   - 历史轮折叠成一行（显示 AI 一句话核心，可展开）
   - 前端只传**最近 1~2 轮**选择链给后端（不累积全量历史）
   - 最多 5 轮，达到后提示"建议确认方向或重新开始"
4. **交互语义统一**：点选选项 = 选择并延深（AI 深入下一轮）；每轮只有反馈输入框；「确认此方向」按钮**只在当前轮底部出现（唯一）**；顶部实时显示当前选择链（如"方向：真相的代价 → 落点：以刀代法"）。
5. **视觉参考灵感模式对话流**：AI 气泡 + 选项卡片 + 历史折叠，弹窗加宽加高给对话区空间。

## Technical Approach

### 后端

1. `backend/app/services/prompt_service.py` — `OUTLINE_CONTINUE_ADVICE` 模板：
   - 【任务】明确：产出的是**卷级大纲方向**，不是章节剧情
   - 选项结构约束为固定 JSON：
     ```
     {"title": "卷主题", "description": "这卷讲什么（一句话）", "conflict": "核心冲突", "plotline": "推进哪条人物线"}
     ```
   - 输出要求：description/conflict/plotline 各 ≤ 60 字，拒绝故事梗概
   - 注册表 parameters 同步
2. `backend/app/api/outlines.py` — 接口逻辑基本不动（context/feedback 已支持多轮；由前端控制传最近轮次）。确认后端无状态（本来无状态）。

### 前端（frontend/src/components/OutlineContinueAdvice.tsx 重构）

1. **顶部区**：
   - Skill 选择器（SkillSelector，categories=OUTLINE），本地 state 存 skill_key，请求时传入 getAISelection 结果
   - 当前选择链显示：`方向：X → 落点：Y`（从 messages 的选择记录推导）
   - 轮数指示：`第 N/5 轮`
2. **对话流**：
   - 历史轮折叠为一行（标题 = 该轮 AI 核心问题摘要，点击展开）
   - 当前轮：AI 气泡 + 选项卡片（点击 = 选择并延深，该轮选项禁用+高亮选中）+ 反馈输入框 + 唯一「确认此方向」按钮
   - 选项卡片展示 title + description + conflict + plotline（标签化）
3. **context 传递**：维护选择链数组（每轮选中的选项 title），请求时只传最近 2 轮拼接；feedback 单独传
4. **轮数上限**：第 5 轮后不再请求延深，提示确认或重新开始（提供"重新开始"按钮清空对话）
5. **确认流程不变**：确认 → onConfirm(direction) → 父组件填 story_direction → 底部「开始续写」提交

### 不动
- 后端接口路由、schema 不变
- 续写执行端（_build_outline_continue_context）不动
- 大纲总览页、灵感模式页面不动

## Acceptance Criteria

- [ ] 选项卡片显示卷级结构（标题 + 讲什么 + 冲突 + 人物线），不再是故事梗概
- [ ] 对话区顶部有 Skill 选择器（可切换，默认推荐大纲设计类），切换后建议生成使用新 Skill
- [ ] 历史轮折叠成一行可展开；当前轮完整显示
- [ ] context 只传最近 1~2 轮（实测请求体确认）
- [ ] 第 5 轮后无法继续延深，提示确认或重新开始
- [ ] 「确认此方向」按钮只出现一次（当前轮底部）
- [ ] 顶部显示当前选择链（方向 → 落点）
- [ ] 点选选项 = 延深且该轮禁用；反馈可让 AI 重生成
- [ ] 前端 tsc + build 通过；部署后实测对话流程正常

## Notes

- 后端 schema（ContinueAdviceOption）需要加 conflict/plotline 字段（title/description 已有）
- 前端类型同步（AdviceOption 加 conflict/plotline，可选字段向后兼容）
- SkillSelector 的 SKILL_CATEGORIES.OUTLINE 已有
- 弹窗宽度已 860，对话区高度可加 max-height + 内部滚动
