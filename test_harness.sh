#!/bin/bash
# ============================================================
# Harness 快速验证脚本
# 用法：bash test_harness.sh
# 只跑一轮，验证所有模块是否正常
# ============================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "=============================================="
echo "   Model Harness 验证测试"
echo "=============================================="
echo ""

# 测试 1：Python 语法
echo -e "${YELLOW}[测试 1] Python 语法检查...${NC}"
cd "$SCRIPT_DIR"
python3 -c "
import py_compile, sys
files = ['config.py','ollama_client.py','mock_client.py','test_generator.py','scorer.py','iteration_engine.py','reporter.py','runner.py']
ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError as e:
        print(f'  ❌ {f}: {e}')
        ok = False
if ok:
    print('  ✅ 所有文件语法正确')
else:
    sys.exit(1)
" || exit 1

# 测试 2：Ollama 连接
echo ""
echo -e "${YELLOW}[测试 2] Ollama 连接...${NC}"
python3 -c "
from ollama_client import get_client
c = get_client()
h = c.health_check()
if h['ok']:
    print(f'  ✅ Ollama 在线')
    models = c.list_models()
    print(f'  已安装模型: {models}')
else:
    print(f'  ❌ Ollama 不可用: {h.get(\"error\")}')
    exit(1)
" || exit 1

# 测试 3：Mock API 连接
echo ""
echo -e "${YELLOW}[测试 3] Mock API 连接...${NC}"
python3 -c "
from mock_client import get_hub
hub = get_hub()
health = hub.health_all()
for name, h in health.items():
    if h.get('status') == 'ok':
        print(f'  ✅ {name} 在线 ({h.get(\"tables\")} 张表)')
    else:
        print(f'  ⚠️  {name} 异常: {h}')
" || echo -e "${YELLOW}  ⚠️  Mock API 不可达（如果只是测试本地逻辑，可以忽略）${NC}"

# 测试 4：单轮演练
echo ""
echo -e "${YELLOW}[测试 4] 单轮完整演练（5 题）...${NC}"
cd "$SCRIPT_DIR"
python3 -c "
import logging
logging.basicConfig(level=logging.WARNING)
from runner import run_single_round
from ollama_client import get_client
from mock_client import get_hub
import config
config.QUESTIONS_PER_ROUND = 5
ok = run_single_round(1, get_client(), get_hub())
if ok:
    print('  ✅ 单轮演练成功！查看 reports/ 目录')
else:
    print('  ❌ 演练失败，请查看上方错误')
    exit(1)
" 2>&1 | tail -20

echo ""
echo -e "${GREEN}=============================================="
echo "   验证完成"
echo "=============================================="
echo -e "${NC}"
echo ""
echo "报告目录: $SCRIPT_DIR/reports/"
echo ""