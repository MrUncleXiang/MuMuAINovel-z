# 修复：写这卷正文对未展开卷误报无需生成

## Goal

大纲页点击某卷【写这卷正文】时，若该卷**一个章节都没有**（从未展开），当前会误提示"《X》各章节都已有内容，无需生成"并直接返回，弹窗不打开，用户无法继续。

## 背景与根因

- 数据：项目《替死者言》第2卷《尘封的标本室》(outline_id=63f3d820-3d34-49c8-be00-fcf2cfb1c9f5) 在 `chapters` 表中 0 行；全部 5 个已完成章节都属于第1卷。
- 日志：`GET /api/outlines/63f3d820-.../chapters` → 200 OK，返回 `{has_chapters: false, chapters: []}`。
- 根因：`frontend/src/pages/Outline.tsx` 的 `handleVolumeGenerate` 只按"未生成章节"集合 `pending` 是否为空判断。`chapters` 为空数组时 `pending` 恒为空，与"章节全写完"落入同一分支，误报"无需生成"。该函数缺少对 `res.has_chapters === false` 的检查（同文件 `handleExpandOutline` 等都有该检查）。

## Requirements

1. 卷无任何章节时（`!res.has_chapters || chapters.length === 0`），不得提示"无需生成"。
2. 此时提示用户该卷尚未展开为章节，并引导/自动打开"展开大纲为多章"流程。
3. 卷有章节且全部写完时，保留原有"无需生成"提示。
4. 卷有章节且中间有已写章节时，保留原有"仅连续生成未写部分"提示。

## Acceptance Criteria

- [x] 对未展开卷点击【写这卷正文】：出现提示"还没有章节，请先点击「展开」…"，并自动弹出"展开大纲为多章"窗口。
- [x] 对已写完卷：仍提示"各章节都已有内容，无需生成"。
- [x] `tsc -b` 通过；前端构建成功；容器内 `/app/static/assets/Outline-DFs588lz.js` 含新逻辑，线上 200 可访问。

## Notes

- 部署方式：`cd source/frontend && NODE_OPTIONS="--max-old-space-size=4096" npm run build`，产物写入 `backend/static`（bind-mount 进容器 `/app/static`），无需重启服务，用户刷新即生效。
