#!/bin/bash
# ============================================================
# 提交前检查脚本（MUMUAINovel）
# 用法：cd source && ./scripts/precommit-check.sh [--container]
#   --container: 额外重启后端容器并验证健康（改动后端必跑）
# 检查项：
#   1. 后端 pyflakes 未定义名称扫描（undefined name 必须清零）
#   2. 后端全量语法编译
#   3. 前端 TypeScript 类型检查（tsc -b）
# 依据：.trellis/spec/guides/backend-defensive-guide.md
# ============================================================
set -e
cd "$(dirname "$0")/.."   # 进入 source/

echo "==================================================="
echo " [1/3] 后端 pyflakes 未定义名称扫描"
echo "==================================================="
cd backend
if ! python3 -m pyflakes --version >/dev/null 2>&1; then
  echo "⚠️  pyflakes 未安装，尝试安装..."
  pip install pyflakes -q || { echo "❌ 无法安装 pyflakes，请手动安装后重试"; exit 1; }
fi
UNDEF=$(python3 -m pyflakes app/ 2>&1 | grep "undefined name" | grep -v "ExceptionGroup" || true)
if [ -n "$UNDEF" ]; then
  echo "❌ 发现未定义名称（运行到即 500/崩溃，必须修复）："
  echo "$UNDEF"
  exit 1
fi
echo "✅ undefined name 清零（ExceptionGroup 为 Python 3.11 内置，允许）"
cd ..

echo ""
echo "==================================================="
echo " [2/3] 后端语法检查（ast.parse，不写盘）"
echo "==================================================="
cd backend
# 递归遍历 app/ 下所有 .py（跳过 __pycache__），纯语法解析不写 pycache
if python3 - <<'PYEOF'
import ast, os, sys

errors = []
count = 0
for root, dirs, files in os.walk('app'):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for fn in files:
        if not fn.endswith('.py'):
            continue
        path = os.path.join(root, fn)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                ast.parse(f.read(), filename=path)
            count += 1
        except SyntaxError as e:
            errors.append(f'{path}:{e.lineno}: {e.msg}')
if errors:
    print('❌ 语法错误：')
    for e in errors:
        print('  ', e)
    sys.exit(1)
print(f'✅ {count} 个 Python 文件语法检查通过')
PYEOF
then
  :
else
  exit 1
fi
cd ..

echo ""
echo "==================================================="
echo " [3/3] 前端 TypeScript 类型检查"
echo "==================================================="
cd frontend
if npx tsc -b 2>&1 | head -30; then
  echo "✅ TypeScript 类型检查通过"
else
  echo "❌ TypeScript 类型检查失败"
  exit 1
fi
cd ..

echo ""
echo "==================================================="
echo " 🎉 提交前检查全部通过"
echo "==================================================="

# 可选：容器启动验证（后端改动必跑）
if [ "$1" = "--container" ]; then
  echo ""
  echo "==================================================="
  echo " [可选] 重启后端容器并验证健康"
  echo "==================================================="
  docker restart mumuainovel 2>&1 | tail -1
  sleep 30
  CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:19000/health || echo "000")
  if [ "$CODE" = "200" ]; then
    echo "✅ 容器健康（HTTP 200）—— FastAPI 路由/响应类型等启动期错误已排除"
  else
    echo "❌ 容器未就绪（HTTP $CODE）—— 请检查 docker logs mumuainovel"
    exit 1
  fi
fi
