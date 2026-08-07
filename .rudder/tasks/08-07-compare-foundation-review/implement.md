# 实施计划：对比创作底座整改

## 执行规则

- 每次只启动一个子任务；前一个子任务通过检查并提交后再启动下一个。
- 每个提交只做一种可独立解释的行为变化，并保持应用可构建、数据库可升级。
- 涉及迁移的任务同时维护 PostgreSQL 与 SQLite，先备份真实 PostgreSQL。
- 发现 PRD 假设错误时退回 planning 修订文档，不在代码中临时发明产品规则。
- `code_auto_commit` 未开启，每次提交前展示差异和提交信息并取得用户确认。

## 阶段与提交组

1. 清理错误原型，不提供半成品入口。
2. 用特征测试固定普通生成/分析行为，再收敛正式章节生命周期。
3. 建立项目级创作配置并区分用户全局资源。
4. 整改 Pipeline，传递完整配置并等待分析。
5. 建立可靠章节状态检查点及失效规则。
6. 让多模型候选采用重新接回正式生命周期。
7. 实现支持两种模式的项目深复制。
8. 实现一次创建一本副本的 UI。
9. 进行源书/A/B 独立性和全链路总体验收。

## 全局验证命令

```bash
python3 -m compileall -q backend/app backend/alembic
PYTHONPATH=backend pytest -q backend/tests
cd backend && alembic -c alembic-sqlite.ini heads
cd backend && alembic -c alembic-postgres.ini heads
pnpm -C frontend exec tsc -b
pnpm -C frontend build
git diff --check
```

全仓库 ESLint 现有历史错误单独记录；本轮新增或修改文件不得增加错误。

## 总回滚策略

- 每个子任务独立提交，可按逆序回滚；
- 数据库迁移只做可逆新增，旧字段在整轮稳定前不删除；
- 新配置和检查点通过兼容读取逐步启用；
- Clone UI 最后开放，因此底座整改期间不会向普通用户暴露半成品流程。
