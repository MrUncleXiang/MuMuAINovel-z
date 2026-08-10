# Implement：模型选择入口统一

> 前置：`git checkout -b feat/outline-model-selector-unify`（从 main）。完成后 PR 合回。
>
> **阻塞记录（2026-08-09）**：步骤 4-5（Chapters.tsx）因工作区存在 MrUncleXiang 未提交的在途改动（章节比较模式每模型单独配 Skill/字数，覆盖同一弹窗区域，见 `backend/app/services/chapter_comparison_service.py` 等 5 文件）而**暂缓**。用户决策：等待其提交后再执行 4-5。步骤 1-3（AIServiceSelector + Outline.tsx）已完成并提交（commit a043a33，已构建部署）。

## 执行清单（按序）

- [ ] 1. 阅读 `components/AIServiceSelector.tsx` 全文，确认 props/类型（`AIServiceSelection`）。
- [ ] 2. 增强 AIServiceSelector：
  - [ ] 2.1 `defaultProvider = providers.find(p => p.is_default)`
  - [ ] 2.2 `modelOptions` 来源改为 `selected ?? defaultProvider`
  - [ ] 2.3 模型下拉 placeholder 未选服务商时显示默认服务商名
  - [ ] 2.4 模型 onChange 未选服务商时自动补 `provider_config_id`
  - [ ] 2.5 服务商下拉 label 加「（默认）」标注
- [ ] 3. `pages/Outline.tsx`：
  - [ ] 3.1 删除 877-898 行「AI模型」Form.Item
  - [ ] 3.2 删除 `loadedModels`/`defaultModel` 加载逻辑（约 699-740 行）
  - [ ] 3.3 预填改为：默认服务商（`is_default`）+ 其 `default_model`（当前 = OpenCode Go · deepseek-v4-flash，动态取不硬编码）写入 `initialValues.provider_config_id` + `initialValues.model`
  - [ ] 3.4 确认 `handleGenerate` 提交读取 form 的 `provider_config_id`/`model`
- [ ] 4. `pages/Chapters.tsx` 单模型弹窗（**阻塞中，等 MrUncleXiang WIP 提交后执行**）：
  - [ ] 4.1 删除 3023-3040 行「AI模型」Form.Item
  - [ ] 4.2 确认 `selectedModel` 仅由 AIServiceSelector 派生
  - [ ] 4.3 删除 `availableModels` state 与 `loadAvailableModels`（已核实无其他引用）
  - [ ] 4.4 预填 = 默认服务商 + default_model（同大纲弹窗），删除 `loadAvailableModels` 的预填逻辑（1641-1648 行）
- [ ] 5. `pages/Chapters.tsx` 批量弹窗（**阻塞中，同上**）：
  - [ ] 5.1 替换「AI 服务」+「AI模型」裸下拉为 AIServiceSelector
  - [ ] 5.2 删除 `batchSelectedProvider`/`batchProviderModels`/`batchSelectedModel` state 及联动
  - [ ] 5.3 核对所有引用点（grep），提交逻辑改从 selection 取值
- [ ] 6. 验证：
  - [ ] 6.1 前端 typecheck/build 通过
  - [ ] 6.2 手测三个弹窗：单套模型选择、未选服务商可见默认服务商模型、选模型自动带服务商 id、不选时走默认路由
- [ ] 7. 提交 commit（单 commit，信息：`feat(outline): 统一模型选择入口为服务商+模型两级`）

## 验证命令

```bash
cd /home/ubuntu/MuMuAINovel/source/frontend
# 项目实际脚本以 package.json 为准
npm run build   # 或 npm run typecheck / lint
```

后端日志确认生成请求参数：`大纲生成AI调用参数: provider参数/model参数`（outlines.py 已有该日志）。

## 回滚点

- 步骤 2 完成即一次可运行状态；步骤 3-5 每完成一个弹窗可独立提交（或合一个 commit，以改动量为准）。
- 异常时 `git reset --hard HEAD` 回到改动前。
