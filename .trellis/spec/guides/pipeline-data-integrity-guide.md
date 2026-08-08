# 建书/测试数据完整性指南（Pipeline Data Integrity）

> **触发场景**：创建项目、一键开书、构建测试数据、给已有书接流水线、写对比测试书。
> **核心教训**：**"图省事"导致数据不完整，后续所有环节都在残缺数据上运行。**

---

## 1. 一本书的"完整设定"由哪些构成

一本可正常推进的书，这 4 块必须齐全：

| 模块 | 字段/表 | 缺失后果 |
|---|---|---|
| 项目基本信息 | title / description / theme / genre | 向导生成世界观报"缺必需参数"；页面被拉回向导 |
| 世界观 | world_time_period / world_location / world_atmosphere / world_rules | 正文写作无背景可参考（AI 裸写） |
| 角色 | characters 表（含关系 relationships） | 正文无人物可写，情节失去锚点 |
| 大纲 | outlines 表（卷/章结构） | 章节循环无从开始 |

## 2. 常见"图省事"坑（已踩过，勿重踩）

1. **用 API 建项目只传 3 个字段**（漏 description）→ 向导报缺参数。
   → 规则：建项目必须保证 description 非空（缺则用 theme 兜底）。
2. **给已有大纲的书启动流水线**，以为"建书完成了"→ 世界观/角色还是空的。
   → 规则：流水线 BOOK 阶段**无论有没有大纲**，先检查世界观/角色，缺则自动补全。
   （已在 pipeline_service 实现：`_generate_world_and_characters` 在任何 BOOK 阶段都会跑）
3. **对比测试只复制大纲+标题**，不复制世界观/角色 → 对比不公平（同标题不同设定）。
   → 规则：构建对比测试书必须**完整复制设定**（世界观字段 + characters 表 + 大纲 + 章节标题）。
4. **项目 wizard_status 未标记完成** → 点击项目被拉回向导页。
   → 规则：流水线启动（start_pipeline）即标记 `wizard_status=completed, wizard_step=4`。

## 3. 机制保障（已实现的自动兜底）

- `start_pipeline`：启动即标记项目向导完成 + description 兜底。
- `_generate_world_and_characters`：任何 BOOK 阶段都检查世界观 4 字段（缺失重试 3 次 + 兜底值）和角色（无角色则生成）。
- 世界设定硬约束：4 字段任一缺失 → 重试 → 兜底默认值，**绝不留空**。

## 4. 构建测试/演示数据的检查清单

- [ ] 项目 4 字段（title/description/theme/genre）齐全？
- [ ] 世界观 4 字段非空？
- [ ] 有角色（或流水线会自动生成）？
- [ ] 大纲存在？
- [ ] wizard_status=completed？（启动流水线会自动处理）
- [ ] 若是对比测试：设定与原版完全一致（同世界观/角色/大纲/标题）？

---

## 5. 本指南如何被使用

- 本文件属于 `.rudder/spec/guides/`，随 spec 注入每个会话。
- 创建项目 / 建测试数据 / 修流水线时，对照第 4 节清单。
- 发现新的"图省事"坑 → 追加到第 2 节。
