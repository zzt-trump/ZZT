#!/bin/bash
# ============================================================
# Model Harness 启动脚本（macOS）
# 用法：bash start_harness.sh
# 默认：每 30 分钟一轮，无限循环
# ============================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HARNESS_DIR="$SCRIPT_DIR"
PID_FILE="$HARNESS_DIR/.harness.pid"
LOG_DIR="$HARNESS_DIR/logs"

echo ""
echo -e "${YELLOW}=============================================="
echo "   Model Harness 启动脚本"
echo "=============================================="
echo -e "${NC}"

# 检查 Ollama 是否运行
echo "检查 Ollama 服务..."
if curl -s http://localhost:11434 > /dev/null 2>&1; then
  echo -e "${GREEN}✅ Ollama 服务运行中${NC}"
else
  echo -e "${RED}❌ Ollama 未启动，请先运行 bash start_qwen.sh${NC}"
  exit 1
fi

# 检查是否已有实例在运行
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if ps -p "$OLD_PID" > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Harness 已在运行（PID: $OLD_PID）${NC}"
    echo "如需重启，请先运行 bash stop_harness.sh"
    exit 0
  else
    rm -f "$PID_FILE"
  fi
fi

# 解析参数
INTERVAL="${1:-1800}"   # 默认 30 分钟
ROUNDS="${2:-0}"         # 默认无限

echo "启动参数: 间隔=${INTERVAL}s, 轮次=${ROUNDS:-无限}"
echo ""

# 后台启动
cd "$HARNESS_DIR"
nohup python3 runner.py --interval "$INTERVAL" ${ROUNDS:+--rounds "$ROUNDS"} \
  > "$LOG_DIR/harness_stdout.log" 2>&1 &

HARNESS_PID=$!
echo "$HARNESS_PID" > "$PID_FILE"

sleep 2

if ps -p "$HARNESS_PID" > /dev/null 2>&1; then
  echo -e "${GREEN}✅ Harness 已启动（PID: $HARNESS_PID）${NC}"
  echo ""
  echo "  查看日志: tail -f $LOG_DIR/harness_stdout.log"
  echo "  停止服务: bash stop_harness.sh"
  echo "  查看报告: open $HARNESS_DIR/reports/"
else
  echo -e "${RED}❌ Harness 启动失败，请查看日志${NC}"
  rm -f "$PID_FILE"
  exit 1
fi

echo ""