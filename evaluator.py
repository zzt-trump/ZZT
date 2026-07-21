#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock Data Harness — 评估器 (evaluator.py)

规则评估 + 分项报告。
支持 exact / set / numeric_range / exists 四种答案类型。
"""

import re
import json
from typing import Any
from collections import Counter


# ── 核心评估函数 ─────────────────────────────────────────

def evaluate_exact(model_answer: str, expected: str) -> dict[str, Any]:
    """精确匹配：去除首尾空白后完全相等"""
    model_clean = model_answer.strip().lower()
    expected_clean = expected.strip().lower()
    passed = model_clean == expected_clean
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "detail": "exact match" if passed else f"expected '{expected_clean}', got '{model_clean[:100]}'",
    }


def evaluate_set(model_answer: str, expected: str) -> dict[str, Any]:
    """
    集合匹配：计算 Jaccard 相似度 + Precision/Recall。
    支持逗号、分号、换行、编号列表等分隔符。
    """
    # 提取 expected 中的元素
    expected_items = _extract_items(expected)
    model_items = _extract_items(model_answer)

    if not expected_items:
        return {"passed": True, "score": 1.0, "detail": "no expected items to check"}

    expected_set = set(expected_items)
    model_set = set(model_items)

    intersection = expected_set & model_set
    union = expected_set | model_set

    precision = len(intersection) / len(model_set) if model_set else 0.0
    recall = len(intersection) / len(expected_set) if expected_set else 1.0
    jaccard = len(intersection) / len(union) if union else 1.0

    # 综合评分：recall 权重 0.6，precision 权重 0.4
    score = 0.6 * recall + 0.4 * precision

    missing = expected_set - model_set
    extra = model_set - expected_set

    detail_parts = []
    if missing:
        detail_parts.append(f"missing: {missing}")
    if extra:
        detail_parts.append(f"extra: {extra}")
    detail = "; ".join(detail_parts) if detail_parts else "all matched"

    return {
        "passed": score >= 0.8,
        "score": round(score, 3),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "jaccard": round(jaccard, 3),
        "detail": detail,
        "missing": list(missing),
        "extra": list(extra),
    }


def evaluate_numeric_range(model_answer: str, expected: str, tolerance: float = 0.05) -> dict[str, Any]:
    """
    数值范围匹配：从答案中提取数字，与期望值比较，允许 ±tolerance 容差。
    """
    # 提取模型答案中的数字
    model_nums = _extract_numbers(model_answer)
    expected_nums = _extract_numbers(expected)

    if not expected_nums:
        return {"passed": True, "score": 1.0, "detail": "no expected numbers"}

    if not model_nums:
        return {"passed": False, "score": 0.0, "detail": "no numbers found in model answer"}

    # 取第一个期望数字和第一个模型数字比较
    expected_val = expected_nums[0]
    model_val = model_nums[0]

    if expected_val == 0:
        passed = model_val == 0
        score = 1.0 if passed else 0.0
    else:
        diff = abs(model_val - expected_val) / abs(expected_val)
        passed = diff <= tolerance
        score = max(0.0, 1.0 - diff)

    return {
        "passed": passed,
        "score": round(score, 3),
        "detail": f"expected ~{expected_val}, got {model_val}",
    }


def evaluate_exists(model_answer: str, expected: str) -> dict[str, Any]:
    """
    存在性判断：检查答案中是否包含关键实体。
    只要模型给出了有意义的答案（非空、非拒绝），就算通过。
    如果 expected 非空，则检查是否包含关键子串。
    """
    model_clean = model_answer.strip()

    # 拒绝回答或空答案
    if not model_clean or len(model_clean) < 5:
        return {"passed": False, "score": 0.0, "detail": "empty or too short answer"}

    if "不存在" in model_clean and "error" in model_clean.lower():
        return {"passed": False, "score": 0.0, "detail": "model reported error"}

    # 如果 expected 有具体值，检查是否包含
    if expected and expected.strip():
        expected_items = _extract_items(expected)
        found = []
        not_found = []
        for item in expected_items:
            if item.lower() in model_clean.lower():
                found.append(item)
            else:
                not_found.append(item)
        score = len(found) / len(expected_items) if expected_items else 1.0
        detail = f"found: {found}, not_found: {not_found}" if not_found else "all found"
        return {
            "passed": score >= 0.5,
            "score": round(score, 3),
            "detail": detail,
            "found": found,
            "not_found": not_found,
        }

    # 无法确定，给一个基本分
    return {"passed": True, "score": 0.7, "detail": "answer exists, manual review recommended"}


# ── 辅助函数 ────────────────────────────────────────────

def _extract_items(text: str) -> list[str]:
    """从文本中提取列表项"""
    text = text.strip()
    items = []

    # 尝试按逗号分割
    if "," in text:
        items = [s.strip() for s in text.split(",") if s.strip()]
    # 尝试按分号分割
    elif ";" in text:
        items = [s.strip() for s in text.split(";") if s.strip()]
    # 尝试按编号列表
    elif re.search(r'\d+[\.\)、]\s', text):
        items = [s.strip() for s in re.split(r'\d+[\.\)、]\s*', text) if s.strip()]
    else:
        items = [text]

    # 清理常见的编号前缀
    cleaned = []
    for item in items:
        item = re.sub(r'^[\d]+[\.\)、]\s*', '', item)
        item = item.strip()
        if item:
            cleaned.append(item)
    return cleaned


def _extract_numbers(text: str) -> list[float]:
    """从文本中提取所有数字"""
    pattern = r'-?\d+\.?\d*'
    matches = re.findall(pattern, text)
    return [float(m) for m in matches]


# ── 评估入口 ─────────────────────────────────────────────

def evaluate_answer(
    model_answer: str,
    test_case: dict[str, Any],
) -> dict[str, Any]:
    """
    评估单个测试用例的答案。

    返回:
    {
        "case_id": str,
        "passed": bool,
        "score": float,
        "grade": "PASS" | "PARTIAL" | "FAIL",
        "detail": str,
        "answer_type": str,
    }
    """
    answer_type = test_case.get("answer_type", "exists")
    expected = test_case.get("expected_answer", "") or ""

    if answer_type == "exact":
        result = evaluate_exact(model_answer, expected)
    elif answer_type == "set":
        result = evaluate_set(model_answer, expected)
    elif answer_type == "numeric_range":
        result = evaluate_numeric_range(model_answer, expected)
    elif answer_type == "exists":
        result = evaluate_exists(model_answer, expected)
    else:
        result = evaluate_exists(model_answer, expected)

    score = result["score"]
    if score >= 0.9:
        grade = "PASS"
    elif score >= 0.5:
        grade = "PARTIAL"
    else:
        grade = "FAIL"

    return {
        "case_id": test_case["id"],
        "passed": result["passed"],
        "score": score,
        "grade": grade,
        "detail": result.get("detail", ""),
        "answer_type": answer_type,
        "extra": {k: v for k, v in result.items() if k not in ("passed", "score", "detail")},
    }


def evaluate_tool_usage(
    actual_tools: list[str],
    expected_tools: list[str],
) -> dict[str, Any]:
    """评估 tool 调用的准确性和效率"""
    if not expected_tools:
        return {"tool_accuracy": 1.0, "tool_efficiency": 1.0, "detail": "no expected tools"}

    actual_set = set(actual_tools)
    expected_set = set(expected_tools)

    # 准确性：期望调用的 tool 中有多少被调用了
    intersection = actual_set & expected_set
    accuracy = len(intersection) / len(expected_set) if expected_set else 1.0

    # 效率：实际调用的 tool 中有多少是必要的
    efficiency = len(intersection) / len(actual_set) if actual_set else 0.0

    missing = expected_set - actual_set
    extra = actual_set - expected_set

    return {
        "tool_accuracy": round(accuracy, 3),
        "tool_efficiency": round(efficiency, 3),
        "detail": f"missing tools: {missing}, extra tools: {extra}" if (missing or extra) else "all tools matched",
    }


# ── 汇总报告 ─────────────────────────────────────────────

def generate_report(results: list[dict[str, Any]]) -> str:
    """
    生成汇总报告。
    results: 每个元素包含 evaluate_answer 和 evaluate_tool_usage 的结果。
    """
    total = len(results)
    if total == 0:
        return "无测试结果。"

    grades = Counter(r["grade"] for r in results)
    pass_count = grades.get("PASS", 0)
    partial_count = grades.get("PARTIAL", 0)
    fail_count = grades.get("FAIL", 0)
    avg_score = sum(r["score"] for r in results) / total

    lines = [
        "=" * 60,
        "  Mock Data Harness — 测试报告",
        "=" * 60,
        "",
        f"总用例数: {total}",
        f"平均分: {avg_score:.2%}",
        f"通过率: {pass_count}/{total} ({pass_count/total:.1%})",
        f"部分通过: {partial_count}/{total} ({partial_count/total:.1%})",
        f"失败: {fail_count}/{total} ({fail_count/total:.1%})",
        "",
    ]

    # 按难度分层
    lines.append("─" * 40)
    lines.append("按难度分层")
    lines.append("─" * 40)
    by_difficulty: dict[str, list] = {}
    for r in results:
        diff = r.get("difficulty", "unknown")
        by_difficulty.setdefault(diff, []).append(r)
    for diff in ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "ADV", "INT"]:
        if diff in by_difficulty:
            items = by_difficulty[diff]
            d_pass = sum(1 for r in items if r["grade"] == "PASS")
            d_avg = sum(r["score"] for r in items) / len(items)
            lines.append(f"  {diff}: {len(items)} 题, 通过率 {d_pass}/{len(items)}, 平均分 {d_avg:.2%}")

    # 按陷阱类型分层
    lines.append("")
    lines.append("─" * 40)
    lines.append("按陷阱类型分层")
    lines.append("─" * 40)
    by_trap: dict[str, list] = {}
    for r in results:
        for trap in r.get("traps", []):
            by_trap.setdefault(trap, []).append(r)
    for trap, items in sorted(by_trap.items()):
        t_pass = sum(1 for r in items if r["grade"] == "PASS")
        t_avg = sum(r["score"] for r in items) / len(items)
        lines.append(f"  {trap}: {len(items)} 题, 通过率 {t_pass}/{len(items)}, 平均分 {t_avg:.2%}")

    # Tool 效率
    if any("tool_accuracy" in r for r in results):
        lines.append("")
        lines.append("─" * 40)
        lines.append("Tool 调用效率")
        lines.append("─" * 40)
        tool_acc = [r["tool_accuracy"] for r in results if "tool_accuracy" in r]
        tool_eff = [r["tool_efficiency"] for r in results if "tool_efficiency" in r]
        if tool_acc:
            lines.append(f"  平均 tool 准确率: {sum(tool_acc)/len(tool_acc):.2%}")
        if tool_eff:
            lines.append(f"  平均 tool 效率: {sum(tool_eff)/len(tool_eff):.2%}")

    # 错误日志
    all_errors = []
    for r in results:
        if r.get("errors"):
            for e in r["errors"]:
                all_errors.append(f"  [{r['case_id']}] {e}")
    if all_errors:
        lines.append("")
        lines.append("─" * 40)
        lines.append("错误日志")
        lines.append("─" * 40)
        lines.extend(all_errors[:20])  # 最多显示 20 条
        if len(all_errors) > 20:
            lines.append(f"  ... 还有 {len(all_errors) - 20} 条错误")

    # 失败用例详情
    failed = [r for r in results if r["grade"] == "FAIL"]
    if failed:
        lines.append("")
        lines.append("─" * 40)
        lines.append("失败用例详情")
        lines.append("─" * 40)
        for r in failed:
            lines.append(f"  [{r['case_id']}] {r.get('question', '')[:80]}")
            lines.append(f"    分数: {r['score']:.2f}, 详情: {r.get('detail', '')[:120]}")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def generate_json_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    """生成 JSON 格式的汇总报告"""
    total = len(results)
    grades = Counter(r["grade"] for r in results)
    avg_score = sum(r["score"] for r in results) / total if total else 0

    by_difficulty = {}
    for r in results:
        diff = r.get("difficulty", "unknown")
        by_difficulty.setdefault(diff, []).append(r)

    by_trap = {}
    for r in results:
        for trap in r.get("traps", []):
            by_trap.setdefault(trap, []).append(r)

    return {
        "total": total,
        "average_score": round(avg_score, 4),
        "grades": dict(grades),
        "pass_rate": grades.get("PASS", 0) / total if total else 0,
        "by_difficulty": {
            diff: {
                "count": len(items),
                "pass_count": sum(1 for r in items if r["grade"] == "PASS"),
                "average_score": round(sum(r["score"] for r in items) / len(items), 4),
            }
            for diff, items in sorted(by_difficulty.items())
        },
        "by_trap": {
            trap: {
                "count": len(items),
                "pass_count": sum(1 for r in items if r["grade"] == "PASS"),
                "average_score": round(sum(r["score"] for r in items) / len(items), 4),
            }
            for trap, items in sorted(by_trap.items())
        },
        "results": results,
    }