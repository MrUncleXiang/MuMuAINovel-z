# Implement：单条大纲 AI 润色与 AI 起草

> 前置：子任务 2（Skill 接入）已合入 main（依赖 `build_skill_system_prompt`）；`git checkout -b feat/outline-ai-edit`。

## 执行清单（按序）

- [ ] 1. `schemas/outline.py`：
  - [ ] 1.1 `OutlineAIEditRequest`：`instruction?/skill_key?/provider_config_id?/model?`
  - [ ] 1.2 `OutlineAIDraftRequest`：`project_id(必填)/order_index?/instruction?/skill_key?/provider_config_id?/model?`
  - [ ] 1.3 `OutlineAIEditResponse` / `OutlineAIDraftResponse`：`{title, content}`（Draft 加 `order_index`）
- [ ] 2. `services/prompt_service.py`：
  - [ ] 2.1 类常量 `OUTLINE_AI_EDIT` / `OUTLINE_AI_DRAFT`（结构仿 OUTLINE_CREATE）
  - [ ] 2.2 `get_all_system_templates` 注册两条
- [ ] 3. `api/outlines.py`：
  - [ ] 3.1 `POST /{outline_id}/ai-edit`：归属校验 → 上下文（项目/角色/当前大纲/前后各2条/instruction）→ get_template+format_prompt → skill 注入（`build_skill_system_prompt`）→ `generate_text` → 解析（JSON 优先，兜底启发式）→ 写 GenerationHistory → 返回建议
  - [ ] 3.2 `POST /ai-draft`：项目校验 → 上下文（项目/角色/插入位置前后各2条或末尾4条/instruction）→ 同 3.1 流程 → 写 GenerationHistory → 返回 `{order_index, title, content}`
  - [ ] 3.3 解析失败：返回 502 + 原始文本（前端可展示）
- [ ] 4. 前端 `pages/Outline.tsx`：
  - [ ] 4.1 编辑弹窗末尾加「🤖 AI 润色」区块（方向 TextArea + Skill 下拉 + AIServiceSelector 受控 + 按钮 + loading）
  - [ ] 4.2 手动创建弹窗末尾加「🤖 AI 起草」区块（同上变体）
  - [ ] 4.3 结果回填 `setFieldsValue` + 提示"确认后再保存"；skill/模型选择 state 清理（弹窗关闭重置）
- [ ] 5. 验证：
  - [ ] 5.1 curl 两个新端点：带/不带 skill_key、带/不带模型各一次；检查响应与「已将 Skill」日志
  - [ ] 5.2 手测润色：回填正确、DB 未变（updated_at 不变）、点更新后入库
  - [ ] 5.3 手测起草：回填后可改、点创建后列表出现
  - [ ] 5.4 模板管理页可见 OUTLINE_AI_EDIT / OUTLINE_AI_DRAFT
  - [ ] 5.5 前端 typecheck/build 通过
- [ ] 6. 提交：后端 + 前端各一个 commit（`feat(outline): 单条大纲AI润色与AI起草（建议回填不入库）`）

## 验证命令

```bash
# curl 示例（登录态以实际 token 为准）：
curl -X POST http://localhost:8000/api/outlines/<id>/ai-edit \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"instruction":"加强章末钩子"}'

# 后端日志：
grep "已将 Skill" /home/ubuntu/MuMuAINovel/logs/*.log | tail
```

## 回滚点

- 步骤 1-3（后端）完成即独立可测（curl）；步骤 4 前端完成后手测。
- 异常：`git reset --hard HEAD` 或 revert 对应 commit。
