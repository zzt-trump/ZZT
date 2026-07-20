# Model Harness — 24/7 本地模型自我迭代系统

> 持续出题 → 测试模型 → 评分 → 分析失败 → 自动优化 Prompt → 下一轮

## 快速开始

```bash
# 1. 确保 Ollama 已启动（Qwen3.5-9B 已加载）
bash start_qwen.sh

# 2. 验证环境
bash test_harness.sh

# 3. 启动 24/7 循环（默认每 30 分钟一轮）
bash start_harness.sh

# 4. 停止
bash stop_harness.sh
```

## 目录结构

```
model_harness/
├── config.py              # 全局配置（模型、API、评分权重等）
├── ollama_client.py       # Ollama 原生 API 客户端（think:false）
├── mock_client.py         # ERP/MES 双源 Mock 数据访问
├── test_generator.py      # 自动生成 6 类测试题 + 标准答案
├── scorer.py              # 4 维度评分引擎
├── iteration_engine.py    # 失败模式聚类 + Prompt 自动进化
├── reporter.py            # Markdown 报告 + 趋势汇总
├── runner.py              # 主入口（调度循环）
├── start_harness.sh       # 启动脚本
├── stop_harness.sh        # 停止脚本
├── test_harness.sh        # 验证脚本
├── reports/               # 每轮报告（*.md）+ summary.json
├── prompts/               # Prompt 版本历史
├── test_suite/            # 测试套件存档
└── logs/                  # 运行日志
```

## 运行参数

```bash
python3 runner.py --once              # 只跑一轮
python3 runner.py --rounds 10         # 跑 10 轮
python3 runner.py --interval 600      # 每 10 分钟一轮
```

## 测试题类别

| 类别 | 占比 | 说明 |
|------|------|------|
| single_table_query | 25% | 单表精确查询 |
| cross_source_join | 20% | 跨 ERP/MES 关联查询 |
| aggregation | 20% | 分组聚合统计 |
| anomaly_detection | 15% | 异常检测（计量参数） |
| quality_trace | 10% | 质检追溯 |
| reasoning | 10% | 综合推理分析 |

## 评分维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 准确性 | 40% | 关键编码/数值是否匹配 |
| 完整性 | 25% | 是否覆盖所有子任务 |
| 格式规范 | 15% | 是否使用表格等结构化格式 |
| 推理逻辑 | 20% | 是否包含推理步骤 |

## 自我迭代机制

1. 每轮评分后，聚类失败案例（按类别 + 共性模式）
2. 当某类失败 ≥ 3 题时，自动生成 Prompt 改进建议
3. 改进建议追加到 System Prompt 末尾
4. 下轮自动使用新 Prompt，形成闭环
5. 每 5 轮生成趋势报告，对比 score 变化