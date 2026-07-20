#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型质量 Harness 主入口 — 24/7 自我迭代循环

用法:
  python3 runner.py                    # 无限循环（默认间隔 30 分钟）
  python3 runner.py --rounds 10        # 执行 10 轮后停止
  python3 runner.py --once             # 只跑一轮
  python3 runner.py --interval 600     # 每 10 分钟一轮
"""

import sys
import time
import signal
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import (
    LOGS_DIR, MAX_ITERATIONS, ITERATION_INTERVAL_SEC,
    ROOT,
)
from ollama_client import get_client, OllamaClient
from mock_client import get_hub, MockDataHub
from test_generator import generate_test_suite, save_test_suite
from scorer import score_round
from iteration_engine import analyze_and_evolve, get_current_prompt
from reporter import write_all_reports

TZ = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def setup_logging():
    """配置日志"""
    log_path = LOGS_DIR / f"harness_{datetime.now(TZ).strftime('%Y%m%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("harness")


logger = None  # 将在 main 中初始化


# ═══════════════════════════════════════════════════════════════
#  单轮执行
# ═══════════════════════════════════════════════════════════════

def run_single_round(round_id: int, client: OllamaClient, hub: MockDataHub) -> bool:
    """
    执行一轮完整测试，返回 True 表示成功
    流程：健康检查 → 生成题目 → 调用模型 → 评分 → 分析迭代 → 输出报告
    """
    global logger

    logger.info(f"{'='*60}")
    logger.info(f"第 {round_id} 轮开始 — {_now()}")
    logger.info(f"{'='*60}")

    # ── 1. 健康检查 ──────────────────────────────────
    ollama_health = client.health_check()
    if not ollama_health.get("ok"):
        logger.error(f"Ollama 不可用: {ollama_health}")
        return False

    mock_health = hub.health_all()
    for name, h in mock_health.items():
        if h.get("status") != "ok":
            logger.warning(f"Mock {name} 异常: {h}")

    logger.info("✅ 健康检查通过")

    # ── 2. 生成测试套件 ───────────────────────────────
    logger.info("生成测试题...")
    questions = generate_test_suite()
    logger.info(f"生成了 {len(questions)} 题")
    save_test_suite(questions, f"suite_round_{round_id:03d}.json")

    # ── 3. 获取当前 system prompt ─────────────────────
    system_prompt = get_current_prompt()
    logger.info(f"System prompt 版本: {len(system_prompt)} 字符")

    # ── 4. 逐题调用模型 ───────────────────────────────
    model_answers = []
    for i, q in enumerate(questions):
        logger.info(f"  [{i+1}/{len(questions)}] {q.id} [{q.category}] [{q.difficulty}]")

        result = client.chat(
            messages=[{"role": "user", "content": q.question}],
            system=system_prompt,
            temperature=0.3,
            think=False,
        )

        if not result.get("ok"):
            logger.error(f"  模型调用失败: {result.get('error')}")
            model_answers.append({
                "content": f"[ERROR] {result.get('error')}",
                "tokens_in": 0,
                "tokens_out": 0,
                "elapsed_ms": 0,
            })
        else:
            model_answers.append({
                "content": result["content"],
                "tokens_in": result.get("tokens_in", 0),
                "tokens_out": result.get("tokens_out", 0),
                "elapsed_ms": result.get("elapsed_ms", 0),
            })
            logger.info(f"    {result.get('tokens_in', 0)}+{result.get('tokens_out', 0)} tokens, {result.get('elapsed_ms', 0)}ms")

    # ── 5. 评分 ───────────────────────────────────────
    logger.info("评分中...")
    round_result = score_round(
        questions=questions,
        model_answers=model_answers,
        round_id=round_id,
        system_prompt=system_prompt,
        timestamp=_now(),
    )
    logger.info(
        f"评分完成: 平均 {round_result.avg_score:.2%}, "
        f"通过率 {round_result.pass_rate:.1%}, "
        f"失败 {len(round_result.failures)}/{round_result.total_questions}"
    )

    # ── 6. 分析迭代 ──────────────────────────────────
    logger.info("分析失败模式...")
    iter_result = analyze_and_evolve(round_result)
    if iter_result.prompt_changed:
        logger.info(f"✅ Prompt 已升级到 v{iter_result.new_prompt_version}")
    if iter_result.weak_areas:
        logger.info(f"薄弱领域: {iter_result.weak_areas}")

    # ── 7. 输出报告 ───────────────────────────────────
    test_path, iter_path = write_all_reports(round_result, iter_result)
    logger.info(f"报告已保存: {test_path}, {iter_path}")

    logger.info(f"第 {round_id} 轮完成 — {_now()}")
    return True


# ═══════════════════════════════════════════════════════════════
#  主循环
# ═══════════════════════════════════════════════════════════════

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info(f"收到信号 {signum}，准备优雅退出...")
    _shutdown = True


def main():
    global logger
    parser = argparse.ArgumentParser(description="模型质量 Harness — 24/7 自我迭代")
    parser.add_argument("--rounds", type=int, default=MAX_ITERATIONS,
                        help=f"执行轮数（0=无限，默认 {MAX_ITERATIONS}）")
    parser.add_argument("--once", action="store_true", help="只跑一轮")
    parser.add_argument("--interval", type=int, default=ITERATION_INTERVAL_SEC,
                        help=f"轮次间隔秒数（默认 {ITERATION_INTERVAL_SEC}）")
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger("harness")

    # 优雅退出
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("=" * 60)
    logger.info("模型质量 Harness 启动")
    logger.info(f"模型: {get_client().model}")
    logger.info(f"间隔: {args.interval}s")
    logger.info(f"轮次: {'无限' if args.rounds == 0 else args.rounds}")
    logger.info("=" * 60)

    client = get_client()
    hub = get_hub()

    round_id = 0
    max_rounds = 1 if args.once else args.rounds

    while not _shutdown:
        round_id += 1

        try:
            ok = run_single_round(round_id, client, hub)
        except KeyboardInterrupt:
            logger.info("用户中断")
            break
        except Exception as e:
            logger.exception(f"第 {round_id} 轮异常: {e}")
            ok = False

        if not ok:
            logger.warning("本轮失败，等待后继续...")

        # 检查是否达到最大轮次
        if max_rounds > 0 and round_id >= max_rounds:
            logger.info(f"已完成 {round_id} 轮，退出")
            break

        # 等待间隔
        if args.once:
            break

        logger.info(f"等待 {args.interval}s 后开始下一轮...")
        for _ in range(args.interval):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("Harness 已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())