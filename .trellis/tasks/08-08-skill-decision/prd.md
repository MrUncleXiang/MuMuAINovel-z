# PRD：网文工坊技能引入（决策已确认）

## 背景

网文工坊（chinese-webnovel-skills，位于 /tmp/webnovel-studio/chinese-webnovel-skills-main）提供 33 个中文网文写作技能。MuMuAINovel 已有完整技能体系：

- `backend/app/skills/{skill}/SKILL.md`（YAML frontmatter：name/display_name/category/description/triggers + 正文），现有 7 个技能（story-* 系列）
- `skill_loader.py` 动态加载 + 缓存，`/api/skills/list` 提供列表
- 技能管理 API（create/update/delete）+ 前端「Skill 管理」页 + 「Skill 工具箱」（SkillChat 技能聊天）已存在
- 章节生成（Chapters.tsx）下拉直接展示全部技能（带 category 标签），装好即自动出现

## 决策记录（用户已确认，基于 Trellis 工作流逐个确认）

| 决策点 | 选择 | 说明 |
|---|---|---|
| ① 装多少技能 | **A2 全装 33 个** | 下拉显示全部（带分类标签），写作类常用技能放前；其余走 SkillChat |
| ② 多技能选择 | **B1 暂缓** | 单选 + 技能聊天先实测，暂不开发多选 |
| ③ 天命恢复开关 | **C2 维持禁用** | 不做开关，保持现状 |

## 实施范围

### 1. 安装技能（核心）

- 复制 32 个网文工坊技能目录 → `backend/app/skills/`（33 个中 deslop 除外）
- `deslop`：不新增目录；将网文工坊 deslop 内容**升级现有 `story-deslop/SKILL.md`**（保留 skill_key，避免历史生成记录失效）
- 现有 7 个技能保留不动
- 安装后技能总数：7 + 32 = **39 个**

### 2. 零开发自动生效的部分

- `/api/skills/list` 自动返回新技能（skill_loader 缓存刷新）
- 章节生成下拉自动显示全部技能（带分类标签）
- SkillChat / 技能管理页自动覆盖新技能

### 3. 明确不做（对应决策）

- 多技能选择（B1）
- 天命恢复开关（C2）
- 技能排序/分类过滤（下拉用现成的 category 标签区分即可）

## 验证清单

1. `skill_loader` 加载 39 个技能无报错（刷新缓存后 list 接口返回 39 条）
2. 抽查 3 个技能 detail（expand/dialogue/deslop 升级）正文注入正常
3. 下拉出现新技能（前端零改动验证）
4. SkillChat 对新技能可用

## 风险与已知限制

- 部分网文工坊技能正文引用 `references/` 或跨技能引用（如 expand 引 pov-guide），实际目录缺失 → 注入时引用失效，效果打折（trends/slang/draft/memory 依赖外部工具，纯提示词环境打折更明显）——不影响运行，仅效果打折，用户已知晓（A2 决策时已说明）
- 技能多、下拉长：39 项带分类标签，可接受；实测后如需精简再治理
- 无新依赖、无数据库改动、无前端改动 → 无需重建镜像，代码卷挂载即时生效
