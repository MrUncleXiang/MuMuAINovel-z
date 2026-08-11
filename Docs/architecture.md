# 架构真相源（Architecture）

> 本文档是项目架构的"真相源"：概览、技术栈、模块地图、架构红线。
> 修改代码涉及架构时，先读本文；红线变更需记录到 [ADR](adr/README.md)。

## 项目概览

MuMuAINovel 是 AI 辅助中文网文创作平台。核心是一条"AI 自动创作管线"：

```
大纲（卷/章纲）→ 章节展开 → 正文生成 → 【正文审查（3步流水线，可自动修改）】
   → 章节分析（记忆/角色/职业/组织/伏笔状态同步 + 质量评分）→ 下一章
```

同时提供创作管理工具（角色、关系、组织、职业、伏笔、剧情分析）与 AI 工具箱（Skill 系统、提示词工坊、多模型对比、本书审查配置、卷检查）。

## 技术栈（真实版本）

| 层 | 技术 | 版本 |
|---|---|---|
| 后端框架 | FastAPI + Uvicorn | 0.121.0 / 0.38.0 |
| ORM / 迁移 | SQLAlchemy (async) + Alembic | 2.0.25 / 1.14.0 |
| 数据库 | PostgreSQL（容器 `mumuainovel-postgres`，42 张表） | — |
| 数据校验 | Pydantic | 2.12.4 |
| AI SDK | openai / anthropic（多 provider 兼容层 `ai_clients/`） | 2.7.0 / 0.72.0 |
| 向量记忆 | Chroma（内存/本地），`memory_service` 封装 | — |
| 前端 | React + Ant Design + Vite | 18.3.1 / 5.27.6 / 7.1.7 |
| 部署 | Docker Compose（`mumuainovel` + `mumuainovel-postgres`） | — |

## 模块地图

### 后端 `backend/app/`

| 模块 | 职责 |
|---|---|
| `api/` | FastAPI 路由：projects / outlines / chapters / characters / foreshadows / careers / prompts / skills / tasks 等 |
| `services/ai_provider_service.py` | 模型路由：`ai_usage_routes` 按 usage_type 选 provider+model；`create_routed_ai_service` 统一入口 |
| `services/ai_clients/` | HTTP 客户端（OpenAI 兼容 / Anthropic / Gemini）；**必须带浏览器 UA**（见 [spec](../.trellis/spec/backend/ai-provider-integration.md)） |
| `services/chapter_review_service.py` | 正文审查引擎：3 步流水线（错别字 → 表达/AI味 → 剧情），minor 原地修 / major 打回重写 |
| `services/chapter_analysis_materialization_service.py` | 分析物化：记忆入库、角色/职业/组织状态更新、伏笔同步（**同正文 hash 只物化一次**） |
| `services/memory_service.py` | 向量记忆：按章切片存取（Chroma），供章节生成上下文检索 |
| `services/background_task_service.py` | 后台任务：每用户 FIFO 队列，任务函数签名 `(task_id, user_id)`，自己建 session |
| `services/formal_chapter_service.py` | 正文"定稿"（formality）流程：生成内容 → 校验 → 持久化 → 派生状态检查点 |
| `models/` | SQLAlchemy 模型（42 张表） |
| `skills/` | 正文写作/审稿 SKILL 包（SKILL.md + references），经 `skill_loader` 注入提示词 |

### 前端 `frontend/src/`

| 模块 | 职责 |
|---|---|
| `pages/` | 大纲（Outline）、章节（Chapters）、剧情分析（ChapterAnalysis）、伏笔（Foreshadows）、审查配置（ReviewConfig）、流水线（PipelinePanel）等 |
| `components/` | AI 修改（ChapterAIChatEdit，diff 确认）、卷检查（VolumeReviewModal）、审查报告（ChapterReviewModal）、多模型对比（LLMCandidate*） |
| `services/api.ts` | Axios 封装（默认导出 `api` + 命名导出 `chapterApi` 等） |
| `theme/` | 主题（useThemeMode，暗色支持） |

## 架构红线

1. **生成/分析必须在后台任务中执行**（用户请求只创建任务，返回 task_id；前端轮询 `GET /api/tasks/{id}`）。禁止在请求内同步调用 AI 长任务。
2. **后台任务函数签名固定** `(task_id, user_id)`：db session / AI 服务 / tracker 由函数内部自建（`get_engine` + `create_routed_ai_service` + `TaskProgressTracker`），不要依赖自动注入。
3. **内容变更必须有 hash 校验**：分析任务绑定生成时的 `content_hash`；正文被编辑后过期结果一律丢弃（`analysis_task_matches_content`），禁止写入正式状态。
4. **状态派生顺序敏感**：展开 → 生成 → **审查（改定稿）** → 分析（基于定稿）→ 后续章。审查必须先于分析（分析基于最终正文）。
5. **正文审查的产物**：minor 原地最小修改、major 带问题清单打回重写；每章轮数上限（默认 2），超限停下等人工，不无限循环烧 token。
6. **AI 请求必须带浏览器 UA**（上游 Cloudflare 按 UA 指纹拦截：空响应/截断/无效 JSON/524 都是 WAF 症状，先查传输层再归咎模型）。见 [ai-provider-integration.md](../.trellis/spec/backend/ai-provider-integration.md)。
7. **设计内跳过不得使整任务失败**（如伏笔同步引用已删除伏笔 → 跳过并记录，不 abort 分析）。
8. **不要直接改数据库**：结构变更走 alembic 迁移；配置类（如 `ai_usage_routes` 模型路由）优先走设置 UI，直接改库可能被 UI 覆盖。
9. **前端复用既有模式**：AI 修改一律"流式生成 → diff 确认 → 应用"，不做黑盒覆盖。
