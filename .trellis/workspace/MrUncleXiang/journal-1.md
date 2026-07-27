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
