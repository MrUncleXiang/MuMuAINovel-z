# PRD：题材模板库——firecrawl 自动采集版（P2）

> 任务：08-05-firecrawl（P2）
> 状态：设计完成，**待 firecrawl API Key 后实施**（MVP 已由手动种子版覆盖）

## 背景

手动种子版模板库已上线（08-05-theme-template-manual）。本任务是用 firecrawl
自动采集番茄/起点等平台榜单，向模板库填充更多热门题材。

## 设计

**firecrawl 简介**：AI 驱动网页抓取工具（16 万星），能理解网页并提取结构化数据。
需要 API Key（有免费额度）：`https://firecrawl.dev`

**采集流程**：
1. 用户配置 firecrawl API Key（设置页，存 Settings 表）
2. 目标平台榜单页 URL（番茄 `/rank`、起点排行等）
3. 后端调用 firecrawl `/scrape` 接口 → 提取榜单（书名/作者/标签/热度）
4. AI 批量分析榜单 → 提炼 N 套题材模板 → 存入 theme_templates（source="firecrawl"）
5. 手动触发刷新（不做持续自动爬取，MVP 边界）

**后端模块**：
- `app/services/firecrawl_service.py`：封装 firecrawl API 调用（httpx）
- `app/api/theme_templates.py` 增加：`POST /theme-templates/import-firecrawl`
  （body: { url, limit }，返回导入的模板数）
- Settings 增加 `firecrawl_api_key` 配置项

**前端**：
- 题材模板库页增加"自动采集"按钮（有 Key 才显示）
- 采集进度展示 + 结果确认（同手动版的分析确认交互）

## 验收标准

1. 配置 Key 后，POST /import-firecrawl 能从真实榜单页提取并生成模板
2. 模板以 source="firecrawl" 入库，与手动模板共存
3. 无 Key 时接口返回明确提示

## 阻塞项

- 需要 firecrawl API Key（用户申请：https://firecrawl.dev，免费额度即可）
- 需确认番茄/起点榜单页在 firecrawl 抓取下的实际结构（反爬可能影响）

## 结论

设计完成。MVP 不依赖本任务（手动种子版已可用）。拿到 Key 后按上述实施。
