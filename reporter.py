#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告生成器 — 每轮产出测试报告 + 迭代报告 + 汇总趋势"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

from config import REPORTS_DIR, SUMMARY_JSON_PATH
from scorer import RoundResult, QuestionResult
from iteration_engine import IterationResult, FailureCluster

logger = logging.getLogger(__name__)

# 北京时间
TZ = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def _timestamp_file() -> str:
    return datetime.now(TZ).strftime("%Y%m%d-%H%M%S")


# ═══════════════════════════════════════════════════════════════
#  Markdown 报告
# ═══════════════════════════════════════════════════════════════

def _score_bar(score: float, width: int = 20) -> str:
    filled = int(score * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {score:.1%}"


def _color_emoji(score: float) -> str:
    if score >= 0.8:
        return "🟢"
    elif score >= 0.6:
        return "🟡"
    else:
        return "🔴"


def generate_test_report(round_result: RoundResult) -> str:
    """生成单轮测试报告（Markdown）"""
    rr = round_result
    lines = []

    lines.append(f"# 测试报告 — 第 {rr.round_id} 轮")
    lines.append(f"**生成时间**：{rr.timestamp or _now()}")
    lines.append("")

    # ── 总览 ──
    lines.append("## 📊 总览")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|----|")
    lines.append(f"| 题目总数 | {rr.total_questions} |")
    lines.append(f"| 平均得分 | {_color_emoji(rr.avg_score)} {rr.avg_score:.2%} |")
    lines.append(f"| 最低分 | {rr.min_score:.2%} |")
    lines.append(f"| 最高分 | {rr.max_score:.2%} |")
    lines.append(f"| 通过率 | {rr.pass_rate:.1%} ({int(rr.pass_rate * rr.total_questions)}/{rr.total_questions}) |")
    lines.append("")

    # ── 按类别 ──
    lines.append("## 📂 按类别得分")
    lines.append("")
    if rr.category_scores:
        lines.append(f"| 类别 | 得分 | 可视化 |")
        lines.append(f"|------|------|--------|")
        for cat, score in sorted(rr.category_scores.items(), key=lambda x: -x[1]):
            lines.append(f"| {cat} | {score:.2%} | {_score_bar(score)} |")
    else:
        lines.append("（无分类数据）")
    lines.append("")

    # ── 按难度 ──
    if rr.difficulty_scores:
        lines.append("## 🎯 按难度得分")
        lines.append("")
        lines.append(f"| 难度 | 得分 |")
        lines.append(f"|------|------|")
        for diff, score in sorted(rr.difficulty_scores.items(), key=lambda x: -x[1]):
            lines.append(f"| {diff} | {score:.2%} |")
        lines.append("")

    # ── 按领域 ──
    if rr.domain_scores:
        lines.append("## 🏭 按领域得分")
        lines.append("")
        lines.append(f"| 领域 | 得分 |")
        lines.append(f"|------|------|")
        for dom, score in sorted(rr.domain_scores.items(), key=lambda x: -x[1]):
            lines.append(f"| {dom} | {score:.2%} |")
        lines.append("")

    # ── 逐题详情 ──
    lines.append("## 📝 逐题详情")
    lines.append("")
    for i, qr in enumerate(rr.questions, 1):
        emoji = "✅" if qr.passed else "❌"
        lines.append(f"### {emoji} {i}. {qr.question_id} [{qr.category}] [{qr.difficulty}]")
        lines.append(f"**得分**：{qr.total_score:.2%} | {qr.elapsed_ms}ms | {qr.tokens_in}+{qr.tokens_out} tokens")
        lines.append("")
        # 维度明细
        if qr.details:
            lines.append(f"| 维度 | 得分 | 评价 |")
            lines.append(f"|------|------|------|")
            for d in qr.details:
                lines.append(f"| {d.label} | {d.score:.2%} | {d.comment} |")
            lines.append("")
        lines.append(f"<details><summary>📋 模型回答</summary>\n\n```\n{qr.model_answer[:2000]}\n```\n</details>")
        lines.append("")

    # ── 失败案例 ──
    if rr.failures:
        lines.append("## ⚠️ 失败案例汇总")
        lines.append("")
        lines.append(f"共 {len(rr.failures)} 题未通过（得分 < {60}%）：")
        lines.append("")
        for f in rr.failures:
            lines.append(f"- **{f.question_id}** [{f.category}] — {f.total_score:.1%}")
            # 最低分维度
            if f.details:
                worst = min(f.details, key=lambda d: d.score)
                lines.append(f"  - 最弱维度：{worst.label} ({worst.score:.0%})：{worst.comment}")
        lines.append("")

    # ── 使用的 Prompt ──
    lines.append("## 🔧 使用的 System Prompt")
    lines.append("")
    lines.append(f"```\n{rr.system_prompt_used[:3000]}\n```")
    lines.append("")

    return "\n".join(lines)


def generate_iteration_report(iter_result: IterationResult) -> str:
    """生成迭代分析报告"""
    ir = iter_result
    lines = []

    lines.append(f"# 迭代分析报告 — 第 {ir.round_id} 轮后")
    lines.append(f"**生成时间**：{_now()}")
    lines.append("")

    # ── 薄弱领域 ──
    lines.append("## 🔍 薄弱领域")
    lines.append("")
    if ir.weak_areas:
        for w in ir.weak_areas:
            lines.append(f"- {w}")
    else:
        lines.append("所有领域表现良好。")
    lines.append("")

    # ── 失败模式聚类 ──
    lines.append("## 📊 失败模式聚类")
    lines.append("")
    if ir.clusters:
        lines.append(f"| 类别 | 失败数 | 平均分 | 共性模式 | 建议修复 |")
        lines.append(f"|------|--------|--------|----------|----------|")
        for cl in ir.clusters:
            lines.append(f"| {cl.category} | {cl.count} | {cl.avg_score:.2%} | {cl.common_pattern} | {cl.suggested_fix} |")
        lines.append("")
    else:
        lines.append("未检测到显著的失败模式聚类。")
    lines.append("")

    # ── Prompt 变更 ──
    lines.append("## 🔄 Prompt 变更")
    lines.append("")
    if ir.prompt_changed:
        lines.append(f"✅ Prompt 已升级到 v{ir.new_prompt_version}")
        lines.append(f"**变更原因**：{ir.change_reason}")
    else:
        lines.append("本轮未触发 Prompt 变更。")
    lines.append("")

    # ── 改进建议 ──
    lines.append("## 💡 改进建议")
    lines.append("")
    if ir.improvement_notes:
        for note in ir.improvement_notes:
            lines.append(f"- {note}")
    else:
        lines.append("暂无额外建议。")
    lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  汇总趋势（summary.json）
# ═══════════════════════════════════════════════════════════════

def update_summary(round_result: RoundResult, iter_result: IterationResult):
    """更新汇总趋势文件"""
    summary = {"rounds": [], "trend": {}}

    if SUMMARY_JSON_PATH.exists():
        try:
            with open(SUMMARY_JSON_PATH, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception:
            pass

    record = {
        "round": round_result.round_id,
        "timestamp": round_result.timestamp or _now(),
        "questions": round_result.total_questions,
        "avg_score": round_result.avg_score,
        "pass_rate": round_result.pass_rate,
        "category_scores": round_result.category_scores,
        "difficulty_scores": round_result.difficulty_scores,
        "domain_scores": round_result.domain_scores,
        "prompt_version": iter_result.new_prompt_version,
        "prompt_changed": iter_result.prompt_changed,
        "failure_count": len(round_result.failures),
        "weak_areas": iter_result.weak_areas,
        "total_tokens": sum(q.tokens_in + q.tokens_out for q in round_result.questions),
        "total_elapsed_ms": sum(q.elapsed_ms for q in round_result.questions),
    }

    summary["rounds"].append(record)

    # 计算趋势
    scores = [r["avg_score"] for r in summary["rounds"]]
    if len(scores) >= 2:
        summary["trend"] = {
            "score_delta": round(scores[-1] - scores[-2], 4),
            "direction": "improving" if scores[-1] > scores[-2] else "declining" if scores[-1] < scores[-2] else "stable",
            "best_round": max(range(len(scores)), key=lambda i: scores[i]) + 1,
            "best_score": max(scores),
        }

    with open(SUMMARY_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def generate_trend_report() -> str:
    """生成跨轮次的趋势报告"""
    if not SUMMARY_JSON_PATH.exists():
        return "暂无汇总数据。"

    with open(SUMMARY_JSON_PATH, "r", encoding="utf-8") as f:
        summary = json.load(f)

    rounds = summary.get("rounds", [])
    if not rounds:
        return "暂无轮次数据。"

    lines = []
    lines.append("# 趋势报告")
    lines.append(f"**总轮次**：{len(rounds)}")
    lines.append("")

    trend = summary.get("trend", {})
    if trend:
        lines.append(f"**趋势方向**：{trend.get('direction', 'N/A')}")
        lines.append(f"**最新变化**：{trend.get('score_delta', 0):+.2%}")
        lines.append(f"**最佳轮次**：第 {trend.get('best_round', '?')} 轮 ({trend.get('best_score', 0):.2%})")
        lines.append("")

    lines.append("## 逐轮趋势")
    lines.append("")
    lines.append("| 轮次 | 时间 | 平均分 | 通过率 | Prompt版本 | 失败数 | 薄弱领域 |")
    lines.append("|------|------|--------|--------|-----------|--------|----------|")
    for r in rounds:
        weak = ", ".join(r.get("weak_areas", [])[:3]) or "-"
        lines.append(
            f"| {r['round']} | {r.get('timestamp','')[:16]} | "
            f"{r['avg_score']:.2%} | {r['pass_rate']:.1%} | "
            f"v{r['prompt_version']} | {r['failure_count']} | {weak} |"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  便捷入口
# ═══════════════════════════════════════════════════════════════

def write_all_reports(round_result: RoundResult, iter_result: IterationResult):
    """写入所有本轮报告"""
    ts = _timestamp_file()
    round_id = round_result.round_id

    # 测试报告
    test_md = generate_test_report(round_result)
    test_path = REPORTS_DIR / f"iteration_{round_id:03d}_test_report.md"
    with open(test_path, "w", encoding="utf-8") as f:
        f.write(test_md)
    logger.info(f"测试报告: {test_path}")

    # 迭代报告
    iter_md = generate_iteration_report(iter_result)
    iter_path = REPORTS_DIR / f"iteration_{round_id:03d}_iteration_report.md"
    with open(iter_path, "w", encoding="utf-8") as f:
        f.write(iter_md)
    logger.info(f"迭代报告: {iter_path}")

    # 更新汇总
    update_summary(round_result, iter_result)

    # 每 5 轮生成一次趋势报告
    if round_id % 5 == 0:
        trend_md = generate_trend_report()
        trend_path = REPORTS_DIR / f"trend_round_{round_id:03d}.md"
        with open(trend_path, "w", encoding="utf-8") as f:
            f.write(trend_md)
        logger.info(f"趋势报告: {trend_path}")

    return test_path, iter_path