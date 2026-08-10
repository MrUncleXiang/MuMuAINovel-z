# Design：单条大纲 AI 润色与 AI 起草

## 边界

- 后端：`schemas/outline.py`（新增 2 个请求/响应模型）、`services/prompt_service.py`（2 个新系统模板 + 注册）、`api/outlines.py`（2 个新端点 + 提示词构造）。
- 前端：`pages/Outline.tsx`（编辑弹窗、手动创建弹窗各加 AI 操作区）。
- 无数据库改动；AI 结果一律不入库（只回填表单）。

## 1. 接口设计

### POST /api/outlines/{outline_id}/ai-edit（润色）

请求：
```json
{
  "instruction": "可选，润色方向，如：加强钩子、压缩篇幅、更贴合爽点节奏",
  "skill_key": "可选",
  "provider_config_id": "可选",
  "model": "可选"
}
```
响应：
```json
{ "title": "建议标题", "content": "建议内容" }
```

流程：
1. 校验大纲归属（`verify_project_access` 同现有端点）。
2. 构造上下文：项目信息（复用 `_build_outline_continue_context` 的 project_info 部分）+ 角色信息（`_build_characters_info`）+ 该大纲当前 title/content/structure + 前 2 条/后 2 条大纲的标题与概要 + 用户 instruction。
3. 模板 `OUTLINE_AI_EDIT`（`PromptService.get_template`，允许用户模板覆盖）→ `format_prompt`。
4. `build_skill_system_prompt(skill_key)`（子任务 2 公共函数）→ 若有，作为 `system_prompt` 传入。
5. `user_ai_service.generate_text(prompt=..., system_prompt=..., provider=..., model=...)`（非流式，一次性返回；后续可升级 SSE）。
6. **调用记录**：`AICallLog` 由 `ai_service.py` 242-248 行自动写入（AI 使用记录页可见，已核实），无需额外处理；另写一条 `GenerationHistory`（project_id/prompt/建议文本/model，与大纲生成记录一致），便于用户回看润色历史。
7. 解析返回：优先 JSON `{title, content}`；兜底按"标题行 + 正文"启发式拆分；解析失败返回 502 与原始文本供前端展示。
8. 响应返回建议值。

### POST /api/outlines/ai-draft（起草）

请求：
```json
{
  "project_id": "必填",
  "order_index": "可选，建议插入序号（默认 next）",
  "instruction": "可选，起草要求",
  "skill_key": "可选",
  "provider_config_id": "可选",
  "model": "可选"
}
```
响应：
```json
{ "order_index": 5, "title": "建议标题", "content": "建议内容" }
```

流程同润色，上下文差异：
- 插入位置前后各 2 条大纲（若指定 `order_index`）或末尾前 4 条；
- 模板 `OUTLINE_AI_DRAFT`，输出要求与 `OUTLINE_CREATE` 单条结构一致（title + content 摘要），保证格式可入库；
- `order_index` 默认 `max(order_index)+1`。

## 2.5 structure 一致性约束（审查补充）

- 已核实：编辑弹窗保存时 `structure` 从表单字段**整体重建**（`summary: values.content`，Outline.tsx 482 行），故 AI 只回填 title/content 不会造成 structure 与 content 不一致。
- 但 AI 改写可能隐含角色/场景变化，而表单的角色/组织/场景字段保持原值。缓解：两个模板的 `<task>` 中明确要求——"如非必要不要改变涉及角色/组织/场景/情感基调的语义；如确有调整，在输出末尾单独列出变化点，供用户手动同步表单"。
- 回填后 UI 提示："结构化字段（角色/场景等）如需同步，请手动核对后再保存"。

## 2. 模板注册（prompt_service.py）

- 新增类常量 `OUTLINE_AI_EDIT` / `OUTLINE_AI_DRAFT`（`<system>/<task>/<project>` 结构，仿 OUTLINE_CREATE；字段参数按 §1 上下文设计，占位符风格 `{title}` 等与现有模板一致）。
- 在 `get_all_system_templates` 的注册表中各加一条（name/category/description/parameters），模板管理页自动可见、可覆盖。
- 注意：新模板默认激活（系统默认模板机制即"无用户模板时用系统默认"），符合现有治理（天命教训是"全局自动替换"，本设计无此问题）。

## 3. 前端（Outline.tsx）

### 编辑弹窗（modalApi.confirm content）

- 在表单末尾（叙事目标之后）加 `<Divider>` + 「🤖 AI 润色」区块：
  - `TextArea` 润色方向（占位：例如：加强章末钩子、压缩到300字、更强调冲突）
  - 「应用 Skill」下拉：**直接复用子任务 2 抽出的 `components/SkillSelector.tsx` 公共组件**（勿重复实现）
  - `AIServiceSelector`（受控 value/onChange，state 管理，与全局一致）
  - 「开始润色」按钮：loading → 调 `POST /api/outlines/{id}/ai-edit` → `editForm.setFieldsValue({title, content})` → `message.success('已填入表单，请确认后点击更新保存')` + 结构化字段核对提示
- 弹窗 body 已有 `maxHeight + overflowY auto`，高度增加安全。

### 手动创建弹窗

- 同样在表单末尾加「🤖 AI 起草」区块（起草要求 + SkillSelector + AIServiceSelector + 「AI 起草」按钮）→ `manualCreateForm.setFieldsValue({order_index, title, content})` → 提示确认后点「创建」。

### 交互纪律

- 润色/起草中按钮 loading、禁止重复点击；结果只回填，不自动提交。

## 兼容性 / 回滚

- 新端点、新模板均为增量，不动现有接口。
- 回滚：后端/前端各一次提交，可独立 revert。
- 风险点：
  - 解析容错（AI 输出非 JSON）→ §1 兜底策略；
  - 编辑弹窗宽度 800px，AIServiceSelector 两行布局在窄屏的表现 → 用已有 Space vertical 布局，不做额外适配（弹窗已是固定宽）。

## 验证方式

1. 接口层：curl 直接调用两个新端点（带/不带 skill_key、带/不带模型），检查响应与日志（`已将 Skill`）。
2. 手测：编辑弹窗润色一条大纲 → 确认表单回填、DB 无变化（查 outline 表 updated_at 不变）；点更新后入库。
3. 起草：创建弹窗起草 → 改标题 → 创建 → 列表出现新条目。
4. 模板管理页可见两个新模板；用户自定义同名模板可覆盖（get_template 机制自动生效）。
