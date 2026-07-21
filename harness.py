#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock Data Harness — 主运行器 (harness.py)

加载测试用例 → 逐个运行 → 评估 → 生成报告。

用法:
  python harness.py                        # 运行全部测试
  python harness.py --difficulty L1-L3     # 只跑 L1-L3
  python harness.py --case L4-01           # 只跑单题
  python harness.py --verbose              # 打印完整 tool 调用链
  python harness.py --dry-run              # 不调 LLM，只验证用例
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any

from tools import TOOL_DEFINITIONS, TOOL_DISPATCH, clear_cache, get_cache_stats
from llm_client import LLMClient, LLMError, check_ollama_health, check_model_available
from test_cases import build_test_cases, get_case_by_id
from prompts import build_system_prompt
from evaluator import (
    evaluate_answer,
    evaluate_tool_usage,
    generate_report,
    generate_json_report,
)


def run_single_case(
    client: LLMClient,
    test_case: dict,
    system_prompt: str,
    verbose: bool = False,
) -> dict[str, Any]:
    """运行单个测试用例"""
    case_id = test_case["id"]
    question = test_case["question"]
    expected_tools = test_case.get("expected_tools", [])

    if verbose:
        print(f"\n{'='*60}")
        print(f"[{case_id}] {question}")
        print(f"  难度: {test_case['difficulty']}, 陷阱: {test_case.get('traps', [])}")
        print(f"{'='*60}")

    # 初始化 messages
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    # 清除缓存
    clear_cache()

    # 执行 tool 循环
    start_time = time.time()
    try:
        result = client.chat_with_tools(messages, TOOL_DISPATCH)
    except LLMError as e:
        elapsed = time.time() - start_time
        return {
            "case_id": case_id,
            "question": question,
            "difficulty": test_case["difficulty"],
            "traps": test_case.get("traps", []),
            "final_answer": "",
            "tool_calls": [],
            "rounds": 0,
            "errors": [str(e)],
            "elapsed": elapsed,
            "grade": "FAIL",
            "score": 0.0,
            "detail": f"LLM 调用失败: {e}",
            "tool_accuracy": 0.0,
            "tool_efficiency": 0.0,
        }
    elapsed = time.time() - start_time

    final_answer = result.get("final_answer", "")
    tool_calls = result.get("tool_calls", [])
    rounds = result.get("rounds", 0)
    errors = result.get("errors", [])

    if verbose:
        print(f"\n  轮次: {rounds}, 耗时: {elapsed:.1f}s")
        for i, tc in enumerate(tool_calls):
            print(f"  Tool {i+1}: {tc['tool']}({tc.get('arguments', {})})")
            r = tc.get("result", {})
            if "error" in r:
                print(f"    [WARN] 错误: {r.get('error')}")
            else:
                print(f"    ✓ 返回: {r.get('_returned', '?')} 行")
        print(f"\n  最终答案: {final_answer[:200]}...")

    # 评估答案
    eval_result = evaluate_answer(final_answer, test_case)

    # 评估 tool 使用
    actual_tools = [tc["tool"] for tc in tool_calls]
    tool_eval = evaluate_tool_usage(actual_tools, expected_tools)

    return {
        "case_id": case_id,
        "question": question,
        "difficulty": test_case["difficulty"],
        "traps": test_case.get("traps", []),
        "final_answer": final_answer[:500],
        "tool_calls": [
            {"tool": tc["tool"], "arguments": tc.get("arguments", {})}
            for tc in tool_calls
        ],
        "rounds": rounds,
        "errors": errors,
        "elapsed": round(elapsed, 1),
        "grade": eval_result["grade"],
        "score": eval_result["score"],
        "detail": eval_result.get("detail", ""),
        "tool_accuracy": tool_eval.get("tool_accuracy", 0),
        "tool_efficiency": tool_eval.get("tool_efficiency", 0),
    }


def parse_difficulty_range(arg: str) -> list[str]:
    """解析难度范围，如 'L1-L3' → ['L1','L2','L3']"""
    all_levels = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "ADV", "INT"]
    if "-" in arg:
        parts = arg.split("-")
        start = parts[0].strip()
        end = parts[1].strip()
        try:
            si = all_levels.index(start)
            ei = all_levels.index(end)
            return all_levels[si : ei + 1]
        except ValueError:
            return [arg]
    return [arg]


def main():
    parser = argparse.ArgumentParser(description="Mock Data Harness — Qwen 9B 数据整合测试")
    parser.add_argument("--difficulty", type=str, default=None,
                        help="难度范围，如 'L1-L3' 或 'L4'")
    parser.add_argument("--case", type=str, default=None,
                        help="只运行指定用例 ID，如 'L4-01'")
    parser.add_argument("--verbose", action="store_true",
                        help="打印完整 tool 调用链")
    parser.add_argument("--dry-run", action="store_true",
                        help="只验证用例定义，不调 LLM")
    parser.add_argument("--no-cot", action="store_true",
                        help="不使用 Chain-of-Thought 提示")
    parser.add_argument("--output", type=str, default="results",
                        help="输出目录（默认 results/）")
    args = parser.parse_args()

    # ── 加载测试用例 ──
    if args.case:
        case = get_case_by_id(args.case)
        if not case:
            print(f"错误：未找到用例 {args.case}")
            sys.exit(1)
        test_cases = [case]
    else:
        test_cases = build_test_cases()
        if args.difficulty:
            levels = set()
            for part in args.difficulty.split(","):
                levels.update(parse_difficulty_range(part.strip()))
            test_cases = [c for c in test_cases if c["difficulty"] in levels]

    print(f"加载 {len(test_cases)} 个测试用例")

    if args.dry_run:
        print("\n── Dry Run ──")
        for tc in test_cases:
            print(f"  [{tc['id']}] {tc['difficulty']:4s} | {tc['question'][:80]}")
            print(f"           陷阱: {tc.get('traps', [])}")
            print(f"           期望工具: {tc.get('expected_tools', [])}")
        print(f"\n[OK] 全部 {len(test_cases)} 个用例定义验证通过")
        return

    # ── 检查 Ollama ──
    health = check_ollama_health()
    if not health["ok"]:
        print(f"\n[ERROR] Ollama 服务不可用: {health.get('error', 'unknown')}")
        print("请先启动 Ollama:\n  bash start_qwen.sh")
        sys.exit(1)
    print("[OK] Ollama 服务可用")

    model_status = check_model_available()
    if not model_status["ok"]:
        print(f"\n[ERROR] 模型不可用: {model_status.get('error', 'unknown')}")
        print("请先下载模型:\n  ollama pull qwen3.5:9b")
        sys.exit(1)
    print(f"[OK] 模型 {model_status.get('model', 'qwen3.5:9b')} 可用")

    # ── 初始化 LLM 客户端 ──
    client = LLMClient()
    client.set_tools(TOOL_DEFINITIONS)
    system_prompt = build_system_prompt(with_cot=not args.no_cot)

    # ── 运行测试 ──
    results = []
    start_time = time.time()

    for i, tc in enumerate(test_cases):
        print(f"\n[{i+1}/{len(test_cases)}] {tc['id']} — {tc['question'][:70]}...", end=" ", flush=True)
        result = run_single_case(client, tc, system_prompt, verbose=args.verbose)
        results.append(result)
        print(f"{result['grade']} ({result['score']:.2f})")

    total_elapsed = time.time() - start_time

    # ── 生成报告 ──
    report_text = generate_report(results)
    report_json = generate_json_report(results)

    # 添加耗时信息
    report_text += f"\n总耗时: {total_elapsed:.1f}s\n"

    # 确保输出目录存在
    os.makedirs(args.output, exist_ok=True)

    # 写入报告
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    txt_path = os.path.join(args.output, f"report_{timestamp}.txt")
    json_path = os.path.join(args.output, f"report_{timestamp}.json")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_json, f, ensure_ascii=False, indent=2)

    # 打印摘要
    print(report_text)

    print(f"\n报告已保存:")
    print(f"  {txt_path}")
    print(f"  {json_path}")


if __name__ == "__main__":
    main()