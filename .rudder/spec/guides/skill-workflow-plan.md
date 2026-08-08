# 技能体系审查与流程修改方案（Skill System Review & Plan）

> 状态：待决策（方案已定，三个决策点待用户拍板，未实施）
> 创建：2026-08-08
> 背景：用户希望改善写作 SKILL 使用体验，考虑引入网文工坊（chinese-webnovel-skills）34 个技能

---

## 一、现状审查（代码事实，2026-08-08 核实）

### 1. SKILL 体系现状

| 项 | 事实 | 证据 |
|---|---|---|
| 内置技能 | 7 个（长篇/短篇·写作、拆文、扫榜、去AI味） | `backend/app/skills/` 目录 |
| 使用入口① | 章节生成【应用 SKILL】下拉，**单选**，注入系统提示词 | `chapters.py` 1444 行 `next(...)` 单技能注入 |
| 使用入口② | 技能聊天 SkillChat（`/api/skills/chat`），**单技能**对话 | `skills.py` /chat 端点 |
| 实际使用 | 7 个内置**从未被应用**（0 次注入记录） | 日志 `grep "已将 Skill"` = 0 |
| 技术限制 | `skill_key: Optional[str]` 单值（接口/UI 均为单值） | `schemas/chapter.py` 133/148/193 |

**结论**：单技能是当前实现限制（非架构必然）；可扩展为多技能（数组+拼接注入），但有代价（上下文膨胀、技能指令冲突）。

### 2. 提示词模板体系现状

| 项 | 事实 |
|---|---|
| 天命 4 个章节模板 | 已禁用（`is_active=false`），章节生成已恢复系统默认 |
| InkOS 3 个模板 | 已删除（无代码调用点，纯占位） |
| TIANMING_SYSTEM_ADDON | 已禁用 |
| 机制 | `PromptService.get_template` 全局自动覆盖（有用户模板即用，否则系统默认），无缓存 |

### 3. 用户使用心智

> 方式 A：选正文 / LLM 模型 / SKILL → 生成 → 看文本（生成时选技能）
> 方式 B：技能聊天（独立任务类技能，目前未使用）

---

## 二、目标

1. 让用户直接用到好用的写作技能（方式 A 为主）
2. 保持可控：技能显式选择，不做全局自动替换（吸取天命不可控教训）
3. 不破坏现有功能

---

## 三、流程修改方案（三部分，互相独立）

### 方案 A：安装网文工坊技能（内容层，最小改动）

- **A1（推荐先做）**：精选安装 8 个正文写作技能进【应用 SKILL】下拉：
  `expand`（扩写）、`cowrite`（续写）、`dialogue`（对话）、`emotion`（情绪）、`deslop`（去AI味）、`human`（人味）+ 2 个试用后决定
- **A2（可选）**：其余 26 个任务类技能（大纲/人设/审稿/取名等）全装，通过技能聊天使用（零开发）
- A1+A2 = 全装 34 个，一次到位

**网文工坊 34 个技能清单**（按流程分组）：

- 前期策划（8）：idea、spark、start、trends、title、name、world、outline
- 正文写作（10）：expand、cowrite、draft、dialogue、emotion、deslop、human、warmth、script、english
- 人设爽点（6）：character、goldfinger、hook、shuangdian、slang、fanfic
- 后期质检（7）：review、continuity、proofread、annotate、aidetect、deconstruct、submission
- 其他（3）：coach、memory、warmth（重复计入）

**依赖外部工具、纯提示词环境效果打折**：trends（平台实时数据）、slang（热梗查询）、draft（Word 导出）、memory（持久化档案）

### 方案 B：技能选择体验（开发层，可选）

- **B1（暂缓）**：多技能同时选择（接口改数组 + 注入拼接 + 前端多选）。技术上可行，但建议暂缓：技能内容数千字，多个同时注入挤占正文空间、指令冲突。
- **B2（暂缓）**：技能下拉显示优化（分组/说明更清晰）。

### 方案 C：模板管理（治理层，可选）

- **C1**：天命模板恢复做成页面开关（`is_active` 开关），用户可随时对比"默认 vs 天命"
- **C2**：维持禁用现状

---

## 四、验证方式（每步实施后）

1. 安装后：`/api/skills/list` 返回数量确认
2. 用 `expand` 技能实际生成一章，对比效果
3. 技能聊天里试 `outline` / `review` 等任务技能
4. 若做 C1：开关切换后 `get_template` 返回内容变化确认

---

## 五、待决策点

| # | 问题 | 选项 |
|---|---|---|
| 1 | 装多少技能 | A1 精选 8 个 / A2 全装 34 个 |
| 2 | 多技能选择（B1） | 暂缓 / 纳入开发 |
| 3 | 天命恢复开关（C1） | 做 / 维持禁用 |

---

## 六、执行纪律

- 决策后按 Rudder 流程建任务 + prd 再实施（AGENTS.md 硬规则）
- 实施每步做真实验证
