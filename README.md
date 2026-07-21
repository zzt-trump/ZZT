# 同学A 最终产出 — 化工产线时序分析项目

> 日期：2026-07-21
> 基于 T35111 装置数据（52 个位号，7 天约 2000 万点），构建时序分析 Agent Benchmark 和 Stateful Skill 原型。

---

## 目录结构

```
同学A_最终产出/
├── README.md                          ← 本文件
├── 01_Validator/                      ← A1: 合同静态检查工具
│   └── contract_validator.py
├── 02_Grounding样例/                   ← A2: 自然语言→位号绑定样例
│   └── grounding_golden_v0.jsonl
├── 03_题库/                            ← A3: 扩展题库（202题）
│   └── analysis_formal.jsonl
├── 04_Contracts/                      ← A4 + P3: 5份 Skill Contract
│   ├── stationarity.json              (平稳性分析)
│   ├── correlation.json               (相关性分析)
│   ├── control_response.json          (控制响应分析)
│   ├── outlier_detect.json            (异常检测)
│   └── financial_cost_analysis.json   (财务成本分析 · 新增)
└── 05_生成器脚本/                      ← 题库生成器（含 --template-only 模式）
    └── generate_analysis_cases.py
```

---

## 各任务详情

### A1: Validator（合同静态检查工具）

**文件**: `01_Validator/contract_validator.py`

对全部 Skill Contract 做自动化检查，共 **12 项**：

| 编号 | 检查项 | 说明 |
|------|--------|------|
| ① | requirement ID 唯一性 | 无重复 ID |
| ② | capability 引用存在 | requires 中的 ID 在 requirements 或 evidence_types 中存在 |
| ③ | produces 引用存在 | produces 中的 evidence 在 evidence_types 中存在（__final__ 除外） |
| ④ | completion 引用存在 | completion.requires 中的 evidence 在 evidence_types 中存在 |
| ⑤ | binding 引用存在 | 非 noop 的 binding 在 bindings 中存在 |
| ⑥ | 版本号存在 | version 字段非空 |
| ⑦ | 不可达检测 | BFS 检查所有 capability 是否可触发 |
| ⑧ | 孤立节点检测 | 所有非 input requirement 至少被一个 capability 引用 |
| ⑨ | 循环依赖检测 | DFS 检测 capability 依赖环 |
| ⑩ | 路径可达 __final__ | 反向 BFS 检查所有 cap 能否到达完成 |
| ⑪ | Schema 版本兼容 | version 格式、skill_id、domain 字段 |
| ⑫ | 高风险权限声明 | 高风险 action 必须有 permissions 声明 |

**运行方式**:
```bash
cd supcon-production-benchmark
python -m production_bench.stateful.validators.contract_validator
```

**验证结果**: `All contracts valid (5 contracts, 12 checks each, 0 warnings)`

---

### A2: Grounding 样例

**文件**: `02_Grounding样例/grounding_golden_v0.jsonl`

共 **32 条**样例，覆盖 5 个合同和 5 种绑定类型：

| 类型 | 条数 | 示例 |
|------|------|------|
| exact_match（唯一匹配） | 11 | "FI35111 过去一小时流量稳不稳" |
| multi_candidate（多候选） | 6 | "1#塔流量" → FI35111 / FI35114 / FI35116 |
| alias（别名） | 4 | "塔顶温度" → TI35111A1 |
| near_miss（近似不匹配） | 5 | "进料压力" → 无此位号 |
| unknown（未知概念） | 4 | "那个什么设备" → 无法绑定 |

新增财务相关样例（2条）：
- "A产品上个月的材料成本是多少" → financial_cost_analysis
- "B产品的生产成本构成" → financial_cost_analysis

---

### A3: 扩展题库

**文件**: `03_题库/analysis_formal.jsonl`

| 指标 | 扩展前 | 扩展后 |
|------|--------|--------|
| 总题数 | **86** | **202** |
| 位号覆盖 | 18 个 | 39 个 |
| 时间窗 | 1h 为主 | 1h / 4h / 8h / 24h |
| 任务族 | 5 个 | 5 个 |

**各任务族分布**:

| 任务族 | 题数 | 说明 |
|--------|------|------|
| analysis_stationarity | 53 | 平稳性检验 |
| analysis_correlation | 33 | 双变量相关性分析 |
| analysis_control_response | 21 | 控制回路 MV-PV 响应分析 |
| analysis_rolling_stats | 45 | 滚动统计量计算 |
| analysis_outlier_detect | 30 | 异常值检测 |
| 边缘场景（edge） | 20 | 24h窗口、空历史位号、时间范围外 |

**验证结果**: `Stateful OK: 202/202`

**数据来源**: `C:\Users\24198\OneDrive\Desktop\暑期实验室\暑科项目_数据包`

---

### A4: Contract 完善

**文件**: `04_Contracts/*.json`

4 份化工合同全部补充了以下字段：

| 字段 | 作用 |
|------|------|
| description | 每个 requirement / capability / evidence_type 的详细描述 |
| phases | 流程阶段划分（grounding → execution → reporting） |
| failure_paths | 失败恢复路径（数据不足→报告；位号不存在→回退确认） |

---

### P3: 财务分析主域准备

**文件**: `04_Contracts/financial_cost_analysis.json`

合同结构：

```
requirements:   product_id, time_period, cost_category
capabilities:   confirm_product → load_cost_data → compute_cost_analysis → report_result
bindings:       analysis.financial.data_loader, analysis.financial.cost_analysis
phases:         grounding → execution → reporting
failure_paths:  data_not_found, product_not_found, insufficient_data
```

---

## 验证总览

| 检查项 | 命令 | 结果 |
|--------|------|------|
| Validator | `python -m production_bench.stateful.validators.contract_validator` | 5 contracts, 0 errors, 0 warnings |
| compare.py | `python -m production_bench.stateful.compare` | 202/202 Stateful OK |
| 题库行数 | `Get-Content benchmark/cases/analysis_formal.jsonl \| Measure-Object -Line` | 202 lines |

---

## 后续待办

拿到原始 CSV 数据后，如需重新生成 gold result：

```bash
cd supcon-production-benchmark
python -m production_bench.generate_analysis_cases --data-dir "数据路径"
```

如需生成模板（无数据时）：

```bash
python -m production_bench.generate_analysis_cases --template-only
```