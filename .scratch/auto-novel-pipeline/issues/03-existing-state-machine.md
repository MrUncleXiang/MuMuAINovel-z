# 项目现有章节推进与编排架构

Type: research
Status: resolved

## Question

当前项目里章节推进的逻辑是怎么设计的？是否存在"章节状态机"（如 draft→generating→review→approved→rewriting 之类的状态流转）？大纲、章节、分析之间的关系如何？现有的任务轮询机制（/api/tasks/{task_id}）能否直接复用于流水线的"后台自动推进+人工检查点挂起"模式？还需要看哪些后台编排能力（background_task_service？）？

## Answer

**现有章节状态管理：**
- Chapter 表有 `status` 字段（String，默认 "draft"），但**没有正式的状态机**——没有 draft→generating→review→approved 之类的枚举约束和转换逻辑。
- 章节写作：`POST /{chapter_id}/generate-stream`（SSE 流式），要求前端在线、不能断连。
- 章节重写：`ChapterRegenerator.regenerate_with_feedback()` 支持"带反馈重写"（用户写修改意见 → AI 重写）。
- 章节分析：有独立的分析生成端点（后台任务），与多 LLM 对比集成。

**现有后台任务机制（可复用）：**
- `TaskProgressTracker`：后台任务的进度跟踪器，状态机为 loading → preparing → generating（含分块) → parsing → saving → completed / failed / cancelled。
- `background_task_service`：管理任务生命周期，前端通过 `GET /api/tasks/{task_id}` 轮询状态和进度。
- 已有实例：大纲生成（后台任务）、章节分析（后台任务）、多 LLM 对比批次（后台异步调度）。
- 关键限制：同时写库有用户级锁（`get_db_write_lock`），防止并发写冲突。

**关键发现：**
- ❌ **没有"自动推进"机制**——现有系统全部是前端手动触发（点"生成大纲"→等结果→点"生成章节"→等结果→…）。流水线需要一个**后台编排引擎**，在无前端驱动的情况下按阶段自动触发下一个任务。
- ⚠️ 章节写作只有 SSE 模式，流水线需要新增一个"后台章节生成"模式（复用 ChapterRegenerator + 任务轮询）。
- ✅ TaskProgressTracker 框架可直接复用为流水线的进度层（每阶段包裹一个 tracker）。
- ✅ 已有用户级写锁，天然防止流水线自动推进时与用户手动操作冲突。

**对流水线蓝图的影响：**
- 需要设计一个新组件：**Pipeline Orchestrator**（流水线编排器），职责是：读当前阶段 → 判断下一步 → 触发生成 → 挂起等检查点 → 用户发"继续"信号 → 继续。
- 章节状态字段需要升级为正式的状态枚举（加入流水线专用状态：awaiting_review、rewriting_rollback 等）。
- 流水线的每个后台步骤可以复用 TaskProgressTracker 范式（进度可见、可取消）。

---
Resolved. 无自动推进机制、无正式状态机、章节仅SSE模式；需要 Pipeline Orchestrator + 章节状态升级 + 后台章节生成。
