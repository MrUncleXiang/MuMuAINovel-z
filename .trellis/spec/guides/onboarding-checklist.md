# Onboarding / Health-Check Guide（接手与体检清单）

> **教训来源（2026-08-11）**：项目长期"使用中"的 Trellis 工作流其实从不完整——llms.txt、CONTEXT.md、Docs/architecture.md、Docs/adr/ 全部缺失，AGENTS.md 引用了不存在的 CONTEXT.md，`.trellis/spec/` 13 个文件仍是模板占位。根因：**一直在"用"，从没"审"**。"能跑"（task.py 可用、任务归档正常）≠ "完整"。
> 复盘记录见 trellis 任务 `08-11-onboarding-checklist`。

## 什么时候做体检

- 新设备 / 新 AI Agent 接入项目时（**必做**）
- 有新模板/参照物出现，或框架升级时（对照 diff）
- 每完成一批任务后（如每 10 个任务）顺手跑一次

## 体检清单（逐项验证，不是目测）

### 1. 文档真相源完整性

```bash
ls llms.txt CONTEXT.md Docs/architecture.md Docs/adr/README.md AGENTS.md
```

缺失任一 → 按 `~/project-scaffold/template/` 补齐（先摸后写，不编造）。

### 2. 交叉引用验证（引用必须指向真实文件）

```bash
# 找出所有文档里的相对引用，逐个验证存在性
grep -rhoE "\]\([^)]+\.md\)" AGENTS.md llms.txt CONTEXT.md Docs/ .trellis/ 2>/dev/null \
  | sed 's/](//;s/)//' | sort -u | while read f; do [ -e "$f" ] || echo "❌ 悬空引用: $f"; done
```

文档引用不存在的文件 = 文档失信，必须修。

### 3. spec 填充状态（占位即未完成）

```bash
grep -rl "To fill\|To be filled" .trellis/spec/ | wc -l   # 期望 0 或已登记 TODO
```

### 4. 工作流可运行性（各跑一遍）

```bash
python3 .trellis/scripts/task.py list          # 能列出任务
python3 .trellis/scripts/get_context.py        # 身份与工作流正常
python3 .trellis/scripts/task.py create "体检冒烟测试" --no-start  # 能建（测完删除/归档）
```

### 5. 构建入口真实性（文档写的命令必须真能跑）

对照 AGENTS.md / llms.txt 里的构建命令，抽查 1-2 个（如前端 build、后端语法检查）。

## 硬规则

- **"能用"不等于"完整"**：工作流运转正常时，更要主动检查"引用、占位、缺失文件"。
- **引用即承诺**：文档里出现路径/文件名，就是承诺它存在——写文档时顺手验证，读文档时顺手抽查。
- **先摸后写**：补文档时基于真实目录/版本/命令，不编造占位符内容。

## Trellis 注入失效排查（2026-08-12 事故）

**症状**：`<workflow-state>` 注入显示过时/错误的旧任务，AI 不按当前工作流行事。

**根因**：任务归档时 `clear_task_from_sessions()` 删除所有指向被归档任务的 session 文件——**包括当前活跃会话的指针**。归档后无自动重建，`task.py current` 走 single-session fallback 到残留孤儿文件（可能指向数天前的旧任务），注入持续错误。

**排查步骤**：
```bash
# 1. 当前解析到谁（注意 source 是否 session-fallback + context_key 是否过时）
python3 .trellis/scripts/task.py current --source
# 2. 当前会话 context key 是否正确
python3 -c "import sys; sys.path.insert(0,'.trellis/scripts'); from common.active_task import resolve_context_key; print(resolve_context_key())"
# 3. sessions 目录是否有当前会话文件
ls .trellis/.runtime/sessions/
```

**修复（归档最后一个活跃任务后必须执行）**：
```bash
# 1. 删除孤儿文件（fallback 锚点）
rm .trellis/.runtime/sessions/<旧会话id>.json
# 2. 重建当前会话空指针
python3 - <<'EOF'
import json
from pathlib import Path
import sys; sys.path.insert(0, '.trellis/scripts')
from common.active_task import resolve_context_key, _context_path
repo = Path.cwd()
key = resolve_context_key()
if key:
    p = _context_path(repo, key)
    p.write_text(json.dumps({"platform": "pi", "last_seen_at": "", "current_task": None, "current_run": None}, ensure_ascii=False) + "\n", encoding="utf-8")
    print("已重建:", p)


## Trellis 注入失效排查（2026-08-12 事故）

**症状**：<workflow-state> 注入显示过时/错误的旧任务，AI 不按当前工作流行事。

**根因**：任务归档时 clear_task_from_sessions() 删除所有指向被归档任务的 session 文件——包括当前活跃会话的指针。归档后无自动重建，task.py current 走 single-session fallback 到残留孤儿文件（可能指向数天前的旧任务），注入持续错误。

**排查步骤**：
```bash
# 1. 当前解析到谁（注意 source 是否 session-fallback + context_key 是否过时）
python3 .trellis/scripts/task.py current --source
# 2. 当前会话 context key 是否正确（应显示 pi_<当前会话id>）
python3 -c "import sys; sys.path.insert(0,'.trellis/scripts'); from common.active_task import resolve_context_key; print(resolve_context_key())"
# 3. sessions 目录是否有当前会话文件
ls .trellis/.runtime/sessions/
```

**修复（归档最后一个活跃任务后必须执行）**：
```bash
# 1. 删除孤儿文件（fallback 锚点）
rm .trellis/.runtime/sessions/<旧会话id>.json
# 2. 重建当前会话空指针（current_task 空 = no task）
python3 -c "
import sys, json
from pathlib import Path
sys.path.insert(0, '.trellis/scripts')
from common.active_task import resolve_context_key, _context_path
key = resolve_context_key()
if key:
    p = _context_path(Path.cwd(), key)
    p.write_text(json.dumps({'platform':'pi','last_seen_at':'','current_task':None,'current_run':None}, ensure_ascii=False) + chr(10), encoding='utf-8')
    print('已重建:', p)
"
# 3. 验证（应返回 Current task: (none)）
python3 .trellis/scripts/task.py current --source
```
