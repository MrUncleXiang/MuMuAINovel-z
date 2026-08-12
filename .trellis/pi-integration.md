# Trellis × Pi 集成说明

让 pi 会话自动触发 Trellis 工作流（每轮注入 `<workflow-state>` 面包屑 + 当前任务），
对应其他平台（Codex 等）的 UserPromptSubmit hook。

## 扩展文件

```
~/.pi/agent/extensions/trellis-workflow/index.ts
```

行为（`before_agent_start`，每次用户发消息时）：

1. 确定项目根：`TRELLIS_ROOT` 环境变量优先；否则从当前会话 cwd 向上查找 `.trellis/workflow.md`
2. 解析 active task（`.trellis/scripts/task.py current --source`）+ `task.json` 的 status
3. 解析 `workflow.md` 中 `[workflow-state:STATUS]` 面包屑
4. 把 `<workflow-state>...</workflow-state>` 追加到系统提示

非 Trellis 项目：静默不注入。

## 启用步骤

1. 确认扩展文件已存在（本文件同目录无关联，扩展在用户主目录）
2. 在 pi 里执行 `/reload`（热加载扩展），或重启 pi
3. 触发方式二选一：
   - **推荐**：在项目目录启动 pi
     ```bash
     cd /home/ubuntu/MuMuAINovel/source && pi
     ```
     （会话 cwd = 项目根 → 自动发现 `.trellis`）
   - **固定项目**：在 `~/.bashrc` 或启动命令加
     ```bash
     export TRELLIS_ROOT=/home/ubuntu/MuMuAINovel/source
     ```
     （任何 cwd 启动的 pi 都会注入本项目 Trellis 状态；适合固定项目工作流）

## 验证

- 在项目目录启动 pi 后，应看到通知：`Trellis workflow 已就绪：<项目根>`
- 之后每轮系统提示中带 `<workflow-state>` 块，AI 会按当前状态行事：
  - `Status: no_task` → AI 先询问是否创建任务（`task.py create`）
  - `Task: xxx (planning)` → AI 停留在规划阶段（写 prd.md / design.md / implement.md）
  - `Task: xxx (in_progress)` → AI 进入实现 + 检查流程
- 主动查询：`python3 ./.trellis/scripts/task.py current --source`

## 说明

- pi 无 `/cd` 命令，会话目录 = 启动时的工作目录（`pi -c` 继续最近会话也是同一目录）。
- 在非 Trellis 目录（如 `~/pi-cwd-*`）启动的会话不会注入，属预期行为。
- 扩展与 Trellis 脚本解耦：只调用 `task.py` 并解析 `workflow.md`，不依赖其他平台脚本。
