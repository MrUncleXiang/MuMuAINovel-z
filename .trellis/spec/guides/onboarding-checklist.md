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
