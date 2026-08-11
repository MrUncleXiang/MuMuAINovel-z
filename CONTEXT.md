# CONTEXT（单上下文总览）

> 单上下文布局：本文件 + `docs/adr/`。规则详见 `docs/agents/domain.md`。

## 这是什么

MuMuAINovel —— AI 辅助中文网文创作平台。

## 一句话定位

从大纲到正文的 AI 自动创作管线：大纲 → 展开 → 生成 → **审查** → 分析（状态同步）→ 下一章，配套角色/伏笔/剧情管理等创作工具与 Skill/提示词等 AI 工具箱。

## 真相源导航

| 想了解 | 去哪 |
|---|---|
| 架构（技术栈/模块地图/红线） | [Docs/architecture.md](Docs/architecture.md) |
| 架构决策记录 | [Docs/adr/README.md](Docs/adr/README.md) |
| 任务工作流（Trellis） | [.trellis/workflow.md](.trellis/workflow.md) |
| 编码规范 | [.trellis/spec/backend/index.md](.trellis/spec/backend/index.md)（后端）/ [frontend](.trellis/spec/frontend/index.md) / [guides](.trellis/spec/guides/index.md) |
| AI 服务商集成（UA/WAF/模型） | [.trellis/spec/backend/ai-provider-integration.md](.trellis/spec/backend/ai-provider-integration.md) |
| AI 助手入口索引 | [llms.txt](llms.txt) |

## 关键约定速记

- 生成/分析是后台任务；任务函数签名 `(task_id, user_id)`。
- 正文变更有 hash 校验，过期分析结果一律丢弃。
- 审查先于分析（分析基于定稿）。
- AI 请求必须带浏览器 UA（Cloudflare）。
- 沟通用大白话；需求未澄清不动手；任务登记按 AGENTS.md 判定标准。
