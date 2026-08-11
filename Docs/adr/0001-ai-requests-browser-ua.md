# 1. AI 请求统一携带浏览器 UA

日期：2026-08-11

## 状态

接受

## 背景

章节分析间歇性失败（连续 6 次尝试：空响应、输出截断、无效 JSON、524 超时）。初期误判为 deepseek-v4-flash "模型弱、长 JSON 不稳定"并临时改路由到 pro。深入排查后发现：OpenCode Go 服务商位于 Cloudflare 之后，Cloudflare 按请求 UA 指纹拦截无 UA / 编程客户端 UA（`python-httpx/...`）的请求（HTTP 403 code 1010），拦截为间歇性，症状恰好与"模型不稳定"完全一致。

## 决策

- `httpx.AsyncClient`（`app/services/ai_clients/base_client.py`）统一携带浏览器 UA（Chrome 131 指纹），对所有 provider 生效。
- 新增 spec 约定：禁止移除 UA、禁止无 UA 的直连请求；AI 失败排查"先查传输层再归咎模型"。

## 备选方案

- 临时把分析路由改到 pro 模型（只是规避，未解决根因；且用户默认配置是 flash，成本更高）→ 未采纳为主方案。
- 在请求层加重试——治标不治本。

## 后果

正面：flash 模型连续 3 次完整章节分析成功；所有 AI 调用稳定性提升（524/空响应/截断消失）。
负面：依赖"浏览器 UA"这一与上游 Cloudflare 规则的耦合，上游收紧规则可能再次失效（已写入 spec 便于再排查）。
