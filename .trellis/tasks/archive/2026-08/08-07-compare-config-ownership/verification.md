# 验收记录：项目创作配置所有权

## 已完成

- 新增每项目一行的 `project_creation_configs`，保存章节/分析模型选择、Skill、风格、MCP 策略和创作参数。
- 配置 Schema 对未知字段使用 `extra=forbid`，API Key、MCP headers/env 等凭据不会进入配置。
- 配置读写始终经过项目权限校验；旧项目没有记录时从用户路由、项目默认风格和启用插件生成兼容读取结果。
- 模型、Skill、写作风格和 MCP 插件失效时返回明确错误，不静默换资源。
- 运行快照只记录资源 ID、名称、协议、模型和版本哈希，不包含密钥或连接参数。
- 新增运行快照接口，供后续 Pipeline 和副本创建使用。

## 自动验收

- 配置测试：5/5 通过。
- 容器 `compileall`：通过。
- PostgreSQL：`c9f8e269 (head)`。
- SQLite 本次迁移升级/回退：通过。
- 真实服务：`/health` 正常；新增配置相关 OpenAPI 路由 2 条。
- `git diff --check`：通过。

## 后续边界

项目副本深复制和独立修改由 `08-07-compare-project-clone` 负责；Pipeline 消费运行快照由 `08-07-compare-pipeline-foundation` 负责。本任务不复制任何全局资源密钥。
