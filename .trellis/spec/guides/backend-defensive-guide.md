# 后端防御指南（Backend Defensive Checks）

> 状态：已生效（2026-08-10）
> 来源：一周内 4 次"引用不存在的名字/对象"生产事故（NameError ×2、DetachedInstanceError、类型错配）

## 提交前必做：静态扫描

```bash
cd source/backend
python3 -m pyflakes app/ | grep -E "undefined name"
```
**`undefined name` 必须清零**（`ExceptionGroup` 是 Python 3.11 内置，唯一允许的假阳性）。

本仓库事故模式：同事提交常带"调用了不存在的函数/变量"（`task_input`、`_recover_stale_analysis_tasks`），运行到即 500。扫描只需 1 分钟，能拦下全部这类问题。

## 高危模式速查

### 1. except 变量在闭包/生成器里引用 ❌
```python
except Exception as e:
    async def error_gen():
        yield str(e)   # ❌ 生成器迭代时 e 已被 Python 删除 → NameError
```
✅ 提前字符串化：`error_msg = str(e)` 后再进闭包。

### 2. datetime 进 JSON 再回数据库 ❌
```python
# 快照序列化：datetime → isoformat 字符串
# 恢复时直接把字符串 INSERT → asyncpg 报 "expected datetime, got str"
```
✅ 恢复时按列类型转回：`datetime.fromisoformat(str_val)`（见 `restore_project_state` 的通用转换）。

### 3. 后台任务闭包捕获 ORM 实例 ❌
请求 session 关闭后访问实例属性 → `DetachedInstanceError`。
✅ 闭包只传 **id/标量**；后台任务自建 session 重新查询。协程参数在**创建时**求值完毕再调度。

### 4. 前端状态枚举不同步 ❌
后端加状态（`superseded`）→ 前端类型和轮询条件漏改 → 假进度/无限轮询。
✅ 改状态机时：后端模型注释 + 前端 `types/index.ts` + 所有轮询停止条件同步。

### 5. 路由装饰器挂错函数 ❌
往 `@router.get(...)` 与函数定义之间插入新函数 → 装饰器挂到新函数 → 启动崩溃。
✅ 插入函数时检查装饰器归属；提交前 `python3 -m py_compile` + 容器启动验证。

## 数据库字段约定

- 快照/JSON 序列化的 datetime 字段：序列化 `isoformat()`，**反序列化必须转回**（统一在恢复函数处理，勿散落各处）
- 每章唯一记录（如 `plot_analysis.chapter_id`）：写入用 `select ... with_for_update` + 存在则更新、不存在则创建
- 后台任务间传递非列属性：用 Python 动态属性（同进程有效），勿给表加列除非需要持久化

## 合并同事分支时的强制检查

1. `pyflakes` undefined name 清零
2. 新接口容器启动验证（FastAPI 路由参数/响应类型错误在启动时崩溃）
3. 新状态/新枚举与前端类型核对
4. 涉及 ORM 的后台任务：检查跨 session 使用
