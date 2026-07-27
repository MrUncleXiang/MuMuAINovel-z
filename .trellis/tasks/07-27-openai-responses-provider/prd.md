# 支持 OpenAI Responses API 渠道

## Goal

让用户可以在“AI 服务管理”中明确选择 OpenAI 兼容渠道使用 Chat Completions 或 Responses API，使仅提供 `POST /v1/responses` 的渠道能够完成连接测试和实际创作，同时不影响现有渠道。

## Background

- 现有 OpenAI 客户端固定调用 `POST {base_url}/chat/completions`（`backend/app/services/ai_clients/openai_client.py:105`、`:150`）。
- `vc-grok` 配置为 `https://sub.vcnovb.cn/v1` 时，实测 `/models` 和 `/responses` 均返回 HTTP 200；`/chat/completions` 在应用日志中返回 HTTP 502。
- CC Switch 使用渠道级 `wire_api = "responses"` 区分线协议，Base URL 填版本根路径而不是完整接口地址。Responses 与 Chat 的请求体、响应体和 SSE 事件不同，不能只替换 URL。

## Requirements

1. OpenAI 兼容渠道增加 `wire_api` 字段，可选 `chat_completions` 和 `responses`。
2. 现有记录、旧版 Settings 和新建渠道默认使用 `chat_completions`，升级后 hubway 等现有渠道行为不变。
3. AI 服务管理页仅在 OpenAI 兼容协议下显示接口类型，并用大白话说明两者对应的接口路径。
4. Responses 模式发送 `POST {base_url}/responses`，使用 Responses 请求字段，并显式设置 `store: false`。
5. Responses 模式支持普通文本、SSE 流式文本、用量统计和当前 MCP 函数工具调用，向上层保持现有统一返回格式。
6. “测试”按钮按渠道所选 `wire_api` 发起最小生成请求；“同步模型”继续独立使用 `/models`。
7. API、数据库、前端类型和路由选择链路完整传递 `wire_api`，非法取值在 API 边界被拒绝。
8. PostgreSQL 和 SQLite 都提供可升级、可回滚的 Alembic 迁移。

## Acceptance Criteria

- [x] 未修改接口类型的既有 OpenAI 渠道仍请求 `/chat/completions`。
- [x] 将 vc-grok 设为 Responses、Base URL 设为 `https://sub.vcnovb.cn/v1` 后，页面连接测试成功并显示模型返回内容。
- [x] Responses 普通响应能解析文本、函数调用、完成原因和 token 用量。
- [x] Responses SSE 能逐段输出文本，并在完成时报告函数调用、完成原因和 token 用量。
- [x] 新建、编辑、读取渠道后 `wire_api` 值不丢失；Anthropic/Gemini 不受该字段影响。
- [x] PostgreSQL 与 SQLite 迁移均通过静态/升级检查，后端定向测试和前端构建通过。
- [x] 使用实际 vc-grok 渠道完成一次非流式和一次流式最小验证，日志中不泄露 API Key 或完整提示词。

## Out of Scope

- 不实现 Responses 与 Chat Completions 的自动双向代理转换。
- 不自动探测或静默切换 wire API，避免一次请求失败后重复计费或行为不确定。
- 不增加完整 URL 模式；本次仍采用 Base URL 加固定接口路径。
- 不新增模型推理强度、后台任务、内置联网搜索等 Responses 专属高级配置。
