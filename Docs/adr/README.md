# 架构决策记录（ADR）

> 重大架构决策按时间记录在此。每条 ADR 格式：状态 / 背景 / 决策 / 备选 / 后果。
> 新决策模板见 [0000-template.md](0000-template.md)。

## 记录表

| 编号 | 决策 | 日期 | 状态 |
|---|---|---|---|
| [0001](./0001-ai-requests-browser-ua.md) | AI 请求统一携带浏览器 UA（上游 Cloudflare 按 UA 指纹拦截） | 2026-08-11 | 接受 |
| [0002](./0002-chapter-review-pipeline.md) | 正文审查 3 步流水线 + 生成后自动审查（先审后析） | 2026-08-11 | 接受 |
| [0003](./0003-volume-review-as-report-only.md) | 卷检查只出报告不改文（跨章修改风险大，人工/按需 AI 修改） | 2026-08-11 | 接受 |
| [0004](./0004-content-hash-validity.md) | 分析任务绑定 content_hash，正文变更后过期结果一律丢弃 | 2026-08-11 | 接受 |
