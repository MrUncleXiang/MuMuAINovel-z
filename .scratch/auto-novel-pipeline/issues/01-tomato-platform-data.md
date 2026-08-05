# 番茄小说热门题材数据获取方式

Type: research
Status: resolved

## Question

番茄小说（fanqienovel.com）是否有公开 API 可获取榜单/热门题材数据？如果没有公开 API，通过网页爬取是否可行（反爬强度、法律风险）？可获取的数据字段有哪些（榜单排名、标签/分类、热度指标、读者评论数、趋势数据等）？哪些字段对我们的"热门题材一键开书"有实际价值？

## Answer

**结论：全网不存在公开的小说榜单 API。（搜索范围：GitHub ×5、Gitee ×3、PyPI、npm、public-apis、Kaggle、豆瓣 API、NovelUpdates）**

- 番茄小说（fanqienovel.com）：SPA，数据走字节内部网关，无公开 API。
- 起点中文（qidian.com）：同样无公开 API，GitHub/Gitee 上没有可用的爬虫项目。
- 豆瓣 Books API v2：已关闭（返回 "Bad Request"）。
- NovelUpdates（novelupdates.com）：Cloudflare 防护，无法自动化访问。
- public-apis 仓库（45 万星，收录所有已知免费 API）：书籍/小说分类**没有任何条目**。

**有价值的发现：**
- **[NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)**（6 万星 Python）：小红书/抖音/B站/微博/知乎的爬虫集合。技术上是成熟的——说明中国平台的爬虫是做得到的——只是还没有人专门为小说平台写。
- **[firecrawl/firecrawl](https://github.com/firecrawl/firecrawl)**（16 万星）：AI 驱动的通用网页抓取工具，可以"理解"任意网页并提取结构化数据，无需手写解析规则。理论上可以用来从任何小说网站提取榜单/标签/热度——但需要 API 付费额度。

**实际可行的路径（更新，按推荐优先级）：**

1. **手动种子 + AI 分析（推荐 MVP 首选）**：你手动给几个感兴趣的小说链接/标题 → AI 分析共性（标签、题材公式、世界观模板）→ 生成"热门题材模板库"。零基础设施、零维护、当下就能用。这是"一键生成热门主题小说"功能的最小闭环。

2. **firecrawl 一次性数据采集**：用 AI 爬虫工具做一次性的番茄/起点榜单采集（不是持续监控，而是"取一次当前热门榜、生成模板库"），之后用户从模板库选题材。比方案 1 更"自动化"的感觉，但需要 firecrawl API 额度（有免费额度）。

3. **自建爬虫（MediaCrawler 路线）**：长期维护一个针对番茄/起点的爬虫——技术可行但维护成本高，适合流水线成熟后作为增强功能，**不放入蓝图 MVP 范围**。

**最终决定：选 B（firecrawl 一次性采集 + 模板库）。**

- 用 firecrawl 对目标平台（番茄/起点等）做一次性热门榜单采集
- 采集结果存为"题材模板库"（每套模板含：题材名、标签、世界观公式、角色原型、常见卷结构）
- 用户在模板库里选一个 → 一键开书 → 进入流水线
- 模板库不需要持续更新（手动触发刷新即可，管几个月）
- 实现依赖（firecrawl API 额度、目标榜单 URL、模板数据结构）——在 grilling-04 中细化。

---
Resolved. 全网无公开小说榜单 API；选择 firecrawl 一次性采集 + 模板库方案。
