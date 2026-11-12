#!/bin/bash
# Agent Clean macOS 卸载脚本：移除 launchd 任务、包装器与安装目录。
# 只删除本工具自己的安装产物，不动任何登记/墓地数据（~/.agent-clean 保留）。
set -euo pipefail

DEST="$HOME/.local/share/agent-clean"
BIN="$HOME/.local/bin/agent-clean"
PLIST="$HOME/Library/LaunchAgents/com.agentclean.reap.plist"
LABEL="com.agentclean.reap"

echo "== Agent Clean 卸载"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl unload "$PLIST" 2>/dev/null || true
[ -f "$PLIST" ] && rm -f "$PLIST" && echo "已移除 $PLIST"
[ -f "$BIN" ] && rm -f "$BIN" && echo "已移除 $BIN"

# 只有路径完全匹配预期安装目录时才递归删除（防误删）
if [ "$DEST" = "$HOME/.local/share/agent-clean" ] && [ -d "$DEST" ]; then
  rm -rf "$DEST"
  echo "已移除 $DEST"
fi

echo "== 卸载完成（状态数据 ~/.agent-clean 未动，如需彻底清理请手动确认后删除）"
