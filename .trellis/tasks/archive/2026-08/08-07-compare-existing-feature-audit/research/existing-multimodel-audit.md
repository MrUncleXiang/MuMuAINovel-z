# MuMuAINovel 既有多模型创作能力审计

> 审计日期：2026-08-07
> 审计范围：当前工作区运行代码（包括尚未提交的“整书对比”原型）
> 证据口径：只引用仓库源码这一手资料；本次为静态只读审计，未调用真实 LLM。

## 结论

当前仓库已经有一套可复用的“同一输入、多模型候选、人工采用”底座，但它只适合**单个创作对象的候选决策**，不能代替“一本长期独立创作的书”。新增的双书原型把复制、选两个模型、启动两条流水线和阅读对比绑成一次操作，又依赖尚未闭环的流水线，因此不应继续按现状产品化。

最关键的三个断点是：

1. 章节正文候选被采用后，只写正式章节和生成历史，没有创建 `AnalysisTask`，也没有触发原有章节分析。因此记忆、伏笔、角色、关系、组织和职业状态不会随采用结果更新（`backend/app/services/chapter_comparison_service.py:217-264`）。
2. 章节分析候选被采用后，只写 `plot_analysis`，没有执行正式分析后半段的记忆、伏笔、角色、关系、组织和职业更新，也没有生成完成态 `AnalysisTask`（`backend/app/services/analysis_comparison_service.py:52-77`；正式链路见 `backend/app/api/chapters.py:1257-1465`）。
3. 自动流水线虽然调用了现有章节后台生成函数，但强制关闭 Skill、MCP 和写作风格；生成函数异步发起分析后，流水线不等待分析完成就继续找下一章（`backend/app/services/pipeline_service.py:656-705`、`backend/app/services/pipeline_service.py:428-485`；异步分析见 `backend/app/api/chapters.py:2635-2658`）。

因此，正确的工程顺序应是：**先修复正式“生成 -> 分析 -> 状态更新 -> 下一章”闭环，再做可选继承范围的项目深复制，最后才做单副本入口和双书阅读对比。**

## 术语和生命周期

### 候选型持久化记录

“临时候选”不是只存在浏览器内存的临时数据。每次比较都会持久化一个 `llm_comparison_batches` 批次和多个 `llm_comparison_candidates` 候选，保存冻结输入、提示词、参数、输出、失败原因、Token、耗时和采用结果（`backend/app/models/llm_comparison.py:14-81`）。

它之所以叫“候选”，是因为采用前不应改变正式项目状态；删除批次会级联删除候选（`backend/app/services/llm_comparison_service.py:147-152`）。它的生命周期依附于同一本书中的一个章节、大纲或分析对象，不是一本可独立推进的书。

### 持久化项目副本

“项目副本”是新的 `projects` 记录，拥有自己的项目级数据、章节、分析状态和流水线。当前原型确实创建了两本数据库项目，不是浏览器缓存；但前端把“两次复制 + 两条流水线启动 + 跳转阅读页”绑成一次临时编排（`frontend/src/components/CreateComparisonModal.tsx:70-109`）。

项目副本与候选批次不能共用同一个产品概念：

| 维度 | 候选型持久化记录 | 持久化项目副本 |
| --- | --- | --- |
| 目的 | 给同一个正式对象选一个版本 | 用不同配置长期创作两本独立书 |
| 正式写入 | 采用前不写，采用后写回原对象 | 从创建起就是普通项目 |
| 进度 | 没有独立章节进度 | 独立章节、分析和流水线进度 |
| 管理入口 | 章节/大纲/分析页面 | 普通书架和项目页面 |
| 删除含义 | 删除候选历史 | 删除整本副本及其项目数据 |

## 能力矩阵

| 能力 | 现有前端入口 | 后端入口/服务 | 持久化 | Skill / 风格 / MCP | 正式状态闭环 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 单章节正文多模型候选 | 章节编辑页“多模型比较”（`frontend/src/pages/Chapters.tsx:2929-2957`） | `POST /chapters/{id}/comparison-batches`（`backend/app/api/chapters.py:1530-1564`） | 比较批次、候选；采用后写 Chapter、GenerationHistory | 三者都支持并冻结进快照（`backend/app/services/chapter_comparison_service.py:54-157`） | **缺失**：采用后不触发分析 | 保留底座，P0 整改采用链路 |
| 批量章节多模型候选 | 批量生成弹窗“多模型对比批量”（`frontend/src/pages/Chapters.tsx:3296-3305`） | `POST /chapters/project/{id}/batch-compare`（`backend/app/api/chapters.py:3889-3975`） | 每章一个比较批次，另有 BatchGenerationTask 汇总进度 | API 支持，但当前前端固定 `enable_mcp:false`，且没有传 Skill（`frontend/src/pages/Chapters.tsx:1351-1361`） | **不成立**：多章同时冻结、生成，不等采用和分析 | 暂停作为连续写书入口；重构后再决定保留 |
| 大纲多模型候选 | 大纲生成弹窗“多模型比较”（`frontend/src/pages/Outline.tsx:743-751`） | `POST /outlines/comparison-batches`（`backend/app/api/outlines.py:1837-1857`） | 比较批次、候选；采用后写正式 Outline/Chapter 骨架 | 支持 MCP 开关；不支持 Skill/写作风格（`backend/app/services/outline_comparison_service.py:92-157`） | 采用复用 `_save_outlines`，并阻止覆盖已有正文（`backend/app/services/outline_comparison_service.py:176-219`） | 保留，整改上下文与可配置项 |
| 章节分析多模型候选 | 章节分析弹窗“多模型比较”（`frontend/src/components/ChapterAnalysis.tsx:876-883`） | `POST /chapters/{id}/analysis-comparison-batches`（`backend/app/api/chapters.py:1489-1501`） | 比较批次、候选；采用后只写 PlotAnalysis | 固定关闭 MCP；无 Skill/风格 | **严重缺失**：没有正式分析副作用和完成态任务 | 暂停“采用”能力，复用正式分析物化服务后恢复 |
| 单模型顺序批量生成 | 章节批量生成弹窗 | `POST /chapters/project/{id}/batch-generate` | Chapter、GenerationHistory、AnalysisTask、PlotAnalysis、Memory 等正式数据 | 支持 provider/model/Skill/风格/MCP（`backend/app/schemas/chapter.py:176-193`） | 开启同步分析时会等本章分析完成再继续（`backend/app/api/chapters.py:4370-4434`） | **应作为连续创作底座保留** |
| 自动小说流水线 | 项目“流水线驾驶舱” | `/pipelines/*`、`pipeline_service` | 一本项目一条 NovelPipeline，含配置、预算、检查点（`backend/app/models/novel_pipeline.py:50-78`） | 运行时强制 Skill/风格为空、MCP 关闭 | 自动分析异步，下一章不等分析 | 保留编排和检查点，P0 重构章节循环 |
| 双书创建原型 | 项目页、流水线页、向导完成页、灵感完成页 | `clone-for-compare` + 启动两条 pipeline | 两本 Project + 两条 Pipeline | 弹窗只能选两组 provider/model 和章数 | 依赖有缺口的 pipeline | 废弃“双副本自动开跑”交互，改为一次创建一本普通副本 |
| 双书章节阅读原型 | `/compare` | 复用项目、章节、流水线查询 | 不产生额外对比数据 | 只展示 pipeline 的章节模型 | 只读，不参与创作 | 与创建解耦后可保留为可选阅读工具 |

## 逐项审计

### 1. 共享候选底座值得保留

共享服务已经正确处理了几个重要边界：

- 创建批次时验证 AI 服务属于当前用户且已启用，不保存 API Key（`backend/app/services/llm_comparison_service.py:64-111`）。
- 每个候选独立执行和记录失败，一个失败不会抹掉其他成功结果；并发上限为 2（`backend/app/services/llm_comparison_service.py:223-298`）。
- 只有成功候选能采用；采用过程带数据库事务，重复采用同一候选可安全返回，不能再改选其他候选（`backend/app/services/llm_comparison_service.py:158-193`）。
- 候选批次可按项目、目标类型和目标 ID 查询，页面关闭后仍可找回（`backend/app/api/llm_comparisons.py:67-104`）。

建议：保留 `LLMComparisonBatch`、`LLMComparisonCandidate` 和共享生命周期服务，不再创建第二套“比较引擎”。需要补齐的不是候选存储，而是各目标的“采用后如何进入正式底座”。

### 2. 单章节正文候选：生成能力较完整，采用后断链

正文候选在创建时只构建一次正式章节上下文，不同模型得到同一份冻结提示词。上下文包含大纲模式、角色、职业、伏笔、记忆、上一章摘要和近期章节；还会冻结 Skill、写作风格、叙事人称、目标字数和 MCP 参数（`backend/app/services/chapter_comparison_service.py:31-157`）。创建接口也检查前置章节正文及上一章分析已经完成（`backend/app/api/chapters.py:1530-1548`）。

采用时有并发保护：如果正式章节在候选生成后被改过，就拒绝覆盖；成功采用后会更新章节、项目总字数并记录采用前后两个 GenerationHistory（`backend/app/services/chapter_comparison_service.py:217-264`）。

但采用函数到此结束，没有创建 `AnalysisTask`、没有调用 `analyze_chapter_background`。前端采用处理也只刷新章节和项目（`frontend/src/pages/Chapters.tsx:1190-1207`）。这意味着被采用的正式正文不会推动后续记忆和角色状态，下一章的 `check_previous_analysis_ready` 还可能因没有完成态分析任务而阻止生成（该检查见 `backend/app/api/chapters.py:605-632`）。

建议：保留生成和候选 UI；把“采用正文 + 失效旧分析派生数据 + 创建分析任务 + 分析成功后才允许下一章”做成一个正式服务。不要靠前端延时发一个分析请求，因为页面关闭、网络失败或重试都可能造成断链。

### 3. 批量章节对比：不能作为连续小说生产

该接口先查出一个章节范围，然后循环为所有章节创建冻结快照并立即调度候选生成（`backend/app/api/chapters.py:3914-3969`）。它只检查起始章节的上一章是否分析完成（`backend/app/api/chapters.py:3927-3930`），任务本身还明确保存 `enable_analysis=False`（`backend/app/api/chapters.py:3932-3940`）。

后果是第 N、N+1、N+2 章可以同时基于旧数据库状态生成：此时前一章候选尚未被用户采用，更不可能完成正式分析。因此后续章节看不到前章最终正文、记忆、伏笔和角色状态。任务“完成”只表示候选都成功或失败，不表示章节已采用或分析完成（`backend/app/api/chapters.py:4118-4156`）。

建议：立即停止把它描述为“批量创作”。若保留，可限定为“为若干互不依赖的既有章节批量准备候选”；若目标是连续写书，应改成严格状态机：本章候选完成 -> 用户采用 -> 正式分析完成 -> 才创建下一章候选。这个交互成本很高，因此整书不同 LLM 创作更适合“复制一本书后，每本书各自跑单模型正式底座”。

### 4. 大纲候选：采用边界较好，但输入不完全等同正式大纲链路

大纲候选支持新建和续写，冻结现有大纲签名，并在采用时再次核对签名，避免覆盖生成期间发生的修改（`backend/app/services/outline_comparison_service.py:92-131`、`backend/app/services/outline_comparison_service.py:176-200`）。新建模式若发现已有章节正文会拒绝替换（`backend/app/services/outline_comparison_service.py:210-219`）。

缺口：续写提示词把伏笔提醒硬编码为“暂无需要关注的伏笔”，`mcp_references` 也为空；虽然生成调用本身支持 MCP，但没有 Skill 和写作风格参数（`backend/app/services/outline_comparison_service.py:68-89`、`backend/app/services/outline_comparison_service.py:128-157`）。

建议：保留。将正式大纲生成和大纲候选共同依赖一个公开的“构建大纲冻结输入”服务，避免继续从 `app.api.outlines` 导入私有函数（`backend/app/services/outline_comparison_service.py:28-30`）。

### 5. 分析候选：当前“采用”不是正式分析

候选提示词明确不读取动态伏笔，也只分析正文出现的角色（`backend/app/services/analysis_comparison_service.py:18-30`）。正式分析则会读取已埋伏笔、按大纲筛选项目角色并带职业信息（`backend/app/api/chapters.py:1076-1139`）。因此两者输入语义已经不同。

更严重的是，候选采用只创建或更新 `PlotAnalysis` 的字段（`backend/app/services/analysis_comparison_service.py:52-77`）；正式分析在写完 PlotAnalysis 后还会：

- 清理旧分析伏笔并重建 StoryMemory（`backend/app/api/chapters.py:1257-1338`）；
- 更新角色职业（`backend/app/api/chapters.py:1340-1368`）；
- 更新角色心理状态、角色关系和组织成员（`backend/app/api/chapters.py:1370-1406`）；
- 更新组织自身状态和伏笔状态（`backend/app/api/chapters.py:1408-1459`）；
- 最终把 AnalysisTask 置为 completed（`backend/app/api/chapters.py:1463-1465`）。

分析候选采用没有上述任何步骤，也没有 AnalysisTask。页面文案称“采用前不会修改记忆、角色、关系、组织或伏笔”（`frontend/src/components/ChapterAnalysis.tsx:969-978`），但没有说明“采用后也不会修改”，会误导用户。

建议：在抽取统一的“分析结果物化服务”之前，暂停分析候选的“采用”按钮，只允许预览和差异查看。整改后，单模型分析和候选采用必须调用同一套物化服务并产生完成态 AnalysisTask。

### 6. 正式单模型生成/分析链路是应复用的底座

正式章节请求支持 `style_id`、provider/model、叙事人称、Skill 和 MCP（`backend/app/schemas/chapter.py:120-133`）。章节生成上下文包含大纲、角色、职业、伏笔、记忆和前文（例如 `backend/app/api/chapters.py:2437-2510`），生成完成后会保存正文、项目字数和生成历史，自动标记伏笔，创建分析任务并启动正式分析（`backend/app/api/chapters.py:2580-2658`）。

单模型顺序批量生成还会在每章前检查前置正文和上一章分析，并在开启同步分析时等待分析结果后再进入下一章（`backend/app/api/chapters.py:4370-4434`）。这条链路最接近用户描述的 MuMuAINovel 底座，应成为副本后续创作的事实标准。

### 7. Pipeline：保留编排外壳，重做章节循环接入

流水线的持久化设计本身合理：一本书一条 `NovelPipeline`，保存配置快照、进度、检查点历史和预算（`backend/app/models/novel_pipeline.py:50-78`）；支持暂停、恢复、停止、检查点继续和回滚（`backend/app/api/pipelines.py:103-190`）。

但运行时存在以下断点：

- 默认配置只有阶段模型、预算和少量参数，没有 Skill、写作风格和 MCP（`backend/app/services/pipeline_service.py:52-70`）。
- 章节生成明确传入 `style_id=None`、`skill_key=None`、`enable_mcp=False`（`backend/app/services/pipeline_service.py:667-699`）。
- 配置页能选“章节分析模型”（`frontend/src/pages/PipelinePanel.tsx:381-387`），但章节生成后调用分析时没有传 provider/model（`backend/app/api/chapters.py:2651-2658`），流水线服务也没有另行调用分析模型。这一配置当前不生效。
- 章节生成会异步启动分析，主循环只按字数判定正文成功，然后直接预算/检查点/下一轮；`_next_pending_chapter` 只调用 `check_prerequisites`，不调用 `check_previous_analysis_ready`（`backend/app/services/pipeline_service.py:428-485`、`backend/app/services/pipeline_service.py:508-539`）。

建议：保留 pipeline、检查点和预算模型；把章节循环改为调用统一的“正式生成并等待正式分析”服务。完成前，不应让新副本自动启动 pipeline。

## 配置交互与“副本独立”边界

用户要求“默认复制配置，之后可自行修改，修改 A 书不能影响 B 书”。当前数据模型必须区分**资源定义**和**项目选择/运行快照**：

| 配置 | 当前归属 | 是否有交互 | 当前能否按书独立修改 | 结论 |
| --- | --- | --- | --- | --- |
| AI 服务/API Key/模型目录 | 用户级 `ai_provider_configs`，无 project_id（`backend/app/models/ai_provider_config.py:9-33`） | 设置页及各生成页可选 | 服务定义共享；pipeline 的 provider/model 选择按项目快照保存 | 副本只复制选择 ID+模型名，不复制 API Key；全局服务变更必须标明会影响所有项目 |
| 默认任务路由 | 用户级 `ai_usage_routes`（`backend/app/models/ai_provider_config.py:36-55`） | 有设置交互 | 不是项目独立 | 需要项目级覆盖或 pipeline 快照，不能把用户默认路由称为“书籍配置” |
| 写作风格定义 | 全局预设或用户级 `writing_styles`（`backend/app/models/writing_style.py:7-20`） | 可增删改 | 定义共享 | 修改风格文本会影响引用它的多本书；对可复现实验应冻结风格内容或做版本化 |
| 项目默认风格选择 | 项目级 `project_default_styles`（`backend/app/models/project_default_style.py:7-20`） | 可设置默认（`frontend/src/pages/WritingStyles.tsx:142-155`） | 是 | 副本默认复制这条“选择”，当前 clone 未复制 |
| Skill 定义 | 服务器文件 `backend/app/skills/*`，由全局目录加载（`backend/app/services/skill_loader.py:1-24`） | 有全局 CRUD（`backend/app/api/skills.py:194-245`） | 否 | Skill 不是项目数据；当前甚至没有用户隔离。需要版本/快照，不能声称复制后独立 |
| 项目默认 Skill 选择 | 不存在；章节页仅 React 临时状态（`frontend/src/pages/Chapters.tsx:86-89`） | 每次生成可选 | 不存在可复制对象 | 先新增项目/pipeline 选择快照及编辑界面 |
| MCP 插件定义 | 用户级 `mcp_plugins`，无 project_id（`backend/app/models/mcp_plugin.py:8-49`） | 有插件管理页 | 定义共享 | 不应复制插件凭据；应保存项目级启用策略/快照 |
| MCP 每书开关 | 不存在统一设置 | 章节单模型请求省略字段，后端默认 true；章节比较硬编码 true；批量比较硬编码 false | 否 | 需要明确的项目/pipeline 控件，消除入口间不一致 |
| 分析模型 | 单次分析可选；pipeline 配置可选 | 有 | pipeline 快照按书独立 | 运行时未使用，先修复后才可验收“已复制” |
| 预算、检查点、每章字数 | pipeline.config_snapshot | 有 pipeline 配置面板（`frontend/src/pages/PipelinePanel.tsx:330-390`） | 是 | 可复制为新 pipeline 的初始配置，但新副本不应自动开跑 |

因此“完全独立”应写成可验证的两层契约：

1. **项目拥有的数据必须深复制**：正文、分析、记忆、伏笔、角色状态、角色关系、组织、职业、章节/大纲关联、默认风格选择、pipeline 配置都使用新项目/新实体 ID；修改 A 的项目数据不得改变 B。
2. **用户级资源只允许引用，不伪装成项目数据**：AI 服务、Skill 定义、MCP 插件、用户自定义风格是共享资源。项目应保存独立的“选择和运行快照”；若要求历史可复现，还需冻结 Skill/风格内容及模型名。API Key、插件凭据不能复制进项目。

当前克隆服务只复制项目字段、角色、关系、组织、大纲和空章节骨架（`backend/app/services/project_clone_service.py:62-90`、`backend/app/services/project_clone_service.py:97-248`），没有复制职业、角色职业、项目默认风格、pipeline 配置，也不支持“继承到第 X 章”的正文及派生状态，尚不能满足上述契约。

## 双书原型审计

### 创建入口

当前弹窗一次要求模型 A、模型 B 和生成章数，然后创建两本副本、并行启动两条流水线并跳转 `/compare`（`frontend/src/components/CreateComparisonModal.tsx:16-39`、`frontend/src/components/CreateComparisonModal.tsx:70-109`）。入口分布在项目页、流水线页、向导完成页和灵感完成页（`frontend/src/pages/ProjectDetail.tsx:393-428`、`frontend/src/pages/PipelinePanel.tsx:194-197`、`frontend/src/pages/ProjectWizardNew.tsx:393-407`、`frontend/src/pages/Inspiration.tsx:1259-1272`）。

建议废弃这个组合交互，替换为一次只创建一本持久化副本：选择继承模式和截止章，创建后回到普通书架；用户在副本自己的项目/流水线页面检查并修改配置，再手动启动。

### `/compare` 页面

该页面允许从普通项目列表选择左右两本书，以 `chapter_number` 对齐章节，并读取各自 pipeline 状态轮询刷新（`frontend/src/pages/CompareView.tsx:37-96`）。它只展示正文和模型信息，不写数据（`frontend/src/pages/CompareView.tsx:108-151`）。

这是“两本现有书逐章阅读比较”，不是“同一章节多模型候选比较”。两者应使用不同命名：建议叫“书籍并排阅读”，避免和已有候选采用功能混淆。页面可以保留为后置可选工具，但必须与“创建副本”和“启动创作”解耦；当前 `/compare` 已注册为独立路由（`frontend/src/App.tsx:52-56`）。

## 保留、整改、废弃建议

### 保留

- `LLMComparisonBatch` / `LLMComparisonCandidate` 及共享创建、并发、重试、采用事务、查询能力。
- 单章节正文候选的冻结输入、Skill/风格/MCP 支持、候选编辑和差异查看。
- 大纲候选的冻结签名和采用前冲突检查。
- 正式单模型章节生成、同步分析、记忆/伏笔/角色状态更新链路。
- NovelPipeline 的项目唯一性、预算、检查点、暂停/恢复/回滚外壳。
- `/compare` 作为可选的只读“双书并排阅读”，但后置实施并改名澄清。

### 整改后保留

- 章节候选采用：必须接入正式分析任务，并明确旧分析派生状态的失效/重建规则。
- 分析候选：必须复用正式分析输入构建和统一物化服务；整改前禁用采用。
- 大纲候选：统一正式输入构建服务，补足伏笔上下文，并决定 Skill/风格是否适用于大纲。
- Pipeline：配置并实际传递 provider/model、分析模型、Skill、风格、MCP；严格等待本章分析完成。
- 克隆服务：支持“仅设定”与“继承到第 X 章”，做全表依赖清单和旧 ID -> 新 ID 映射，复制项目级配置选择但不复制密钥。
- 配置 UI：补项目/pipeline 级 Skill、MCP、风格和分析配置；清楚标识哪些是全局资源、哪些是本书设置。

### 废弃或暂停

- 废弃 `CreateComparisonModal` 当前“一次创建两本并自动启动”的交互实现。
- 暂停把 `batch-compare` 用于连续章节创作；未建立逐章采用/分析状态机前，不应作为 pipeline 或整书对比底座。
- 暂停分析候选的“采用”操作；当前采用会制造“有 PlotAnalysis、无配套状态更新/完成任务”的不一致状态。
- 暂停新副本自动启动当前 pipeline；允许用户先检查配置，再手动启动。

## 任务拆分与依赖顺序

### P0：先修正式底座

1. **统一分析物化服务**
   从 `analyze_chapter_background` 抽出“将结构化分析写入 PlotAnalysis、Memory、伏笔、角色、关系、组织、职业并完成 AnalysisTask”的事务边界；单模型分析和分析候选采用共同调用。需先定义重分析时旧状态如何撤销或重算。
2. **统一章节采用后处理**
   章节候选采用和普通章节生成共同使用“正文正式落库 -> 分析任务 -> 等待/失败处理”的服务，补并发和幂等测试。
3. **整改 pipeline 章节循环**
   依赖 1、2；传递完整配置并等待分析完成，再推进下一章。修复 analysis model 配置不生效。

对应现有任务：`.rudder/tasks/08-07-compare-pipeline-foundation/` 应承接以上工作，并拆成可独立验收的小任务，不应一次性修改整条大文件链路。

### P1：定义并实现项目深复制

4. **继承范围和数据依赖清单**
   先枚举所有 project/chapter 归属表及向量存储，定义“仅设定”和“继承到第 X 章”的闭包。继承 X 章必须包含 1..X 正文以及支撑 X+1 续写的分析、记忆、伏笔和实体状态，不能让用户任意取消关键分析子项后仍宣称可续写。
5. **独立配置快照**
   定义项目级 Skill/MCP/风格/模型/分析模型选择；明确用户级资源共享边界和快照/版本策略。
6. **原子深复制服务**
   依赖 4、5；生成全部新 ID 和外键映射，在单事务中创建一本普通副本，并用隔离测试证明修改 A 不影响 B。

对应现有任务：`.rudder/tasks/08-07-compare-project-clone/`。

### P2：再做用户入口

7. **单副本创建面板**
   依赖 6；一次创建一本，提供“仅复制设定 / 继承至第 X 章”，展示系统自动包含的分析闭包，创建后不自动启动。
8. **副本内配置审阅和手动启动**
   依赖 3、5、7；复用普通书架、项目页、章节页和 pipeline 面板。

对应现有任务：`.rudder/tasks/08-07-compare-single-clone-ui/`。

### P3：可选阅读工具

9. **双书并排阅读**
   依赖 7；确认真实使用需求后再保留/整改 `/compare`，只负责选择两本已有书和并排阅读，不负责创建或生成。

原任务 `.rudder/tasks/08-07-compare-ui/`、`.rudder/tasks/08-07-compare-view/` 和 `.rudder/tasks/08-07-clone-for-compare/` 应冻结原实现口径，由上述新任务替代；不要在原双模型自动编排上继续补功能。

## 验证要求

后续实现至少需要以下自动化验证；当前 `backend/tests/` 只有 OpenAI client 和项目克隆测试，没有候选、分析采用、batch-compare 或 pipeline 闭环测试。

1. 采用章节候选后，必须生成完成态 AnalysisTask，并可观察到 PlotAnalysis、StoryMemory、伏笔及角色状态按采用正文更新。
2. 分析候选采用后的数据库结果必须与把同一结构化分析交给正式物化服务一致。
3. Pipeline 第 N+1 章开始前，第 N 章 AnalysisTask 必须 completed；分析失败时流水线暂停且不能继续烧模型额度。
4. Pipeline 配置的章节模型、分析模型、Skill、风格和 MCP 必须在 AI 调用日志/冻结快照中可追踪。
5. 继承到第 X 章的副本能直接从 X+1 章续写；副本内不存在指向源项目实体 ID 的外键或 JSON 引用。
6. 修改/删除副本 A 的正文、分析、角色、关系、组织、职业、伏笔、默认风格选择和 pipeline 配置，不改变源书或副本 B。
7. 用户级 API Key、MCP 凭据不复制进项目；全局资源变更的影响范围在 UI 中明确展示。
8. 双书并排阅读只能读取已有项目，页面关闭后两本书仍可从普通书架独立管理。
