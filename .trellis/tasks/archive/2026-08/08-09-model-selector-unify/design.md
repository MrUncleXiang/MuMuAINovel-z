# Design：模型选择入口统一

## 边界

- 纯前端改动，无后端接口变更、无数据库改动。
- 改动文件：`components/AIServiceSelector.tsx`、`pages/Outline.tsx`、`pages/Chapters.tsx`。
- 不动：多模型比较组件 `LLMMultiSelector`（已是服务+模型两级多选，与本次统一目标一致）。

## 1. AIServiceSelector 增强（核心）

现状：`modelOptions` 仅在选中服务商时有值（`if (!selected) return []`）。

增强逻辑：

```ts
const defaultProvider = providers.find(p => p.is_default) ?? providers[0];  // 默认服务商，兜底第一个启用的
// 模型选项来源：选中服务商 或 默认服务商
const sourceProvider = selected ?? defaultProvider;
const modelOptions = sourceProvider
  ? Array.from(new Set([sourceProvider.default_model, ...(sourceProvider.models || [])].filter(Boolean)))
      .map(model => ({ label: model, value: model }))
  : [];
```

- 「本次模型」下拉 `placeholder`：未选服务商时显示 `默认服务商: ${defaultProvider.name}`，替代现文案「不指定，使用服务默认模型」。
- 选择模型且未选服务商时，`onChange` 自动补 `provider_config_id: defaultProvider.id`：

```ts
onChange={model => onChange?.({ ...value, provider_config_id: value?.provider_config_id ?? defaultProvider?.id, model })}
```

- 服务商下拉增加 `is_default` 标注（label 加「（默认）」后缀），帮助用户识别。
- 蓝色 resolve 提示保留不动（未指定时 resolve 已能解析默认服务商，如「实际将使用：OpenCode Go · deepseek-v4-flash」）。
- **已核实**：数据库 `ai_provider_configs` 中 OpenCode Go 为 `is_default=true` 且 models 完整（25 个），验收可用真实数据验证。

## 2. Outline.tsx 改动

- 删除 877-898 行「AI模型」`Form.Item`（含 `loadedModels` 选项、`当前默认模型` 提示）。
- 删除弹窗打开时加载 `loadedModels`/`defaultModel` 的逻辑（约 699-740 行）。
- **预填决策（用户已确认 2026-08-09）**：弹窗打开时预填**默认服务商 + 其 default_model**（当前数据 = OpenCode Go · deepseek-v4-flash）：`initialValues = { provider_config_id: defaultProvider.id, model: defaultProvider.default_model }`。来源用 `aiProviderApi.list()` 中 `is_default` 的服务商（**动态取，不硬编码**），与 AIServiceSelector 内部逻辑一致。预填后「本次使用的 AI 服务」显示 OpenCode Go（（默认）标注）、「本次模型」显示 deepseek-v4-flash、蓝色提示显示「实际将使用：OpenCode Go · deepseek-v4-flash」。
- 提交逻辑（`handleGenerate`）读取 form 的 `provider_config_id`/`model`，不变。

## 3. Chapters.tsx 改动

### 单模型生成弹窗（约 3023-3040 行）

- 删除「AI模型」`Form.Item`（渲染 `availableModels` 的下拉）。
- `selectedModel` state 保留，但只从 `AIServiceSelector.onChange` 的 `selection.model` 派生（现有 2946-2954 行已如此）。
- **`availableModels` state 及 `loadAvailableModels` 加载逻辑（69/1641 行区域）一并删除**（已核实其全部引用点 3095/3103/3425/3431/3433 行都在两个待删下拉中，无其他使用）。
- **预填（用户已确认 2026-08-09）**：弹窗打开时预填默认服务商 + 其 default_model（当前 = OpenCode Go · deepseek-v4-flash）：`selection = { provider_config_id: 默认服务商.id, model: 默认服务商.default_model }`，通过 `aiProviderApi.list()` 动态获取（不硬编码）。删除 `loadAvailableModels` 的预填逻辑（1641-1648 行）。

### 批量生成弹窗（约 3326-3410 行）

- 「AI 服务」+「AI模型」两个裸下拉替换为 `<AIServiceSelector usageType="chapter_write_batch" ...>`（或现有 usageType）。
- 删除 `batchSelectedProvider`/`batchProviderModels`/`batchSelectedModel` 相关 state 与联动逻辑，改为统一的 selection state。
- 提交时从 selection 取值组装请求体。

## 兼容性 / 回滚

- 不选服务、不选模型 = 现状（后端默认路由），无行为回归。
- 回滚：单 commit 纯前端改动，`git revert` 即可。
- 风险点：批量弹窗 state 重构涉及提交逻辑，需仔细核对请求体组装处（`batchSelectedModel`/`batchSelectedProvider` 的全部引用点）。

## 验证方式

- `npm run typecheck`（或项目现有 lint/build 命令）通过。
- 手测：三个弹窗各打开一次，确认只有一套模型选择；不选服务商时模型下拉出现 OPENCODEGO 模型；选模型后提交，后端日志确认收到 `provider_config_id`。
