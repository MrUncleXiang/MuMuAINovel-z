# PRD：正文阅读页（仿笔趣阁拆页式通读）

## 背景

用户希望像在小说网站（如笔趣阁）读小说一样，完整、连贯地阅读一本书的全部正文。现状缺口：

- **大纲总览**（`OutlineOverview.tsx`）：只有卷大纲（剧情梗概），没有正文
- **单章阅读器**（`ChapterReader.tsx`，`/chapters/:id/reader`）：一次只读一章，分析导向（记忆标注/重新分析），翻章需要点击加载，不适合连贯通读
- **章节管理**（`Chapters.tsx`）：管理操作界面，不适合阅读

需要新增一个独立的「正文阅读」页面。

## 需求（用户已逐条确认）

### 1. 拆页逐章节显示正文（核心）
- **1-1** 点击【正文阅读】按钮进入后，**右侧显示目录**（按卷分组 → 卷下列章节）
- **1-2** 点击目录项，右侧内容区跳转显示**该章节的全部正文**（单页一章，不连续铺开）
- **1-3** 提供**上一章 / 下一章**按钮跳转章节，首/末章边界按钮置灰

### 2. 默认纯阅读
无记忆标注、无分析按钮、无编辑入口。点章节标题只做目录跳转。

### 3. 入口（用户已确认"是的"）
- 侧边栏「大纲总览」下方新增菜单项「正文阅读」
- 章节管理页顶部操作栏新增「正文阅读」按钮直达

### 4. 阅读体验标配（用户已确认一起做）
- **字号调节**：A- / A+ 调整正文字号，设置持久化（localStorage）
- **记住上次读到哪章**：再次进入页面自动恢复上次阅读的章节
- **目录当前章自动高亮**：切换章节时目录同步滚动/高亮
- **未生成章节占位**：无正文的章节显示"本章尚未生成"占位，不报错

## 技术方案

### 总体：后端小改（加参数）+ 前端新页面
- **后端**：`GET /chapters/project/{project_id}`（chapters.py L240）新增 query 参数 `include_content: bool = True`——默认 True 保持现状（章节管理/剧情分析等现有调用方零影响）；`include_content=False` 时响应 items 中 `content` 置 None，只返回目录元数据（几十 KB）
- **前端正文阅读页**：
  - 挂载时请求 `?include_content=false` 轻量目录 → 页面本地 state（**不使用全局 store / useChapterSync**，与章节管理页解耦）
  - 切换章节时请求单章接口 `GET /chapters/{id}`（已存在，chapters.py L307，返回含 content）→ 本地缓存 `Map<chapterId, content>` + **预加载下一章**（切章后提前请求第 N+1 章，翻章无感）
- 不新增接口、不写迁移、不改 schema（content 本就 Optional）

### 新增文件
- `frontend/src/pages/BodyReader.tsx`（新页面；`ChapterReader` 名字已被单章阅读器占用）

### 路由与入口改动
- `frontend/src/App.tsx`：lazy import `BodyReader` + 嵌套路由 `path="body-reader"`
- `frontend/src/pages/ProjectDetail.tsx`：
  - **两份菜单都要加**（代码证据：`menuItems` 展开版 L124 + `menuItemsCollapsed` 折叠版 L224，不是桌面/移动端之分）：均在「大纲总览」项下方新增「正文阅读」项（key: `body-reader`）
  - `selectedKey` 匹配逻辑增加 `/body-reader` 判断（与 `/chapters` 无前缀冲突，但需显式添加；参照 L314 的注释惯例）
- `frontend/src/pages/Chapters.tsx`：顶部操作按钮区（「导出为TXT」附近，L2355 起的 Space 按钮组）新增「正文阅读」按钮，`navigate('/project/{id}/body-reader')`

### 后端改动（小）
- `backend/app/api/chapters.py` `get_project_chapters`：新增参数 `include_content: bool = True`；为 False 时构造 chapter_dict 时 `content` 置 None（其余字段照常）
- `backend/app/schemas/chapter.py`：无需改动
- 默认行为不变 → 其他页面零影响
- 部署：按项目常规流程 `docker cp backend/app mumuainovel:/app/ && docker restart mumuainovel`

### 数据流（目录/正文分离，关键可靠性要求）
- **目录加载**：挂载时请求 `GET /chapters/project/{projectId}?include_content=false` → 本地 state `toc`（含 id / chapter_number / title / word_count / outline_id / outline_title / outline_order / status，无正文）。从侧边栏直接进入时也能独立工作，不依赖「先访问过章节管理页」
- **正文加载**：切换章节时请求 `GET /chapters/{id}` → 写入本地缓存 Map（同章不重复请求）；**预加载下一章**（切章后提前请求第 N+1 章正文，翻章无感）
- 章节排序**页面内自行兜底**：`[...toc].sort((a,b) => a.chapter_number - b.chapter_number)`（Chapters.tsx L696 同款惯例）
- 目录分组复用 Chapters.tsx L690-720 同款逻辑：`key = outline_id || 'uncategorized'`，标题 `outline_title || '未分类章节'`，组排序 `outline_order ?? 999`
- **空章节判断以 `content` 为空为准**（`chapter.content ?? ''` 为空即占位），**不可依赖 `status` 字段**：前端类型 `status: 'draft'|'writing'|'completed'`（types/index.ts L537）与后端真实枚举（7 种：draft/pending/running/completed/failed/awaiting_review/rewriting_rollback）不一致
- 上一章/下一章**不需要 navigation API**：用 toc 本地计算（`chapter_number ± 1` 前后项），避免额外请求

### 页面布局

```
┌────────────────────────────────────────────────────┐
│ ←返回  上一章 │ 第3章 尘封的标本室 · 2.3万字 │ 下一章  A- A+ │ ← 顶部工具栏
├────────────────────────────────┬───────────────────┤
│                                │ 目录 ☰（可折叠）    │
│   单页显示当前章全部正文         │ ┌ 第一卷          │
│   （居中，阅读栏宽，行距2，      │ │ 第1章 回响与手术刀│
│    白字深底，沿用主题 token）    │ │ 第2章 …         │
│                                │ └ 第二卷          │
│                                │  第3章 ← 当前高亮  │
└────────────────────────────────┴───────────────────┘
```

- 顶部工具栏（sticky）：返回、上一章/下一章（带章名 tooltip）、当前章标题+字数、A-/A+ 字号按钮
- 内容区：`maxWidth ~800px` 居中，标题行 + 正文（`whiteSpace: pre-wrap`，`lineHeight: 2`，字号受 A-/A+ 控制，默认 16px，范围 14–22）
- 右侧目录栏：宽 ~280px，`borderLeft` 分隔；按 `outline_order` 分组（卷标题），组内按 `chapter_number` 排序；无 `outline_id` 的章节归入「未分组」放最后；当前章高亮（`colorPrimary` 背景/文字），`activeChapterId` 变化时滚动到该目录项
- 移动端（≤768px）：目录收进右侧 Drawer，工具栏简化
- 空章节：`content` 为 null/空时正文区显示占位文案"本章尚未生成，请到「章节管理」生成"（基于 content 判空，见数据流要求）

### 状态与持久化
- 当前章节 id 存 URL query（`?chapter=<id>`），刷新/分享可直达
- 进度记忆：`localStorage` key `body-reader:progress:{projectId}` = 最近章节 id；进入页面时若存在则直接恢复该章（首页无则第一章）；每次切换章节更新
- 字号：`localStorage` key `body-reader:font-size`（默认 16）
- 章节切换时内容区滚动回顶部

### 目录分组兼容
- `outline_mode === 'one-to-one'`（大纲即章节）时仍按卷分组展示（与大钢总览的卷标签逻辑一致），无特殊分支

## 验证清单

1. 后端：`GET /chapters/project/{id}?include_content=false` 返回 items 中 content 为 null、其余字段完整；不带参数时仍返回全文（其他页面不受影响）
2. 侧边栏出现「正文阅读」菜单项（展开+折叠两份菜单），路由 `/project/:projectId/body-reader` 可访问且菜单高亮正确
3. 章节管理页顶部「正文阅读」按钮点击进入该页
4. 右侧目录按卷分组展示全部章节，无大纲章节进「未分组」
5. 点击目录项 → 右侧正文切换为该章全文，目录该项高亮
6. 上一章/下一章正确跳转；第一章/最后一章时按钮置灰
7. A-/A+ 字号实时变化，刷新后保持
8. 关闭页面再进入 → 自动恢复到上次阅读的章节
9. 空章节（无 content）显示占位而非报错/空白
10. 连续翻章：已读章节不重复请求（缓存生效），下一章预加载生效
11. 移动端宽度下目录为抽屉，正文可读
12. 深色主题下颜色/边框与现有页面协调（用 antd token，无硬编码色值）
13. `npm run build` 通过（TS 类型检查）

## 明确不做（本次范围外）

- 记忆标注/分析入口（保持纯阅读）
- 书签/划线/笔记等阅读器高级功能
- 新后端接口（仅给现有列表接口加参数，不新增端点）

## 风险与已知限制

- 单章加载存在网络延迟 → 预加载下一章缓解；本地/内网部署几乎瞬时，公网部署几百 ms 内可接受
- 连续快速切章：用缓存 Map + 已加载判断避免重复请求；不做请求过期/取消（避免过度设计）
- URL query 恢复章节依赖章节 id 稳定（id 为 UUID，删除章节后 localStorage 中的旧 id 失效 → 回退到第一章，需在代码中兜底）
