# 大纲总览页（通读视图）

## Goal

新增一个独立的【大纲总览】页面，把一本书的所有卷大纲按顺序连续铺开，作者可以像读文档一样从头滚到尾通读一遍，检查故事逻辑与伏笔衔接。核心场景是"从头通读看逻辑"，不是目录式扫描。

## Background（现状事实）

- 后端 `GET /outlines/project/{project_id}` 已**全量返回**所有大纲（不分页），且每卷附带 `has_chapters`（布尔，是否已展开章节），但**没有章节数量**字段。
- 前端大纲管理页（`frontend/src/pages/Outline.tsx`）是"卷卡片 + 分页(20条/页) + 默认折叠"，卷多了以后无法连续通读。
- 侧边栏菜单在 `frontend/src/pages/ProjectDetail.tsx`（大纲管理 key=`outline`），路由在 `frontend/src/App.tsx:79`（`path="outline"`）。
- ⚠️ `ProjectDetail.tsx:303` 的菜单选中判断 `if (path.includes('/outline')) return 'outline';` 会**误匹配** `/outline-overview`，需修正。

## Requirements（已与用户确认）

1. 在左侧菜单【大纲管理】**下面**插入新菜单项【大纲总览】，独立页面入口。
2. 通读视图 = **纯阅读**，不带操作按钮（编辑/删除/写正文等），保持干净阅读体验；要改回"卡片管理"（原大纲页）。
3. **一次性加载全部卷，不分页**，按卷序号（order_index）顺序连续展示，从上滚到底。
4. 排版：每卷用**标题样式**（大字号）展示卷名，标题右侧/下方用小字号展示章节信息：
   - 已展开 → 显示"已展开 · N 章"（N = 该卷实际章节数）
   - 未展开 → 显示"未展开"（**不显示章节数**）
   - 注意：未展开的卷**照常显示大纲正文**，保证整本书只有大纲也能通读。
5. 章级内容（章节标题列表）**不展开显示**，只要个数。

## Technical Approach

### 后端（1 处小改）
`backend/app/api/outlines.py` 的 `get_outlines()`：现有 `has_chapters` 查询已按 `outline_id` 分组计数，把计数一并暴露为新字段（如 `chapter_count: int`），`has_chapters` 保持兼容（= count > 0）。影响面小，其他调用方不受影响。

### 前端
1. **新页面** `frontend/src/pages/OutlineOverview.tsx`：
   - 复用 `outlineApi.getOutlines(projectId)` 全量获取
   - 渲染：卷标题（大字号）+ 右侧小字（已展开 · N 章 / 未展开）+ 大纲正文（小字号，保持现有排版风格）
   - 卷与卷之间分隔线，顺序按 `order_index`
2. **菜单** `frontend/src/pages/ProjectDetail.tsx`：在 `key: 'outline'`（大纲管理）菜单项**之后**插入新菜单项（key=`outline-overview`，label 大纲总览，Link 到 `/project/${projectId}/outline-overview`，沿用现有图标风格）。
3. **路由** `frontend/src/App.tsx`：在 `path="outline"` 路由下新增 `<Route path="outline-overview" element={<OutlineOverview />} />`。
4. **菜单选中逻辑修正** `ProjectDetail.tsx:303`：`path.includes('/outline')` 会同时匹配 `/outline-overview`，改为先判断 `outline-overview` 再判断 `outline`（或精确匹配），保证两个菜单高亮互不干扰。

### 明确不做（Out of Scope）
- 不做章级折叠展开、不做编辑功能、不改原大纲管理页的卡片交互、不做导出/分享。

## Acceptance Criteria

- [ ] 左侧菜单【大纲管理】下方出现【大纲总览】入口，点击进入独立页面，路由为 `/project/{projectId}/outline-overview`。
- [ ] 页面一次性加载全部卷（20+ 卷也不分页），按卷序号连续展示，可从头滚动通读。
- [ ] 每卷以标题样式展示卷名；已展开的卷右侧小字显示"已展开 · N 章"（N 为该卷实际章节数）；未展开的卷显示"未展开"且无章节数。
- [ ] 未展开的卷大纲正文正常展示，不缺失。
- [ ] 通读视图无任何操作按钮（纯阅读）。
- [ ] 大纲管理页菜单高亮不受影响（选中【大纲总览】时【大纲管理】不高亮，反之亦然）。
- [ ] 后端 `chapter_count` 字段不破坏现有 `has_chapters` 兼容性；前端构建通过（npm run build）。

## Notes

- 保持 UI 沿用现有组件风格（antd，与 Outline.tsx 一致）。
- 后端返回的 `content` 可能来自 `structure` 解析（后端已在 get_outlines 中处理），前端直接使用即可。
- 建书数据完整性要求：本项目大纲数据多为演示数据，验收时注意卷数可能较少，可临时用真实项目验证。
