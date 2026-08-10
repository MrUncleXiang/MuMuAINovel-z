# PRD：模型选择入口统一（服务商 → 模型两级）

## Goal

消除 AI 生成弹窗中「本次模型」与「AI模型」双入口并存的问题，全局统一为 `AIServiceSelector`（服务商 → 模型两级选择），并修复「未选服务商时看不到已配置模型（OPENCODEGO 等）」的问题。

## 背景（代码事实）

- `components/AIServiceSelector.tsx`：现成的「本次使用的 AI 服务」+「本次模型」两级组件，resolve 后显示蓝色提示「实际将使用：provider · model」。缺陷：未选服务商时 `modelOptions` 为空数组（`if (!selected) return []`）。
- `pages/Outline.tsx` 877-898 行：后加的「AI模型」下拉（`name="model"`），与 AIServiceSelector 写同一 form 字段，互相干扰。
- `pages/Chapters.tsx` 3023-3040 行：单模型生成弹窗同样有重复的「AI模型」下拉。
- `pages/Chapters.tsx` 3326-3410 行：批量生成弹窗用「AI 服务」+「AI模型」两个裸下拉（未封装），本质也是两级选择。
- `AIProviderConfig` 含 `is_default`（默认服务商标记）与 `models` 字段，前端 `aiProviderApi.list()` 可直接取到——增强「未选服务商显示默认服务商模型」无需后端改动。

## Requirements

1. 大纲生成弹窗：删除后加的「AI模型」下拉及其加载逻辑（`loadedModels`/`defaultModel`），模型选择仅保留 AIServiceSelector。
2. 章节单模型生成弹窗：删除重复的「AI模型」下拉，模型选择统一由 AIServiceSelector 负责（`selectedModel` 从 selection 派生）。
3. 章节批量生成弹窗：「AI 服务」+「AI模型」裸下拉替换为 AIServiceSelector 组件。
4. 增强 AIServiceSelector：未选服务商时，模型下拉展示默认服务商（`is_default`）的模型列表；此时选择模型自动携带默认服务商 `provider_config_id`。
5. 保留蓝色 resolve 提示（「实际将使用：...」）。
6. 各弹窗打开时仍预填当前默认模型（保证「本次模型」显示有效值，且下拉选项可见）。

## Acceptance Criteria

- [ ] 大纲生成弹窗（单模型模式）只有一套模型选择区：服务商下拉 + 模型下拉 + resolve 提示。
- [ ] 弹窗打开时预填默认服务商及其默认模型（当前 = OpenCode Go · deepseek-v4-flash）。
- [ ] 不选服务商时，模型下拉可见 OPENCODEGO（默认服务商）的完整模型列表。
- [ ] 章节生成弹窗、批量生成弹窗同样只有一套模型选择，交互与大纲弹窗一致（含同样预填）。
- [ ] 生成请求体中 `provider_config_id`/`model` 正确（选模型而未选服务商时自动带默认服务商 id）。
- [ ] 未做任何选择时，提交行为与现状一致（走后端默认路由）。
- [ ] 前端 typecheck / build 通过。
