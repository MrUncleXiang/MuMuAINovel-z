# MuMuAINovel 现有建书流程与数据模型

Type: research
Status: resolved

## Question

MuMuAINovel 当前的"智能向导"建书流程（wizard）具体怎么运作的？项目创建时需要哪些输入字段（标题、类型、主题、世界观参数等）？"分卷"概念在现有数据模型中是否存在（还是只有"大纲→章节"两层）？建书完成后 AI 自动生成哪些内容（大纲？角色？世界观？）以及先后顺序？

## Answer

**现有建书流程（智能向导）：**

向导通过 SSE 流式接口 `/wizard-stream/*` 分 4 步顺序推进：
1. **世界观构建** (`POST /world-building`)：输入 title/theme/genre（必填）→ AI 生成 world_time_period、world_location、world_atmosphere、world_rules → 创建 Project 记录
2. **职业体系** (`POST /career-system`)：可选，AI 生成修仙境界/魔法等级等自定义等级体系
3. **角色生成** (`POST /characters`)：根据世界观 + 职业体系 → AI 批量生成角色（含性格、外貌、关系）
4. **大纲生成** (`POST /outline`)：综合以上 → AI 生成完整大纲（章节标题 + 摘要），写入 Outline 表

**建书输入字段（Project 模型）：**
- 标题(title)、主题(theme)、类型(genre)、简介(description)
- 目标字数(target_words)、大纲模式(outline_mode: one-to-one / one-to-many)
- 世界观字段：world_time_period、world_location、world_atmosphere、world_rules
- 向导状态：wizard_status（incomplete/completed）、wizard_step（0-4）

**关键发现：**
- ❌ **没有"分卷"概念**——现有结构是 Project → Outline（多条）→ Chapter（一条大纲下可有多个子章节）
- 分卷是流水线的**全新概念**，需要设计数据模型（Volume 表）和与大纲/章节的关联
- 向导是按步流式执行的（前端驱动，用 SSE 展示进度），不是后台自主推进——流水线需要一个"后台自主编排"层

**对流水线蓝图的影响：**
- "分卷"需要从 0 设计（建表、关联关系、卷→章→子章节三层结构）
- 向导现有 4 步可复用为流水线的"建书阶段"，但需要改造成后台任务模式（不用 SSE）
- 现有输入字段基本够用（流水线需要新增：里程碑数、模型偏好、预算上限、检查点频率等配置字段）

---
Resolved. 向导4步建书、无分卷概念、需新增 Volume 模型 + 后台编排层。
