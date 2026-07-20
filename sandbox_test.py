#!/usr/bin/env python3
"""沙箱模拟：完整多轮端到端测试，不依赖外部服务"""

import sys, os, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 重置全局状态 ──
import mock_client
mock_client._cache = None
import iteration_engine
iteration_engine._evolver = None
import ollama_client
ollama_client._client = None

# ── 打桩：Mock Ollama 客户端 ──
from ollama_client import OllamaClient

class FakeOllamaClient(OllamaClient):
    def health_check(self):
        return {"ok": True, "status": 200}

    def chat(self, messages, system=None, temperature=0.3, max_tokens=2048, think=False):
        q = messages[0].get("content", "") if messages else ""
        return {
            "ok": True,
            "content": self._fake_answer(q),
            "tokens_in": len(q) // 4,
            "tokens_out": 50,
            "elapsed_ms": 200,
        }

    def _fake_answer(self, q):
        ql = q.lower()
        if "t01" in q and "t02" in q:
            return "t01 供应商主数据, t02 物料货品主数据, t03 BOM物料清单"
        elif "join" in ql or "关联" in q:
            return "ERP: 采购到货记录中批次号=BRM001。MES: 质检批次记录中批次号=BRM001，检验结论=合格。"
        elif "聚合" in q or "统计" in q or "分组" in q:
            return "| 分组 | 计数 | 总和 | 平均值 |\n|---|---|---|---|\n| A | 3 | 150.00 | 50.00 |"
        elif "异常" in q:
            return "未找到异常记录"
        elif "不合格" in q or "质检" in q:
            return "批次号BRM001不合格，原因未知"
        elif "推理" in q or "分析" in q:
            return "第一步：查工单数据。第二步：找关联采购订单。结论：需要更多数据才能完成分析。"
        else:
            return "查询结果：t01 供应商主数据包含 SUP0001 等记录。"

# 注入假客户端
ollama_client._client = FakeOllamaClient()

# ── 打桩：Mock 数据源 ──
from mock_client import MockDataHub, MockDataSource

class FakeDataSource(MockDataSource):
    def health(self):
        return {"status": "ok", "tables": len(self.table_ids)}
    def list_tables(self):
        return [{"id": tid, "name": f"Table_{tid}"} for tid in self.table_ids]
    def get_schema(self, tid):
        return {"columns": [{"name": c} for c in ["col_a", "col_b", "col_c", "col_d", "col_e"]]}
    def get_data(self, tid, limit=100, offset=0):
        rows = []
        for i in range(min(limit, 15)):
            rows.append({
                "col_a": f"VAL_A_{tid}_{i}",
                "col_b": f"VAL_B_{i}",
                "col_c": "123",
                "col_d": "SUP0001",
                "col_e": "合格",
            })
        return {
            "id": tid, "name": f"Table_{tid}",
            "columns": ["col_a", "col_b", "col_c", "col_d", "col_e"],
            "total": 30, "rows": rows,
        }

class FakeHub(MockDataHub):
    def __init__(self):
        erp_tables = ["t01", "t02", "t03", "t04", "t05", "t06", "t08", "t09"]
        mes_tables = ["t07", "t10", "t11", "t12"]
        self.erp = FakeDataSource({"name": "ERP", "base_url": "http://fake", "token": "x", "tables": erp_tables})
        self.mes = FakeDataSource({"name": "MES", "base_url": "http://fake", "token": "x", "tables": mes_tables})
        self.sources = {"ERP": self.erp, "MES": self.mes}
    def health_all(self):
        return {n: s.health() for n, s in self.sources.items()}

mock_client._cache = FakeHub()

# ── 配置 ──
import config
config.QUESTIONS_PER_ROUND = 8
config.FAILURE_CLUSTER_MIN = 2
config.PROMPT_EVOLUTION_ENABLED = True

from test_generator import generate_test_suite, save_test_suite
from scorer import score_round
from iteration_engine import analyze_and_evolve, get_current_prompt, get_evolver
from reporter import write_all_reports

print("=== Sandbox: Multi-round simulation ===")
print()

for round_id in range(1, 4):
    print(f"--- Round {round_id} ---")

    # 生成题目
    qs = generate_test_suite()
    print(f"  Generated {len(qs)} questions")
    cats = {}
    for q in qs:
        cats[q.category] = cats.get(q.category, 0) + 1
    print(f"  Categories: {cats}")

    # 调模型
    client = ollama_client._client
    sp = get_current_prompt()
    answers = []
    for q in qs:
        r = client.chat([{"role": "user", "content": q.question}], system=sp)
        answers.append({
            "content": r["content"],
            "tokens_in": r.get("tokens_in", 0),
            "tokens_out": r.get("tokens_out", 0),
            "elapsed_ms": r.get("elapsed_ms", 0),
        })

    # 评分
    rr = score_round(qs, answers, round_id=round_id, system_prompt=sp, timestamp="2026-07-20")
    print(f"  Score: avg={rr.avg_score:.2%}, pass_rate={rr.pass_rate:.1%}, failures={len(rr.failures)}")

    # 迭代
    ir = analyze_and_evolve(rr)
    print(f"  Clusters: {len(ir.clusters)}, prompt_changed={ir.prompt_changed}, weak_areas={ir.weak_areas}")

    # 写报告
    tp, ip = write_all_reports(rr, ir)
    print(f"  Reports: {tp.name}, {ip.name}")
    print()

# ── 验证输出 ──
print("=== Verification ===")
reports_dir = config.REPORTS_DIR
report_files = sorted(reports_dir.glob("iteration_*_test_report.md"))
print(f"Test reports: {len(report_files)} files")
for f in report_files:
    print(f"  {f.name} ({f.stat().st_size} bytes)")

iter_files = sorted(reports_dir.glob("iteration_*_iteration_report.md"))
print(f"Iteration reports: {len(iter_files)} files")

summary_path = config.SUMMARY_JSON_PATH
if summary_path.exists():
    with open(summary_path, encoding="utf-8") as f:
        data = json.load(f)
    print(f"summary.json: {len(data['rounds'])} rounds")
    for r in data["rounds"]:
        print(f"  Round {r['round']}: avg={r['avg_score']:.2%}, pass_rate={r['pass_rate']:.1%}, prompt_v{r['prompt_version']}")

    trend = data.get("trend", {})
    if trend:
        print(f"  Trend: {trend.get('direction')} (delta={trend.get('score_delta', 0):+.2%})")

# Prompt 版本历史
prompt_ver = config.PROMPTS_DIR / "prompt_versions.json"
if prompt_ver.exists():
    with open(prompt_ver, encoding="utf-8") as f:
        vers = json.load(f)
    print(f"Prompt versions: {len(vers)}")
    for v in vers:
        print(f"  v{v['version']}: round={v['from_round']}, reason={v['reason'][:80]}")

print()
print("SANDBOX SIMULATION PASSED")