#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试用例生成器 — 从 Mock 数据自动生成测试题 + 标准答案"""

import json
import random
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

from config import (
    QUESTIONS_PER_ROUND, CATEGORY_WEIGHTS, DIFFICULTY_WEIGHTS,
    TEST_SUITE_DIR, CROSS_SOURCE_JOINS,
)
from mock_client import get_hub, MockDataHub

logger = logging.getLogger(__name__)


@dataclass
class TestQuestion:
    """一道测试题"""
    id: str                          # 唯一 ID，如 "Q001"
    category: str                    # single_table_query | cross_source_join | aggregation | anomaly_detection | quality_trace | reasoning
    difficulty: str                  # easy | medium | hard
    domain: str                      # ERP | MES | cross_source
    question: str                    # 自然语言问题
    golden_answer: str               # 标准答案
    answer_type: str = "open"        # open | exact | numeric
    source_tables: list = field(default_factory=list)  # 涉及的源表
    hints: list = field(default_factory=list)           # 可选提示
    rubric: dict = field(default_factory=dict)          # 评分细则

    def to_dict(self) -> dict:
        return asdict(self)


# ── 全局缓存 ──────────────────────────────────────────
_snapshot_cache: Optional[dict] = None


def _ensure_snapshot() -> dict:
    global _snapshot_cache
    if _snapshot_cache is None:
        hub = get_hub()
        _snapshot_cache = hub.fetch_full_snapshot()
    return _snapshot_cache


def _snapshot() -> dict:
    return _ensure_snapshot()


def _erp_table(tid: str) -> dict:
    return _snapshot().get("ERP", {}).get("tables", {}).get(tid, {})


def _mes_table(tid: str) -> dict:
    return _snapshot().get("MES", {}).get("tables", {}).get(tid, {})


def _sample_rows(source: str, tid: str, n: int = 5) -> list:
    """获取某表的前 n 行样本"""
    snap = _snapshot()
    return snap.get(source, {}).get("tables", {}).get(tid, {}).get("sample_rows", [])[:n]


def _total_rows(source: str, tid: str) -> int:
    return _snapshot().get(source, {}).get("tables", {}).get(tid, {}).get("total_rows", 0)


def _pick_columns(source: str, tid: str, n: int = 3) -> list:
    """随机选取某表的 n 个列名"""
    cols = _snapshot().get(source, {}).get("tables", {}).get(tid, {}).get("columns", [])
    if len(cols) <= n:
        return cols
    return random.sample(cols, n)


# ═══════════════════════════════════════════════════════════════
#  题目生成器（按类别）
# ═══════════════════════════════════════════════════════════════

_counter = 0


def _next_id() -> str:
    global _counter
    _counter += 1
    return f"Q{_counter:04d}"


# ── 单表查询 ──────────────────────────────────────────

def gen_single_table_query() -> TestQuestion:
    """从单张表生成一个查询问题"""
    source = random.choice(["ERP", "MES"])
    snap = _snapshot()
    tables = list(snap.get(source, {}).get("tables", {}).values())
    if not tables:
        return gen_fallback()
    t = random.choice(tables)
    tid = t["id"] if "id" in t else ""
    rows = t.get("sample_rows", [])
    cols = t.get("columns", [])
    if not rows or not cols:
        return gen_fallback()

    # 选一个维度列和若干展示列
    dim_col = random.choice(cols[:6])  # 前几列通常是维度
    display_cols = [c for c in cols if c != dim_col][:4]

    # 选一个维度值
    sample_row = random.choice(rows)
    dim_val = sample_row.get(dim_col, "N/A")

    # 在全部 sample 中找出匹配该维度的行
    matching = [r for r in rows if r.get(dim_col) == dim_val]
    if not matching:
        matching = [sample_row]

    # 构建答案
    answer_lines = []
    answer_lines.append(f"查询条件：{dim_col} = {dim_val}")
    answer_lines.append(f"匹配行数（样本中）：{len(matching)}")
    answer_lines.append("")
    answer_lines.append(f"| {' | '.join(display_cols)} |")
    answer_lines.append(f"|{'|'.join(['---']*len(display_cols))}|")
    for r in matching[:5]:
        vals = [str(r.get(c, "null")) for c in display_cols]
        answer_lines.append(f"| {' | '.join(vals)} |")

    total = t.get("total_rows", 0)
    question = (
        f"在{source}系统的「{t.get('name', tid)}」表中，"
        f"查询 {dim_col} 为「{dim_val}」的所有记录。"
        f"该表共 {total} 行数据。请列出匹配到的记录（显示 {', '.join(display_cols)}）。"
    )

    return TestQuestion(
        id=_next_id(),
        category="single_table_query",
        difficulty="easy",
        domain=source,
        question=question,
        golden_answer="\n".join(answer_lines),
        answer_type="open",
        source_tables=[f"{source}:{tid}"],
        rubric={"key_fields": [dim_col], "display_fields": display_cols},
    )


# ── 跨源 JOIN ─────────────────────────────────────────

def gen_cross_source_join() -> TestQuestion:
    join_info = random.choice(CROSS_SOURCE_JOINS)
    erp_t = _erp_table(join_info["erp_table"])
    mes_t = _mes_table(join_info["mes_table"])
    if not erp_t or not mes_t:
        return gen_fallback()

    erp_key = join_info["erp_key"]
    mes_key = join_info["mes_key"]
    erp_rows = erp_t.get("sample_rows", [])
    mes_rows = mes_t.get("sample_rows", [])

    # 找到两边共有的 key 值
    erp_keys = {r.get(erp_key) for r in erp_rows if r.get(erp_key)}
    mes_keys = {r.get(mes_key) for r in mes_rows if r.get(mes_key)}
    common = erp_keys & mes_keys
    if not common:
        common = erp_keys | mes_keys

    # 选一个公共 key 值
    key_val = random.choice(list(common)[:10]) if common else "N/A"

    erp_match = [r for r in erp_rows if r.get(erp_key) == key_val]
    mes_match = [r for r in mes_rows if r.get(mes_key) == key_val]

    erp_cols = erp_t.get("columns", [])[:4]
    mes_cols = mes_t.get("columns", [])[:4]

    answer_lines = [
        f"跨源 JOIN 键：{erp_key} = {mes_key} = 「{key_val}」",
        "",
        f"**ERP {erp_t.get('name', '')} 侧匹配：**",
        f"| {' | '.join(erp_cols)} |",
        f"|{'|'.join(['---']*len(erp_cols))}|",
    ]
    for r in erp_match[:3]:
        answer_lines.append(f"| {' | '.join(str(r.get(c, 'null')) for c in erp_cols)} |")
    answer_lines.extend([
        "",
        f"**MES {mes_t.get('name', '')} 侧匹配：**",
        f"| {' | '.join(mes_cols)} |",
        f"|{'|'.join(['---']*len(mes_cols))}|",
    ])
    for r in mes_match[:3]:
        answer_lines.append(f"| {' | '.join(str(r.get(c, 'null')) for c in mes_cols)} |")

    question = (
        f"通过「{join_info['label']}」关联 ERP 的「{erp_t.get('name', '')}」和 MES 的「{mes_t.get('name', '')}」。"
        f"请查询 {erp_key}='{key_val}' 在两侧系统中的完整记录。"
        f"\n提示：需分别调用 ERP({join_info['erp_table']}) 和 MES({join_info['mes_table']}) 的 API。"
    )

    return TestQuestion(
        id=_next_id(),
        category="cross_source_join",
        difficulty="medium",
        domain="cross_source",
        question=question,
        golden_answer="\n".join(answer_lines),
        answer_type="open",
        source_tables=[f"ERP:{join_info['erp_table']}", f"MES:{join_info['mes_table']}"],
        rubric={"join_key": key_val, "join_type": join_info["label"]},
    )


# ── 聚合分析 ──────────────────────────────────────────

def gen_aggregation() -> TestQuestion:
    source = random.choice(["ERP", "MES"])
    snap = _snapshot()
    tables = list(snap.get(source, {}).get("tables", {}).items())
    if not tables:
        return gen_fallback()
    tid, t = random.choice(tables)
    rows = t.get("sample_rows", [])
    cols = t.get("columns", [])
    if not rows or not cols:
        return gen_fallback()

    # 找一个数值列做聚合
    num_col = None
    group_col = None
    for c in cols:
        vals = [r.get(c) for r in rows if r.get(c) is not None]
        if not vals:
            continue
        try:
            _ = float(vals[0])
            if num_col is None:
                num_col = c
        except (ValueError, TypeError):
            if group_col is None and len(set(str(v)[:6] for v in vals)) >= 2:
                group_col = c
        if num_col and group_col:
            break
    if not num_col:
        num_col = cols[0]
    if not group_col:
        group_col = cols[1] if len(cols) > 1 else cols[0]

    # 按 group_col 分组计算
    groups = {}
    for r in rows:
        g = r.get(group_col, "null")
        v = r.get(num_col)
        if v is not None:
            try:
                groups.setdefault(str(g), []).append(float(v))
            except ValueError:
                pass

    answer_lines = [f"聚合对象：{source} {t.get('name', tid)}", f"分组列：{group_col}，聚合列：{num_col}", ""]
    answer_lines.append(f"| {group_col} | 计数 | 总和 | 平均值 |")
    answer_lines.append(f"|{'---'*4}|")
    for g, vals in sorted(groups.items())[:8]:
        s = sum(vals)
        avg = s / len(vals) if vals else 0
        answer_lines.append(f"| {g} | {len(vals)} | {s:.2f} | {avg:.2f} |")

    question = (
        f"在{source}系统的「{t.get('name', tid)}」表中，按「{group_col}」分组，"
        f"统计「{num_col}」的计数、总和与平均值。"
    )

    return TestQuestion(
        id=_next_id(),
        category="aggregation",
        difficulty="medium",
        domain=source,
        question=question,
        golden_answer="\n".join(answer_lines),
        answer_type="open",
        source_tables=[f"{source}:{tid}"],
        rubric={"group_col": group_col, "agg_col": num_col},
    )


# ── 异常检测 ──────────────────────────────────────────

def gen_anomaly_detection() -> TestQuestion:
    # 用 t12 计量参数表（有标准上限/下限）
    t = _mes_table("t12")
    if not t:
        return gen_fallback()
    rows = t.get("sample_rows", [])
    if not rows:
        return gen_fallback()

    # 筛选异常记录
    anomalies = [r for r in rows if r.get("是否异常") == "Y"]
    normal = [r for r in rows if r.get("是否异常") != "Y"]

    if not anomalies:
        # 模拟：从正常中标记一些
        anomalies = random.sample(normal, min(3, len(normal)))
        normal = [r for r in normal if r not in anomalies]

    anomaly = random.choice(anomalies)
    cols = ["设备/仪表编码", "设备/仪表名称", "参数项名称", "参数值", "单位", "标准下限", "标准上限", "是否异常", "异常说明"]

    answer_lines = [
        f"异常记录详情：",
        f"| {' | '.join(cols)} |",
        f"|{'|'.join(['---']*len(cols))}|",
    ]
    for r in anomalies[:5]:
        answer_lines.append(f"| {' | '.join(str(r.get(c, 'null')) for c in cols)} |")
    answer_lines.append(f"\n总异常数：{len(anomalies)}（样本中）")

    question = (
        f"在 MES 系统的「MES计量参数记录」表中，请找出所有「是否异常」='Y' 的记录，"
        f"并分析异常原因。该表记录了设备/仪表的实时参数，包含标准上下限。"
    )

    return TestQuestion(
        id=_next_id(),
        category="anomaly_detection",
        difficulty="medium",
        domain="MES",
        question=question,
        golden_answer="\n".join(answer_lines),
        answer_type="open",
        source_tables=["MES:t12"],
        rubric={"expected_count": len(anomalies)},
    )


# ── 质检追溯 ──────────────────────────────────────────

def gen_quality_trace() -> TestQuestion:
    t = _mes_table("t11")
    if not t:
        return gen_fallback()
    rows = t.get("sample_rows", [])
    if not rows:
        return gen_fallback()

    # 找一个不合格的
    fails = [r for r in rows if r.get("检验结论") == "不合格"]
    if not fails:
        fails = random.sample(rows, min(1, len(rows)))

    fail = random.choice(fails)
    batch = fail.get("批次号", "")
    cols = t.get("columns", [])[:8]

    answer_lines = [
        f"不合格批次：{batch}",
        f"| {' | '.join(cols)} |",
        f"|{'|'.join(['---']*len(cols))}|",
    ]
    for r in fails[:5]:
        answer_lines.append(f"| {' | '.join(str(r.get(c, 'null')) for c in cols)} |")
    answer_lines.append(f"\n不合格总数：{len(fails)}（样本中）")

    question = (
        f"在 MES 系统的「MES质检批次记录」中，请找出检验结论为「不合格」的所有批次，"
        f"并说明每批的不合格原因和不良类别。"
    )

    return TestQuestion(
        id=_next_id(),
        category="quality_trace",
        difficulty="easy",
        domain="MES",
        question=question,
        golden_answer="\n".join(answer_lines),
        answer_type="open",
        source_tables=["MES:t11"],
        rubric={"expected_fail_count": len(fails)},
    )


# ── 综合推理 ──────────────────────────────────────────

def gen_reasoning() -> TestQuestion:
    """生成需要多步推理的综合题"""
    # 从 t07 工单和 t05 采购订单中组合
    t07 = _mes_table("t07")
    t05 = _erp_table("t05")
    if not t07 or not t05:
        return gen_fallback()

    mo_rows = t07.get("sample_rows", [])
    if not mo_rows:
        return gen_fallback()

    # 找有销售订单号关联的工单
    linked = [r for r in mo_rows if r.get("关联销售单号")]
    if not linked:
        linked = mo_rows
    mo = random.choice(linked)

    sales_order = mo.get("关联销售单号", "N/A")
    product_code = mo.get("货品编码", "N/A")
    product_name = mo.get("货品名称", "N/A")
    plan_qty = mo.get("计划产量", "N/A")
    done_qty = mo.get("已完工量", "N/A")
    status = mo.get("工单状态", "N/A")

    answer_lines = [
        f"生产工单: {mo.get('工单号', 'N/A')}",
        f"关联销售订单: {sales_order}",
        f"货品: {product_code} ({product_name})",
        f"计划产量: {plan_qty}，已完工: {done_qty}，状态: {status}",
        "",
        "分析：",
        f"1. 该工单通过销售订单号 {sales_order} 与 ERP 销售订单关联",
        f"2. 完工率: {done_qty}/{plan_qty}",
        "3. 如需追溯采购，需在 ERP t05 表中按物料编码查找对应采购订单",
    ]

    question = (
        f"某生产工单「{mo.get('工单号', 'N/A')}」正在生产「{product_name}」（{product_code}），"
        f"关联销售订单「{sales_order}」。请分析："
        f"\n1. 该工单的完工进度"
        f"\n2. 如何追溯到对应的采购订单和质检记录"
        f"\n3. 如果该工单延期，可能影响哪些下游环节"
    )

    return TestQuestion(
        id=_next_id(),
        category="reasoning",
        difficulty="hard",
        domain="cross_source",
        question=question,
        golden_answer="\n".join(answer_lines),
        answer_type="open",
        source_tables=["MES:t07", "ERP:t05", "ERP:t04"],
        rubric={"reasoning_steps": 3},
    )


# ── 兜底 ──────────────────────────────────────────────

def gen_fallback() -> TestQuestion:
    return TestQuestion(
        id=_next_id(),
        category="single_table_query",
        difficulty="easy",
        domain="ERP",
        question="请列出 ERP 系统中所有可用的表及其名称。",
        golden_answer="ERP 表：t01 供应商主数据, t02 物料货品主数据, t03 BOM物料清单, t04 销售订单, t05 采购订单, t06 采购到货记录, t08 物料库存快照, t09 MRP建议表",
        answer_type="open",
        source_tables=["ERP:tables"],
        rubric={"key_fields": []},
    )


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

GENERATORS = {
    "single_table_query": gen_single_table_query,
    "cross_source_join": gen_cross_source_join,
    "aggregation": gen_aggregation,
    "anomaly_detection": gen_anomaly_detection,
    "quality_trace": gen_quality_trace,
    "reasoning": gen_reasoning,
}


def generate_test_suite(n: int = None) -> list[TestQuestion]:
    """生成一轮测试套件"""
    n = n or QUESTIONS_PER_ROUND
    random.seed()  # 每轮不同

    # 按权重分配各类别题目数
    allocation = {}
    for cat, w in CATEGORY_WEIGHTS.items():
        allocation[cat] = max(1, int(n * w))

    # 补足因取整造成的差额
    allocated = sum(allocation.values())
    if allocated < n:
        # 优先给权重最高的类别
        top_cat = max(CATEGORY_WEIGHTS, key=CATEGORY_WEIGHTS.get)
        allocation[top_cat] += (n - allocated)

    questions = []
    for cat, count in allocation.items():
        gen = GENERATORS.get(cat, gen_fallback)
        for _ in range(count):
            try:
                q = gen()
                questions.append(q)
            except Exception as e:
                logger.warning(f"生成 {cat} 题目失败: {e}")
                questions.append(gen_fallback())

    return questions[:n]


def save_test_suite(questions: list[TestQuestion], filename: str) -> Path:
    """保存测试套件到 JSON"""
    path = TEST_SUITE_DIR / filename
    data = [q.to_dict() for q in questions]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_test_suite(filename: str) -> list[TestQuestion]:
    """从 JSON 加载测试套件"""
    path = TEST_SUITE_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [TestQuestion(**d) for d in data]