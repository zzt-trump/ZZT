#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评分引擎 — 多维度评估模型回答质量"""

import re
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

from config import SCORING_DIMENSIONS, PASS_THRESHOLD

logger = logging.getLogger(__name__)


@dataclass
class ScoreDetail:
    """单维度评分"""
    dimension: str
    label: str
    score: float          # 0.0 ~ 1.0
    weight: float
    weighted: float       # score * weight
    comment: str = ""


@dataclass
class QuestionResult:
    """单题评分结果"""
    question_id: str
    category: str
    difficulty: str
    domain: str
    question: str
    golden_answer: str
    model_answer: str
    total_score: float          # 0.0 ~ 1.0
    passed: bool
    details: list = field(default_factory=list)  # list[ScoreDetail]
    tokens_in: int = 0
    tokens_out: int = 0
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class RoundResult:
    """一轮测试的汇总结果"""
    round_id: int
    total_questions: int
    avg_score: float
    min_score: float
    max_score: float
    pass_rate: float          # 通过率
    category_scores: dict     # {category: avg_score}
    difficulty_scores: dict   # {difficulty: avg_score}
    domain_scores: dict       # {domain: avg_score}
    questions: list = field(default_factory=list)  # list[QuestionResult]
    failures: list = field(default_factory=list)   # 未通过的题目
    system_prompt_used: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ═══════════════════════════════════════════════════════════════
#  评分函数
# ═══════════════════════════════════════════════════════════════

def _score_accuracy(model_answer: str, golden_answer: str) -> tuple[float, str]:
    """准确性评分：检查关键信息是否匹配"""
    ga_lower = golden_answer.lower()
    ma_lower = model_answer.lower()

    # 提取 golden answer 中的关键数值和编码
    key_patterns = [
        r'\b(SUP\d+)\b', r'\b(RM\d+)\b', r'\b(FG\d+)\b', r'\b(SF\d+)\b',
        r'\b(MO\d+)\b', r'\b(PO\d+)\b', r'\b(t\d{2})\b',
        r'\b(合格|不合格|待检|免检)\b',
        r'\b(计划|已下达|生产中|已完工|已关闭)\b',
        r'\b(执行中|已完成|部分到货|新建)\b',
    ]
    key_values = set()
    for pat in key_patterns:
        for m in re.finditer(pat, golden_answer):
            key_values.add(m.group(1).lower())

    if not key_values:
        # 没有可提取的关键值，用字符级相似度
        matches = sum(1 for a, b in zip(ga_lower, ma_lower) if a == b)
        score = matches / max(len(ga_lower), 1)
        return min(score, 1.0), "字符级相似度"

    matched = sum(1 for v in key_values if v in ma_lower)
    score = matched / len(key_values) if key_values else 0.5
    comment = f"关键值匹配: {matched}/{len(key_values)}"
    return score, comment


def _score_completeness(model_answer: str, golden_answer: str) -> tuple[float, str]:
    """完整性评分：检查是否覆盖了所有要求的子任务"""
    # 统计 golden answer 中的行数作为"应有信息量"
    ga_lines = [l.strip() for l in golden_answer.split("\n") if l.strip() and not l.startswith("|")]
    ma_lines = [l.strip() for l in model_answer.split("\n") if l.strip()]

    if not ga_lines:
        return 0.5, "golden answer 为空"

    # 简单启发式：模型回答长度与标准答案长度之比
    len_ratio = min(len(ma_lines) / max(len(ga_lines), 1), 2.0)
    # 但太长也不好（可能冗余）
    if len_ratio < 0.3:
        score = 0.2
        comment = f"回答过短 ({len(ma_lines)} 行 vs {len(ga_lines)} 行)"
    elif len_ratio < 0.7:
        score = 0.5
        comment = f"回答偏短 ({len(ma_lines)} 行 vs {len(ga_lines)} 行)"
    elif len_ratio > 1.5:
        score = 0.7
        comment = f"回答偏长 ({len(ma_lines)} 行 vs {len(ga_lines)} 行)"
    else:
        score = 0.9
        comment = f"长度适中 ({len(ma_lines)} 行 vs {len(ga_lines)} 行)"
    return score, comment


def _score_format(model_answer: str, golden_answer: str) -> tuple[float, str]:
    """格式规范评分：检查是否使用了 Markdown 表格等结构化格式"""
    score = 0.5
    reasons = []

    if "|" in model_answer and "---" in model_answer:
        score += 0.2
        reasons.append("使用了 Markdown 表格")
    elif re.search(r'\d+\.\s', model_answer):
        score += 0.1
        reasons.append("使用了编号列表")

    if "**" in model_answer:
        score += 0.1
        reasons.append("使用了加粗强调")

    if len(model_answer.split("\n\n")) >= 2:
        score += 0.1
        reasons.append("段落分隔清晰")

    if not reasons:
        reasons.append("缺少结构化格式")

    return min(score, 1.0), "; ".join(reasons)


def _score_reasoning(model_answer: str, golden_answer: str) -> tuple[float, str]:
    """推理逻辑评分：检查是否包含推理过程"""
    reasoning_keywords = [
        r'因为', r'所以', r'因此', r'由于', r'分析', r'推理',
        r'because', r'therefore', r'analysis', r'reason',
        r'第一步', r'第二步', r'首先', r'然后', r'最后',
        r'追溯', r'关联', r'通过.*找到',
    ]
    ma_lower = model_answer.lower()

    found = []
    for kw in reasoning_keywords:
        if re.search(kw, ma_lower):
            found.append(kw)

    if len(found) >= 3:
        score = 0.9
        comment = f"推理充分（关键词: {', '.join(found[:3])}）"
    elif len(found) >= 1:
        score = 0.5
        comment = f"有一定推理（关键词: {', '.join(found)}）"
    else:
        score = 0.2
        comment = "缺少推理过程"

    return score, comment


SCORERS = {
    "accuracy":     _score_accuracy,
    "completeness": _score_completeness,
    "format":       _score_format,
    "reasoning":    _score_reasoning,
}


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

def score_answer(model_answer: str, golden_answer: str,
                 category: str = "single_table_query") -> tuple[float, list[ScoreDetail]]:
    """对单个回答进行多维度评分，返回 (总分, 明细列表)"""
    details = []
    total = 0.0

    for dim_key, dim_cfg in SCORING_DIMENSIONS.items():
        scorer = SCORERS.get(dim_key)
        if scorer:
            raw, comment = scorer(model_answer, golden_answer)
        else:
            raw, comment = 0.5, "无评分函数"

        weighted = raw * dim_cfg["weight"]
        details.append(ScoreDetail(
            dimension=dim_key,
            label=dim_cfg["label"],
            score=raw,
            weight=dim_cfg["weight"],
            weighted=weighted,
            comment=comment,
        ))
        total += weighted

    return min(total, 1.0), details


def score_round(questions: list, model_answers: list[dict],
                round_id: int, system_prompt: str = "",
                timestamp: str = "") -> RoundResult:
    """
    对一轮测试进行完整评分
    questions: list[TestQuestion]
    model_answers: list[dict] 每个含 {"content": str, "tokens_in": int, "tokens_out": int, "elapsed_ms": int}
    """
    results = []
    failures = []
    category_scores = {}
    difficulty_scores = {}
    domain_scores = {}

    for q, ans in zip(questions, model_answers):
        model_content = ans.get("content", "")
        total, details = score_answer(model_content, q.golden_answer, q.category)
        passed = total >= PASS_THRESHOLD

        qr = QuestionResult(
            question_id=q.id,
            category=q.category,
            difficulty=q.difficulty,
            domain=q.domain,
            question=q.question,
            golden_answer=q.golden_answer,
            model_answer=model_content,
            total_score=total,
            passed=passed,
            details=details,
            tokens_in=ans.get("tokens_in", 0),
            tokens_out=ans.get("tokens_out", 0),
            elapsed_ms=ans.get("elapsed_ms", 0),
        )
        results.append(qr)
        if not passed:
            failures.append(qr)

        # 累计分类分数
        for attr, storage in [(q.category, category_scores),
                               (q.difficulty, difficulty_scores),
                               (q.domain, domain_scores)]:
            if attr not in storage:
                storage[attr] = []
            storage[attr].append(total)

    # 计算平均值
    for storage in [category_scores, difficulty_scores, domain_scores]:
        for k in storage:
            storage[k] = round(sum(storage[k]) / len(storage[k]), 4)

    scores = [r.total_score for r in results]
    rr = RoundResult(
        round_id=round_id,
        total_questions=len(questions),
        avg_score=round(sum(scores) / len(scores), 4) if scores else 0,
        min_score=round(min(scores), 4) if scores else 0,
        max_score=round(max(scores), 4) if scores else 0,
        pass_rate=round(sum(1 for r in results if r.passed) / len(results), 4) if results else 0,
        category_scores=category_scores,
        difficulty_scores=difficulty_scores,
        domain_scores=domain_scores,
        questions=results,
        failures=failures,
        system_prompt_used=system_prompt,
        timestamp=timestamp,
    )
    return rr