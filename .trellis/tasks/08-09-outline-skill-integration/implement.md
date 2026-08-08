# Implement：大纲生成接入 SKILL

> 前置：子任务 1（模型入口统一）已合入 main；`git checkout -b feat/outline-skill-integration`。

## 执行清单（按序）

- [ ] 1. `services/skill_loader.py`：新增 `build_skill_system_prompt(skill_key)` 公共函数（格式见 design §1）。
- [ ] 2. `api/chapters.py`：1440-1463 行改为调用公共函数（日志保留在调用侧），跑一遍章节生成冒烟确认行为不变。
- [ ] 3. `schemas/outline.py`：`OutlineGenerateRequest` 加 `skill_key` 字段。
- [ ] 4. `api/outlines.py`（**注意：每条函数 2 次生成调用——首次 + 重试分支——都要传 system_prompt，在函数顶部统一构造**）：
  - [ ] 4.1 `new_outline_generator`：首+重试两处 `generate_text_stream` 都传 `system_prompt`，并加注入/未找到日志
  - [ ] 4.2 `continue_outline_generator`：同上
  - [ ] 4.3 `_run_new_outline_bg`：同上（task_input 取 skill_key，重试循环内也要传）
  - [ ] 4.4 `_run_continue_outline_bg`：同上
- [ ] 5. `services/outline_comparison_service.py`：`generate_outline_candidate` 从 `batch.input_snapshot["request"].get("skill_key")` 取（**不是 payload，候选生成时无 payload 对象**）→ `service.generate_text(system_prompt=...)`。
- [ ] 6. 前端：
  - [ ] 6.1 新建 `components/SkillSelector.tsx` 公共组件（加载/渲染/outline 置顶+推荐；子任务 3 复用）
  - [ ] 6.2 生成弹窗「生成方式」下方加「应用 Skill」Form.Item（两种模式都显示）
  - [ ] 6.3 单模型模式：`generateForm` 加 `skill_key`，提交携带
  - [ ] 6.4 比较模式：`handleGenerateComparison` 请求 body 顶层加 `skill_key`
- [ ] 7. 验证：
  - [ ] 7.1 后端日志：单模型选 SKILL 生成 → 出现「已将 Skill」；不选 SKILL → 无注入日志
  - [ ] 7.2 后台任务模式同样验证
  - [ ] 7.3 比较模式：日志中每个候选均注入
  - [ ] 7.4 生成产物可入库（大纲列表出现新卷，结构字段完整）
  - [ ] 7.5 前端 typecheck/build 通过
- [ ] 8. 提交 commit：`feat(outline): 大纲生成支持应用 SKILL（三条路径注入）`

## 验证命令

```bash
# 后端日志（部署环境）：
grep "已将 Skill" /home/ubuntu/MuMuAINovel/logs/*.log | tail
grep "未找到 Skill" /home/ubuntu/MuMuAINovel/logs/*.log | tail

# 前端
cd /home/ubuntu/MuMuAINovel/source/frontend && npm run build
```

## 回滚点

- 步骤 1-2 完成即一次可运行状态（行为不变）。
- 步骤 4-5 完成一个路径可独立验证。
- 异常时 `git reset --hard HEAD` 或 revert 本分支 PR。
