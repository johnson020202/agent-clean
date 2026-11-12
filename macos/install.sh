#!/bin/bash
# Agent Clean macOS 安装脚本（幂等，可重复执行）
#
# 做四件事：
#   1. 复制项目到 ~/.local/share/agent-clean
#   2. 生成命令包装器 ~/.local/bin/agent-clean
#   3. 由模板生成 ~/Library/LaunchAgents/com.agentclean.reap.plist
#   4. 加载 launchd 任务：每天 04:00 跑 reap + purge，日志到 ~/Library/Logs/agent-clean.log
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/.local/share/agent-clean"
BIN="$HOME/.local/bin/agent-clean"
LOG="$HOME/Library/Logs/agent-clean.log"
PLIST="$HOME/Library/LaunchAgents/com.agentclean.reap.plist"
LABEL="com.agentclean.reap"

PYTHON="$(command -v python3 || true)"
if [ -z "$PYTHON" ]; then
  echo "错误：找不到 python3，请先安装 Python 3" >&2
  exit 1
fi

echo "== Agent Clean 安装（源：$SRC）"

# 1. 复制项目（不含缓存与状态）
mkdir -p "$DEST" "$HOME/.local/bin" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '__pycache__' --exclude '*.pyc' --exclude '.git' --exclude 'state' \
    "$SRC/" "$DEST/"
else
  rm -rf "$DEST.tmp-copy"
  cp -R "$SRC" "$DEST.tmp-copy"
  rm -rf "$DEST"
  mv "$DEST.tmp-copy" "$DEST"
fi
echo "已复制到 $DEST"

# 2. 命令包装器
cat > "$BIN" <<EOF
#!/bin/bash
exec "$PYTHON" "$DEST/cli/main.py" "\$@"
EOF
chmod +x "$BIN"
echo "已生成 $BIN"

# 3. 由模板生成 launchd plist（占位符替换）
sed -e "s|@PYTHON@|$PYTHON|g" \
    -e "s|@DEST@|$DEST|g" \
    -e "s|@LOG@|$LOG|g" \
    "$SRC/macos/com.agentclean.reap.plist" > "$PLIST"
echo "已生成 $PLIST"

# 4. 加载任务（先卸载旧的，保证幂等）
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST" 2>/dev/null || launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "已加载 launchd 任务（每天 04:00 执行 reap + purge，日志：$LOG）"

echo "== 安装完成。用法：agent-clean add <路径> 2h"
