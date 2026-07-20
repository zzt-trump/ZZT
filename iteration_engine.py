#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自我迭代引擎 — 分析失败模式，自动优化 System Prompt 和 Few-shot 示例"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

from config import (
    PROMPTS_DIR, BASE_SYSTEM_PROMPT,
    FAILURE_CLUSTER_MIN, MAX_FEWSHOT_EXAMPLES, PROMPT_EVOLUTION_ENABLED,
)
from scorer import RoundResult, QuestionResult

logger = logging.getLogger(__name__)


@dataclass
class FailureCluster:
    """一组失败案例的聚类"""
    category: str
    count: int
    avg_score: float
    common_pattern: str       # 共性描述
    suggested_fix: str        # 建议的 prompt 改进
    examples: list = field(default_factory=list)  # 失败案例 ID 列表


@dataclass
class PromptVersion:
    """Prompt 版本记录"""
    version: int
    system_prompt: str
    fewshot_examples: list = field(default_factory=list)
    reason: str = ""          # 为什么变更
    from_round: int = 0


@dataclass
class IterationResult:
    """单次迭代分析结果"""
    round_id: int
    clusters: list = field(default_factory=list)     # list[FailureCluster]
    prompt_changed: bool = False
    new_prompt_version: int = 0
    change_reason: str = ""
    weak_areas: list = field(default_factory=list)   # 薄弱领域
    improvement_notes: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
#  失败模式聚类
# ═══════════════════════════════════════════════════════════════

def _cluster_failures(failures: list[QuestionResult]) -> list[FailureCluster]:
    """将失败案例按类别+模式聚类"""
    by_category = {}
    for f in failures:
        cat = f.category
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(f)

    clusters = []
    for cat, items in by_category.items():
        if len(items) < FAILURE_CLUSTER_MIN:
            continue

        avg = sum(i.total_score for i in items) / len(items)

        # 分析共性模式
        patterns = _detect_patterns(items)
        fix = _suggest_fix(cat, patterns)

        clusters.append(FailureCluster(
            category=cat,
            count=len(items),
            avg_score=round(avg, 3),
            common_pattern=patterns,
            suggested_fix=fix,
            examples=[i.question_id for i in items[:3]],
        ))

    return sorted(clusters, key=lambda c: c.count, reverse=True)


def _detect_patterns(failures: list[QuestionResult]) -> str:
    """检测失败案例的共性模式"""
    # 检查是否有共同的低分维度
    dim_issues = {}
    for f in failures:
        for d in f.details:
            if d.score < 0.5:
                dim_issues.setdefault(d.dimension, 0)
                dim_issues[d.dimension] += 1

    patterns = []
    for dim, count in sorted(dim_issues.items(), key=lambda x: -x[1]):
        if count >= len(failures) * 0.5:
            patterns.append(f"{dim} 维度普遍偏低({count}/{len(failures)})")

    # 检查是否答案过短（可能是模型没理解问题）
    short_answers = sum(1 for f in failures if len(f.model_answer) < 100)
    if short_answers >= len(failures) * 0.5:
        patterns.append(f"回答过短({short_answers}/{len(failures)})")

    # 检查跨源 JOIN 是否混淆了数据源
    if any(f.category == "cross_source_join" for f in failures):
        patterns.append("跨源 JOIN 可能混淆了 ERP 和 MES 的数据")

    return "; ".join(patterns) if patterns else "模式不明确"


def _suggest_fix(category: str, pattern: str) -> str:
    """根据失败模式生成建议修复"""
    fixes = []

    if "accuracy" in pattern.lower():
        fixes.append("在 system prompt 中强调：编码必须保留前导零，数值精确匹配，使用 /nothink 关闭思考模式")

    if "completeness" in pattern.lower() or "过短" in pattern:
        fixes.append("在 system prompt 中增加：必须列出所有匹配行，使用 Markdown 表格完整展示")

    if "reasoning" in pattern.lower():
        fixes.append("在 system prompt 中增加推理步骤模板：先分析问题 → 查数据 → 关联 → 得出结论")

    if "cross_source" in category or "跨源" in pattern:
        fixes.append("添加跨源查询的 few-shot 示例，展示如何从 ERP 和 MES 分别取数后关联")

    if "aggregation" in category:
        fixes.append("添加聚合分析的 few-shot 示例，展示分组统计的标准输出格式")

    return "; ".join(fixes) if fixes else "增加更多针对性 few-shot 示例"


# ═══════════════════════════════════════════════════════════════
#  Prompt 进化
# ═══════════════════════════════════════════════════════════════

class PromptEvolver:
    """管理系统 prompt 的版本演进"""

    def __init__(self):
        self.versions: list[PromptVersion] = []
        self._load_history()
        if not self.versions:
            # 初始版本
            self.versions.append(PromptVersion(
                version=1,
                system_prompt=BASE_SYSTEM_PROMPT,
                fewshot_examples=[],
                reason="初始版本",
                from_round=0,
            ))

    def _load_history(self):
        path = PROMPTS_DIR / "prompt_versions.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.versions = [PromptVersion(**d) for d in data]
            except Exception as e:
                logger.warning(f"加载 prompt 历史失败: {e}")

    def _save_history(self):
        path = PROMPTS_DIR / "prompt_versions.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(v) for v in self.versions], f, ensure_ascii=False, indent=2)

    @property
    def current(self) -> PromptVersion:
        return self.versions[-1]

    @property
    def current_prompt(self) -> str:
        return self.current.system_prompt

    def evolve(self, clusters: list[FailureCluster], round_id: int) -> Optional[PromptVersion]:
        """根据失败聚类生成新的 prompt 版本"""
        if not PROMPT_EVOLUTION_ENABLED or not clusters:
            return None

        new_prompt = self.current.system_prompt
        changes = []

        for cl in clusters[:3]:  # 最多处理 3 个聚类
            fix = cl.suggested_fix
            if fix and fix not in new_prompt:
                changes.append(f"- [{cl.category}] {fix}")

        if not changes:
            return None

        # 追加到 prompt 末尾
        addition = "\n\n## 最新迭代优化（基于失败案例）\n"
        addition += "\n".join(changes)
        new_prompt += addition

        new_ver = PromptVersion(
            version=self.current.version + 1,
            system_prompt=new_prompt,
            fewshot_examples=self.current.fewshot_examples,
            reason="; ".join(f"{cl.category}:{cl.common_pattern}" for cl in clusters[:3]),
            from_round=round_id,
        )
        self.versions.append(new_ver)
        self._save_history()
        return new_ver


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

_evolver: Optional[PromptEvolver] = None


def get_evolver() -> PromptEvolver:
    global _evolver
    if _evolver is None:
        _evolver = PromptEvolver()
    return _evolver


def analyze_and_evolve(round_result: RoundResult) -> IterationResult:
    """分析一轮测试结果，自动优化 prompt"""
    evolver = get_evolver()
    clusters = _cluster_failures(round_result.failures)

    # 识别薄弱领域
    weak = []
    for cat, score in sorted(round_result.category_scores.items(), key=lambda x: x[1]):
        if score < 0.6:
            weak.append(f"{cat}({score:.2f})")

    # 尝试进化 prompt
    new_ver = evolver.evolve(clusters, round_result.round_id)

    improvements = []
    if new_ver:
        improvements.append(f"Prompt 已从 v{new_ver.version - 1} 升级到 v{new_ver.version}")
        improvements.append(f"变更原因: {new_ver.reason}")
    else:
        improvements.append("本轮未触发 prompt 变更（失败案例不足或模式不明确）")

    return IterationResult(
        round_id=round_result.round_id,
        clusters=clusters,
        prompt_changed=new_ver is not None,
        new_prompt_version=evolver.current.version,
        change_reason=new_ver.reason if new_ver else "",
        weak_areas=weak,
        improvement_notes=improvements,
    )


def get_current_prompt() -> str:
    return get_evolver().current_prompt