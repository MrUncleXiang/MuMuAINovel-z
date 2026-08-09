# PRD：展开章节 AI 点评建议

## Goal

在「展开信息」弹窗中增加「🤖 AI 点评建议」按钮：针对已展开的章节数、每章章纲（叙事目标/关键事件/涉及角色/场景/情感基调/预计字数）与项目上下文，由 AI 做整体分析点评，输出改进建议。建议**不入库**，弹窗展示。

## Requirements

1. 后端新接口 `POST /api/outlines/{outline_id}/ai-review`：
   - 请求：`{ instruction?, skill_key?, provider_config_id?, model? }`（均可选）
   - 上下文：项目信息 + 角色 + 该大纲 structure + 已展开章节完整章纲 + 相邻大纲
   - 提示词模板 `OUTLINE_AI_REVIEW`（注册进模板体系，可覆盖）
   - 输出：纯文本点评建议（不要求 JSON，避免解析失败）
   - 写 GenerationHistory；不入库
2. 前端「展开信息」弹窗（showExistingExpansionPreview）增加「🤖 AI 点评建议」按钮：
   - 点击 → loading → 调用接口 → 新弹窗展示建议文本
   - 可选：Skill 选择（推荐 `review` 五维诊断技能）、模型选择（复用 AIServiceSelector）
3. 兼容：未展开的大纲不显示此按钮（展开信息弹窗只在已展开时出现，天然满足）

## Acceptance Criteria

- [ ] 已展开卷的「展开信息」弹窗可发起 AI 点评；弹窗展示建议文本（可滚动复制）
- [ ] 带 SKILL（SKILL_REVIEW）时后端日志出现「已将 Skill」注入
- [ ] 未指定模型/服务商时走默认路由
- [ ] 不入库（outlines/chapters 表无变化）；GenerationHistory 有记录
- [ ] 前端 typecheck/build 通过
