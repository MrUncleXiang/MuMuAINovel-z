# PRD：数据层改造——章节状态枚举 + 流水线运行记录

> 任务：08-05-data-layer（P0）
> 来源：wayfinder 蓝图 `.scratch/auto-novel-pipeline/blueprint.md` 第七节
> 状态：in_progress

## 目标

为自动化小说生产流水线打好数据地基：
1. **章节状态升级为正式枚举**——新增流水线专用状态，代码中统一引用常量，不再散落字符串
2. **新增流水线运行记录表**——一本书一条运行记录（当前阶段、进度、配置快照、检查点历史、预算用量）

## 一、章节状态枚举

现有使用值（散落在代码中）：`draft / pending / running / completed / failed`

新增流水线状态：
| 状态 | 含义 |
|---|---|
| `awaiting_review` | 章节已生成完成，流水线停在检查点，等待人工审阅 |
| `rewriting_rollback` | 章节被回滚后正在重新生成（回滚机制任务使用） |

实现：在 `app/models/chapter.py` 增加常量类（如 `ChapterStatus`），代码统一引用。
`status` 列本身是 `String(20)`，无 DB 约束——**新增状态值无需数据库迁移**。

## 二、流水线运行记录表（novel_pipelines）

一本书一条（project_id 唯一）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | String(36) PK | |
| project_id | String(36) FK projects.id CASCADE, UNIQUE | 一本书一条流水线 |
| status | String(20) default `idle` | idle / running / awaiting_review / paused / completed / stopped / failed |
| current_stage | String(30) default `idle` | idle / book / chapter_loop / checkpoint / volume_transition / completed |
| current_outline_id | String(36) FK outlines.id SET NULL | 当前卷(Outline) |
| chapter_count | Integer default 0 | 已生成章节总数 |
| current_checkpoint_id | String(36) FK pipeline_checkpoints.id SET NULL | 当前挂起的检查点 |
| config_snapshot | JSON | 里程碑、每N章、每卷必停、各阶段模型/温度/token、预算（建书时快照，运行中变更时更新） |
| progress_json | JSON | 运行进度明细（阶段内进度等） |
| checkpoint_history | JSON | 检查点决策历史摘要（冗余，便于驾驶舱快速展示） |
| budget_used_tokens | Integer default 0 | 累计 tokens |
| budget_used_amount_cents | Integer default 0 | 累计估算金额（分） |
| last_error | Text nullable | 最近一次失败原因 |
| created_at / updated_at | DateTime | |

## 三、检查点记录表（pipeline_checkpoints）

支撑"回退到任意历史检查点"：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | String(36) PK | |
| pipeline_id | String(36) FK novel_pipelines.id CASCADE | |
| checkpoint_type | String(20) | every_n / volume_end / milestone / manual |
| trigger_chapter_number | Integer | 触发时的章节总数 |
| chapter_from / chapter_to | Integer nullable | 本次检查点覆盖章节范围 |
| status | String(20) default `pending` | pending / approved / rollback / stopped |
| decision | String(20) nullable | continue / rollback / stop |
| rollback_to_checkpoint_id | String(36) FK pipeline_checkpoints.id SET NULL | 回滚目标（回滚决策时记录） |
| decided_at | DateTime nullable | |
| created_at / updated_at | DateTime | |

## 四、迁移

- 生产（postgres）：新增 `alembic/postgres/versions/` 迁移，创建两表 + 唯一约束 + FK
- 开发（sqlite）：同步新增 `alembic/sqlite/versions/` 迁移（保持双库一致）
- 章节状态不涉及 schema 变更，无迁移

## 五、验收

1. `novel_pipelines`、`pipeline_checkpoints` 两表在 postgres 创建成功（alembic upgrade head）
2. ChapterStatus 常量可用，现有代码引用不受影响
3. 容器重启后 DB 迁移正常（alembic current = head）
