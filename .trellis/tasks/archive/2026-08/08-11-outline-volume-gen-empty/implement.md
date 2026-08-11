# Implement — 写这卷正文：空卷误报修复

## 变更

文件：`source/frontend/src/pages/Outline.tsx`（函数 `handleVolumeGenerate`，约 L166）

在获取章节列表后、计算 pending 之前新增守卫：

```ts
// 卷还没有任何章节（从未展开）：不能直接写正文，提示并引导先展开
if (!res.has_chapters || chapters.length === 0) {
  message.warning(`《${outline.title}》还没有章节，请先点击「展开」把大纲展开成章节，再写正文`);
  void handleExpandOutline(outline.id, outline.title);
  return;
}
```

## 行为变化

| 场景 | 修复前 | 修复后 |
|---|---|---|
| 卷无任何章节 | 误报"各章节都已有内容，无需生成" | 提示"还没有章节"+ 自动弹出展开窗口 |
| 章节全写完 | "无需生成" | 不变 |
| 中间有已写章节 | 提示仅连续生成未写部分 | 不变 |

## 验证

- `npx tsc -b` → EXIT 0
- `NODE_OPTIONS="--max-old-space-size=4096" npm run build` → 成功（默认堆 512MB 会 OOM，必须加大）
- 新产物：`backend/static/assets/Outline-DFs588lz.js`，含"还没有章节"文案与 `handleExpandOutline` 调用
- 容器 `/app/static`（bind-mount）已可见新文件；`curl http://127.0.0.1:19000/assets/Outline-DFs588lz.js` → 200

## 部署

静态目录 bind-mount 进容器，构建即生效，无需重启/重建镜像。用户强刷页面即可验证。

## 教训（已同步到 spec 候选）

"数据为空"与"数据全完成"必须区分：先判断集合是否为空，再判断是否全部完成。类 vacuous-truth 误判。
