# Design：大纲生成接入 SKILL

## 边界

- 后端：`schemas/outline.py`、`services/skill_loader.py`、`api/outlines.py`、`services/outline_comparison_service.py`、`api/chapters.py`（顺手统一公共函数）。
- 前端：`pages/Outline.tsx`（生成弹窗加「应用 Skill」下拉）。
- 无数据库改动；SKILL 仍单选；不改变生成产物结构（JSON 入库）。

## 1. 公共注入函数（skill_loader.py）

```python
def build_skill_system_prompt(skill_key: Optional[str]) -> Optional[str]:
    """根据 skill_key 构造 Skill 系统提示词；未找到返回 None。"""
    if not skill_key:
        return None
    skills = get_all_skills_cached()
    skill = next((s for s in skills if s["template_key"] == skill_key), None)
    if not skill:
        return None
    return (
        f"【⚡ Skill 工作流：{skill['template_name']}】\n\n"
        f"{skill['content']}\n\n"
        "⚠️ 请严格遵循上述 Skill 工作流指令进行创作！"
    )
```

- `chapters.py` 1440-1463 行替换为调用本函数（行为完全一致：日志保留在调用侧）。
- 日志：调用侧统一打 `logger.info(f"⚡ 已将 Skill '{name}' 注入系统提示词（{len}字符）")`；未找到打 warning。为便于验收，大纲路径也保留同样日志。

## 2. Schema

`OutlineGenerateRequest` 增加：

```python
skill_key: Optional[str] = Field(None, description="Skill 标识，指定后以该 Skill 的工作流指导大纲生成")
```

`OutlineComparisonCreateRequest` 继承自动获得；比较模式下后端将同一 `skill_key` 用于每个候选。

## 3. 注入点（重点：8 处生成调用，含重试分支）

> **审查修正（2026-08-09）**：四条生成函数在 JSON 解析失败时均有**第二次生成调用**（retry_prompt 重试分支，已核实 `api/outlines.py` 1231/1691 行及后台任务 retry 循环），重试不传 system_prompt 会导致 SKILL 失效。**system_prompt 在函数顶部统一构造一次，所有生成调用（含重试）都传**。

| 路径 | 文件/函数 | 生成调用数 | 改动 |
|---|---|---|---|
| SSE 流式-全新 | `api/outlines.py` `new_outline_generator` | 2（首+重试） | `data.get("skill_key")` → `build_skill_system_prompt` → 每次 `generate_text_stream(system_prompt=...)` 都传 |
| SSE 流式-续写 | `api/outlines.py` `continue_outline_generator` | 2（首+重试） | 同上 |
| 后台任务-全新 | `api/outlines.py` `_run_new_outline_bg` | 2（首+重试循环） | 同上（task_input dict 取 `skill_key`） |
| 后台任务-续写 | `api/outlines.py` `_run_continue_outline_bg` | 2（首+重试循环） | 同上 |
| 多模型比较 | `services/outline_comparison_service.py` `generate_outline_candidate` | 1 | **从 `batch.input_snapshot["request"]["skill_key"]` 取**（候选生成时无 payload 对象，已核实；batch 创建时 `payload.model_dump(exclude={"selections","provider_config_id","model","provider"})` 不含 skill_key 排除项，会自动存入 snapshot）→ 构造 system_prompt → `service.generate_text(system_prompt=...)`（generate_text 支持 system_prompt 参数，已核实） |

- 未找到 SKILL 或未指定：`system_prompt=None`，与现状完全一致。
- 未找到 SKILL 时打 warning 但**不阻断生成**。
- 比较模式请求 `create_outline_comparison_batch` 已接收完整 `OutlineComparisonCreateRequest`（顶层字段），无额外改动。

## 4. 前端（Outline.tsx 生成弹窗）

- 新建公共组件 `components/SkillSelector.tsx`（**子任务 3 的编辑/创建弹窗复用，避免重复实现**）：
  - 加载 `availableSkills`（`/api/skills/list`，复用 Chapters 的加载方式）；
  - 受控 props：`value/onChange/disabled`；
  - UI：placeholder「不使用 Skill（标准创作）」、allowClear、showSearch、option 显示名称+分类 Tag、选中后绿色描述行；
  - `outline` 置顶 + 「推荐」Tag（前端排序即可，不改后端 list 顺序）。
- 生成弹窗：在「生成方式」Segmented 下方加「应用 Skill」`Form.Item`（两种模式都显示）。
- 提交：单模型模式 `generateForm` 增加 `skill_key` 字段；比较模式提交 body 顶层带 `skill_key`（`handleGenerateComparison` 的请求对象加字段）。

## 兼容性 / 回滚

- 未选 SKILL：所有路径 `skill_key=None`，行为零变化。
- 回滚：后端+前端一次提交，`git revert`。
- 风险点：`generate_text_stream` 的 `system_prompt` 参数在各路径调用点已存在（章节在用），大纲路径为新增参数，需逐个核对调用签名（`provider`/`model`/`auto_mcp` 参数已存在）。

## 验证方式

1. 后端日志：三种模式各生成一次，grep `已将 Skill` / `未找到 Skill`。
2. 产物校验：`_parse_ai_response` 成功（前端大纲列表出现新卷）。
3. 不选 SKILL 生成一次，确认无注入日志、行为不变。
