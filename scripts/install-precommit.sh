#!/bin/bash
# ============================================================
# git pre-commit 钩子安装脚本（MUMUAINovel）
# 安装：cd source && ./scripts/install-precommit.sh
# 作用：每次 git commit 前自动运行提交前检查
#       （pyflakes 未定义名称 + 语法 + 前端 tsc），失败则阻止提交
# 依据：.trellis/spec/guides/backend-defensive-guide.md
# ============================================================
set -e
cd "$(dirname "$0")/.."   # 进入 source/

GIT_DIR=$(git rev-parse --git-dir 2>/dev/null || echo ".git")
HOOK_PATH="$GIT_DIR/hooks/pre-commit"
SCRIPT_PATH="$PWD/scripts/precommit-check.sh"

cat > "$HOOK_PATH" <<EOF
#!/bin/bash
# 自动生成：scripts/install-precommit.sh —— 提交前自动检查
# 跳过方式：git commit --no-verify（仅紧急情况）
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " 🔍 提交前自动检查（pre-commit hook）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if ! "$SCRIPT_PATH"; then
  echo ""
  echo "❌ 提交已阻止：请先修复上述检查问题。"
  echo "   （紧急情况可用 git commit --no-verify 跳过，但不建议）"
  exit 1
fi
EOF

chmod +x "$HOOK_PATH"
echo "✅ pre-commit 钩子已安装：$HOOK_PATH"
echo "   - 每次 git commit 自动检查（未定义名称/语法/前端类型）"
echo "   - 紧急跳过：git commit --no-verify"
echo "   - 卸载：rm $HOOK_PATH"
