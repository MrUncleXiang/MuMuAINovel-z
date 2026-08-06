# Journal - MrUncleXiang (Part 1)

> AI development session journal
> Started: 2026-07-27

---



## Session 1: 多 LLM 候选比较基础能力

**Date**: 2026-07-27
**Task**: 多 LLM 候选比较基础能力
**Branch**: `main`

### Summary

完成双数据库表、用户隔离 API、状态/重试/采用/并发服务，以及前端多选器和候选卡片；已构建和迁移验证。

### Git Commits

| Hash | Message |
|------|---------|
| `9a6b3ad` | (see git log) |

### Status

[OK] **Completed**


## Session 2: 章节多 LLM 候选比较

**Date**: 2026-07-27
**Task**: 章节多 LLM 候选比较
**Branch**: `main`

### Summary

完成同输入冻结、2至4模型并发候选、失败重试、编辑复制、双结果差异和事务化采用；正式章节仅在确认采用时修改。

### Git Commits

| Hash | Message |
|------|---------|
| `14c1d54` | (see git log) |

### Status

[OK] **Completed**


## Session 3: 大纲多 LLM 候选比较

**Date**: 2026-07-27
**Task**: 大纲多 LLM 候选比较
**Branch**: `main`

### Summary

完成大纲同输入候选、比较重试和安全采用；有正文的下游章节会阻止替换正式大纲。

### Git Commits

| Hash | Message |
|------|---------|
| `HEAD` | (see git log) |

### Status

[OK] **Completed**


## Session 4: 分析多 LLM 候选比较

**Date**: 2026-07-27
**Task**: 分析多 LLM 候选比较
**Branch**: `main`

### Summary

完成无副作用分析候选、差异查看、重试和冲突检测采用；生成阶段不写正式分析及实体副作用表。

### Git Commits

| Hash | Message |
|------|---------|
| `HEAD` | (see git log) |

### Status

[OK] **Completed**


## Session 5: 多 LLM 候选比较整体交付

**Date**: 2026-07-27
**Task**: 多 LLM 候选比较整体交付
**Branch**: `main`

### Summary

四个子任务完成；前后端与迁移检查通过，已备份 PostgreSQL、迁移到 d8f1b620，并将 19000 切换至 comparison-e383ad3 镜像，健康检查正常。

### Git Commits

| Hash | Message |
|------|---------|
| `e383ad3` | (see git log) |

### Status

[OK] **Completed**


## Session 6: OpenAI Responses API 渠道支持

**Date**: 2026-07-27
**Task**: OpenAI Responses API 渠道支持
**Branch**: `main`

### Summary

新增渠道级 wire_api，支持 Responses 普通、SSE 和函数工具调用；完成 PostgreSQL/SQLite 迁移、测试、备份与 19000 端口部署，vc-grok 和 hubway 均通过应用内连接测试。

### Git Commits

| Hash | Message |
|------|---------|
| `775c06d` | (see git log) |

### Status

[OK] **Completed**


## Session 7: 改进 LLM 渠道测试反馈

**Date**: 2026-07-27
**Task**: 改进 LLM 渠道测试反馈
**Branch**: `main`

### Summary

将 LLM 渠道测试专用超时延长到 5 分钟，增加行内最近测试状态、耗时和结果，保留上游 HTTP 错误正文并取消重复测试弹窗；完成构建、9 条测试和 19000 端口部署。

### Git Commits

| Hash | Message |
|------|---------|
| `5f8c659ec757eea94c0c0a8b64ef2d9d60e05414` | (see git log) |

### Status

[OK] **Completed**

---

## 2026-08-06 经验：建书/测试数据完整性（"图省事"教训）

**问题**：用 API 建《暗潮香江-DeepSeek对比测试》书时只传了 title/genre/theme，漏了 description 和世界观/角色。后果：① 点进项目被拉回向导页报"缺必需参数"；② DeepSeek 写正文时没有世界观/角色可参考（裸写）；③ 对比不公平（同标题不同设定）。

**根因**：a) 建项目字段不全无兜底；b) 流水线 BOOK 阶段"有大纲就跳过补全世界/角色"的逻辑漏洞；c) 对比测试复制数据不完整。

**修复（机制层）**：
- start_pipeline 启动即标记 wizard_status=completed + description 用 theme 兜底
- BOOK 阶段无论有无大纲都检查并补全世界设定/角色（_generate_world_and_characters）
- 世界设定 4 字段缺失重试 3 次 + 兜底值，绝不留空
- 对比测试书补齐原版世界观 + 93 个角色

**沉淀**：`.rudder/spec/guides/pipeline-data-integrity-guide.md` + AGENTS.md 规则 + 本日志。
