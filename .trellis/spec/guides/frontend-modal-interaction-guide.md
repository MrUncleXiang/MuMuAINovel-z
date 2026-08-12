# 前端弹窗与受控组件指南（Modal Interaction）

> 状态：已生效（2026-08-11 更新）
> 来源：AI 润色/起草“无法输入、点击无反应”事故复盘；续写弹窗 Tab 拆分重构复盘

## 核心知识：modal.confirm 的内容是静态渲染的

antd `modal.confirm/info/success`（含 `App.useApp()` 的 modalApi）打开的弹窗，**内容是一次性创建的 React 元素，不随外层组件 state 更新而重渲染**。表现：

- 受控输入框（`value` 来自组件 state）→ 打字不显示
- 按钮 `loading={state}` → loading 不出现
- 点击回调里读取的 state → 永远是渲染时的旧值（如 `editingOutlineId` 恒为 undefined）
- **受控 Tabs（`activeKey` 绑外层 state）→ 点击 Tab 无反应**（state 更新了但弹窗不重渲染，activeKey 永远不变；2026-08-11 实际事故）

**这不是 antd bug，是确认弹窗 API 的设计**：它是“一次性快照”，不是可交互表单容器。

## 三条可用方案（按优先级）

### 方案 A：受控 Modal 组件（大表单首选）
```tsx
<Modal open={visible} onOk={handleSave} okButtonProps={{ disabled: running }} ...>
  <Form form={form}>...</Form>
</Modal>
```
- 弹窗在组件渲染树内，**一切 state 正常**
- 可控制按钮禁用/loading、拦截关闭（如任务进行中弹确认）
- 适用：编辑弹窗、生成弹窗、任何"打开后还要交互"的场景

### 方案 B：子组件自持状态（confirm 弹窗内嵌复杂交互）
```tsx
modalApi.confirm({
  content: <MySection form={form} ... />,  // MySection 内部 useState
});
```
- **子组件实例挂载后内部 state 完全自洽**（React 组件固有机制）
- 与外层的数据交互走 props 和 `form.setFieldsValue`（命令式，不受静态渲染影响）
- 适用：AI 辅助区块（润色/起草/点评）、Skill 选择等

### 方案 C：Form 字段驱动（confirm 弹窗内简单输入）
```tsx
<Form.Item name="skill_key"><SkillSelector /></Form.Item>
```
- antd Form 内部管理值并重渲染，不依赖外层组件
- 适用：纯表单字段；**不适合**需要“点击后改变按钮状态”的交互

### 方案 D：非受控组件（confirm 弹窗内 Tabs/切换类的最简解法）
```tsx
<Tabs defaultActiveKey="direct" items={[...]} />
```
- 切换状态由组件内部管理，不依赖外层 state → 不受静态渲染影响
- **弹窗内的 Tabs 一律用 `defaultActiveKey`，禁用 `activeKey`+`onChange` 受控写法**
- 适用：弹窗内 Tab 拆分（表单 Tab / 对话 Tab）、折叠面板等“只要切换、不要外部联动”的场景

## 禁用模式（事故来源）

- ❌ confirm 内容里用外层 state 做受控输入/loading/回调判断
- ❌ 把 `if (!id) return` 这类“读取渲染时 state”的守卫放按钮回调里——点击时读到的永远是旧值
- ❌ 受控 Tabs（activeKey 绑外层 state）放进 confirm 弹窗——点击无反应
- ❌ 需要用 `setTimeout` 延迟触发异步再“等它自己好”——弹窗/页面不重渲染时无人感知

## 检查清单

- [ ] 弹窗内容里有受控组件？→ 确认弹窗必须用方案 A/B/C/D
- [ ] 弹窗内容里有 Tabs？→ 用方案 D（非受控 defaultActiveKey）
- [ ] 弹窗里有“进行中”状态（loading/进度）？→ 方案 A（可禁用确认按钮）或方案 B（子组件内自持）
- [ ] 弹窗关闭时可能丢异步结果？→ 方案 A + 拦截 onCancel 弹确认
