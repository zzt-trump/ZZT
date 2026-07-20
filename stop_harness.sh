#!/bin/bash
# ============================================================
# Model Harness 停止脚本（macOS）
# 用法：bash stop_harness.sh
# ============================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.harness.pid"

echo ""
echo -e "${YELLOW}正在停止 Model Harness...${NC}"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if ps -p "$PID" > /dev/null 2>&1; then
    kill "$PID" 2>/dev/null && echo "已发送停止信号 (PID: $PID)" || true
    sleep 2
    # 如果还在，强制终止
    if ps -p "$PID" > /dev/null 2>&1; then
      kill -9 "$PID" 2>/dev/null && echo "已强制终止" || true
    fi
  else
    echo "PID 文件存在但进程已不存在"
  fi
  rm -f "$PID_FILE"
else
  # 尝试通过进程名查找
  pkill -f "python3 runner.py" 2>/dev/null && echo "已通过进程名终止" || true
fi

sleep 1
if pgrep -f "python3 runner.py" > /dev/null 2>&1; then
  echo -e "${RED}⚠️  仍有进程残留，尝试强制终止...${NC}"
  pkill -9 -f "python3 runner.py" 2>/dev/null || true
fi

if ! pgrep -f "python3 runner.py" > /dev/null 2>&1; then
  echo -e "${GREEN}✅ Harness 已停止${NC}"
else
  echo -e "${RED}⚠️  仍有进程运行，可能需要手动 kill${NC}"
fi

echo ""