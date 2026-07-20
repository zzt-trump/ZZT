#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型 Harness 配置中心 — 所有可调参数集中管理"""

import os
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "reports"
PROMPTS_DIR = ROOT / "prompts"
TEST_SUITE_DIR = ROOT / "test_suite"
LOGS_DIR = ROOT / "logs"

for d in [REPORTS_DIR, PROMPTS_DIR, TEST_SUITE_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Ollama 模型连接 ───────────────────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:9b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "120"))  # 秒

# ── Mock 数据源（ERP + MES 双源）───────────────────────
MOCK_ERP_BASE = os.environ.get("MOCK_ERP_BASE", "http://114.215.204.62:8005")
MOCK_ERP_TOKEN = os.environ.get("MOCK_ERP_TOKEN", "erp-token-2026")
MOCK_MES_BASE = os.environ.get("MOCK_MES_BASE", "http://114.215.204.62:8006")
MOCK_MES_TOKEN = os.environ.get("MOCK_MES_TOKEN", "mes-token-2026")
MOCK_TIMEOUT = int(os.environ.get("MOCK_TIMEOUT", "30"))

# 双源配置列表
DATA_SOURCES = [
    {
        "name": "ERP",
        "base_url": MOCK_ERP_BASE,
        "token": MOCK_ERP_TOKEN,
        "tables": ["t01","t02","t03","t04","t05","t06","t08","t09"],
    },
    {
        "name": "MES",
        "base_url": MOCK_MES_BASE,
        "token": MOCK_MES_TOKEN,
        "tables": ["t07","t10","t11","t12"],
    },
]

# 跨源 JOIN 映射（用于生成跨源测试题）
CROSS_SOURCE_JOINS = [
    {
        "label": "到货批次 ↔ 质检批次",
        "erp_table": "t06", "erp_key": "批次号",
        "mes_table": "t11", "mes_key": "批次号",
        "description": "ERP 采购到货记录与 MES 质检批次记录通过批次号关联",
    },
    {
        "label": "销售订单 ↔ 生产工单",
        "erp_table": "t04", "erp_key": "销售订单号",
        "mes_table": "t07", "mes_key": "关联销售单号",
        "description": "ERP 销售订单与 MES 生产工单通过销售订单号关联",
    },
    {
        "label": "物料主数据 ↔ 领用记录",
        "erp_table": "t02", "erp_key": "物料编码",
        "mes_table": "t10", "mes_key": "物料编码",
        "description": "ERP 物料货品主数据与 MES 物料领用记录通过物料编码关联",
    },
]

# ── 测试生成 ──────────────────────────────────────────
QUESTIONS_PER_ROUND = int(os.environ.get("QUESTIONS_PER_ROUND", "20"))
# 各类别题目占比
CATEGORY_WEIGHTS = {
    "single_table_query": 0.25,    # 单表查询
    "cross_source_join": 0.20,     # 跨源 JOIN
    "aggregation": 0.20,           # 聚合分析
    "anomaly_detection": 0.15,     # 异常检测
    "quality_trace": 0.10,         # 质检追溯
    "reasoning": 0.10,             # 综合推理
}
# 难度分布
DIFFICULTY_WEIGHTS = {
    "easy": 0.30,
    "medium": 0.50,
    "hard": 0.20,
}

# ── 评分引擎 ──────────────────────────────────────────
SCORING_DIMENSIONS = {
    "accuracy":    {"weight": 0.40, "label": "准确性"},
    "completeness":{"weight": 0.25, "label": "完整性"},
    "format":      {"weight": 0.15, "label": "格式规范"},
    "reasoning":   {"weight": 0.20, "label": "推理逻辑"},
}
PASS_THRESHOLD = 0.70  # 总得分 ≥ 此值视为通过

# ── 自我迭代引擎 ──────────────────────────────────────
MAX_ITERATIONS = 0  # 0 = 无限循环，>0 = 指定轮数后停止
ITERATION_INTERVAL_SEC = int(os.environ.get("ITERATION_INTERVAL_SEC", "1800"))  # 默认 30 分钟
FAILURE_CLUSTER_MIN = 3  # 至少 N 个同类失败才触发 prompt 优化
MAX_FEWSHOT_EXAMPLES = 5  # few-shot 示例池上限
PROMPT_EVOLUTION_ENABLED = True  # 是否允许自动修改 prompt

# ── 系统 prompt 模板 ───────────────────────────────────
# 基础 system prompt（会被迭代引擎更新）
BASE_SYSTEM_PROMPT = """你是一个制造业数据分析助手，服务于离散制造企业的 ERP/MES 系统。
你的回答必须：

1. **精确**：数值、编码、日期必须与数据源一致，保留前导零（如 SUP0007 不能写成 SUP7）
2. **结构化**：涉及多行数据时，优先使用 Markdown 表格
3. **可验证**：引用具体的表名和字段名，让结论可追溯
4. **简洁**：先给出直接答案，再附简要分析

## 数据源背景
- 这是一个离散制造企业，有 ERP（采购/销售/供应链）和 MES（制造执行）两套系统
- 两套系统互相独立，通过「批次号」「物料编码」「销售订单号」等字段跨系统关联
- 所有字段值均为字符串（保留编码前导零），空值为 null

## 常见错误提醒
- 不要混淆供应商编码和供应商名称
- 注意「已到货量」和「采购数量」的区别
- 质检状态有：合格、不合格、待检、免检
- 工单状态有：计划、已下达、生产中、已完工、已关闭
- 跨系统查询时，必须从两个数据源分别获取数据后再关联
"""

# ── 报告 ──────────────────────────────────────────────
SUMMARY_JSON_PATH = REPORTS_DIR / "summary.json"