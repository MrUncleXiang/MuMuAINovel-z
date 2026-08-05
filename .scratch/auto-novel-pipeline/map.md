# 自动化小说生产流水线——实现蓝图

## Destination

为 MuMuAINovel 设计一条自动化小说生产流水线——从番茄小说热门题材检索开始，经过主题确认→分卷→大纲→章节自动生成，每阶段/每章设人工检查点（继续 or 回滚重写），支持预设里程碑（如"写完前 50 章暂停"）且无硬性终点。地图走完时交付一份实现蓝图，后续通过 Rudder 分批施工做进产品。

## Notes

- 项目：MuMuAINovel（FastAPI + React + PostgreSQL）
- LLM 接入：已有 OpenAI/Anthropic/Gemini 三协议 + 自定义中转（hubway、vc-grok、OpenCode Go）
- 已有能力：智能向导（建书）、大纲生成、章节生成、分析（拆书/章节分析）、多 LLM 对比、Prompt 工坊、伏笔管理
- 技能：grilling（决策）、research（查资料/代码）、prototype（快速原形验证）
- AGENTS.md 衔接：wayfinder 决策票 → Rudder 任务 → 分步施工

## Decisions so far

- 目的地：实现蓝图（地图走完交付设计决策文档，施工由 Rudder 分批执行）
- 目标平台（题材来源）：番茄小说为主
- 里程碑支持：用户预设章节数（如 50 章），到达时自动暂停
- 检查点可见内容：正文 + 分析报告 + 可选多 LLM 对比结果
- 回滚粒度：可分内容、分阶段回滚
- LLM 路由：各阶段独立配置模型
- 成本控制：提供费用上限设定与提醒
- 多 LLM 对比：可选开关 + 手动选模型 + 分额度控制
- [番茄小说热门题材数据获取方式](./issues/01-tomato-platform-data.md) — 全网无公开小说榜单 API（GitHub/Gitee/PyPI/npm/public-apis/豆瓣/NovelUpdates 全空）；决定：**题材检索改为"题材模板选择"**，模板库初始用 firecrawl 一次性采集或手动种子建立，持续自动爬虫不放进 MVP 蓝图。
- **分卷方案**：不改造 MuMuAINovel。沿用现有 Outline→Chapter 两层结构，每条 Outline = 一卷。无需新增 Volume 模型。
- [MuMuAINovel 现有建书流程与数据模型](./issues/02-existing-wizard-flow.md) — 向导分 4 步（世界观→职业体系→角色→大纲），无"分卷"概念（Project→Outline→Chapter 两层），分卷需新增 Volume 模型；向导是前端驱动 SSE，流水线需后台编排层。
- [项目现有章节推进与编排架构](./issues/03-existing-state-machine.md) — 无正式章节状态机（仅 draft 字符串），无自动推进机制，章节写作仅 SSE 模式；可复用 TaskProgressTracker 框架；需要 Pipeline Orchestrator + 章节状态升级 + 后台章节生成模式。
- [流水线阶段与检查点粒度设计](./issues/04-pipeline-stages-checkpoints.md) — 4 阶段（一键建书→章节循环→检查点→卷过渡）；检查点组合可配（每N章+每卷结束+里程碑+手动）；里程碑为独立计数器、与每N章可同时用；题材模板选择是建书入口输入；UI 要求：里程碑与每N章分开罗列放一起。
- [回滚语义设计（分内容/分阶段）](./issues/05-rollback-semantics.md) — 默认只回退正文、可选正文+大纲；可回退任意历史检查点；旧内容纯删除不留存；重写走现有"带反馈重写"（可写要求/换模型/换风格，无需特殊设计）；回退可重复执行无特殊状态。
- [流水线前端体验设计](./issues/06-frontend-experience.md) — 侧边栏最上独立"流水线"面板（驾驶舱）；检查点审阅在面板内完成（复用现有分析/对比组件）；建书向导配流水线设置（默认值预填）+ 运行中随时可改；状态展示=阶段流程线+阶段内进度+下个检查点提示。
- [各阶段 LLM 路由与成本预算设计](./issues/07-llm-routing-budget.md) — 全阶段默认 deepseek-v4-flash（OpenCode Go）、每阶段可自定义其他已配置 LLM；多 LLM 对比任何阶段可开（开关+选模型+分额度）；预算=金额+tokens 双显示、超限自动暂停可加预算/换模型；每阶段独立暴露 temperature/max_tokens。

---

**地图完成：7/7 票全部解决。路线已清晰，可以转交施工。**

## Not yet specified

（空——地图已完成，所有决策已拍板）

> 施工前技术调研项：firecrawl 接入细节（API 额度、目标榜单 URL、模板数据结构）——作为 Rudder 施工任务之一处理

## Out of scope

- 内容分发/发布到外部小说平台（本图只覆盖"生产"，不覆盖"发布"）
- AI 自动完结判定（完结仍为人工判断，不属于本次自动化范围）
- 多语言/翻译支持
