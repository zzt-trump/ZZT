#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock Data Harness — 测试用例 (test_cases.py)

7 层难度 × ~7 题 + 5 对抗题 + 2 综合题 = 56 题。
每道题标注了暗含的陷阱类型。
"""

from typing import Any, Optional

# 陷阱类型常量
CROSS_SOURCE = "cross_source"       # 跨源查询
PAGINATION = "pagination"           # 需要翻页
NULL_HANDLING = "null_handling"     # 需处理 null 值
ONE_TO_MANY = "one_to_many"         # 一对多关系
STRING_TYPE = "string_type"         # 字段值为字符串，需类型转换
SYSTEM_BOUNDARY = "system_boundary" # 系统边界感知
COLUMN_AMBIGUITY = "column_ambiguity" # 多表同名列
AGGREGATION = "aggregation"         # 需要聚合计算
TIME_FILTER = "time_filter"         # 需要日期过滤
ADVERSARIAL = "adversarial"         # 对抗性测试


def build_test_cases() -> list[dict[str, Any]]:
    """返回全部测试用例"""
    cases: list[dict[str, Any]] = []

    # ═══════════════════════════════════════════════════════
    #  L1: 单源单表 — 基本 tool 调用
    # ═══════════════════════════════════════════════════════
    L1 = [
        {
            "id": "L1-01", "difficulty": "L1",
            "question": "ERP 系统中有多少个供应商？",
            "expected_tools": ["erp_query"],
            "expected_answer": "220",
            "answer_type": "exact",
            "traps": [],
        },
        {
            "id": "L1-02", "difficulty": "L1",
            "question": "MES 系统中有多少个生产工单？",
            "expected_tools": ["mes_query"],
            "expected_answer": "240",
            "answer_type": "exact",
            "traps": [SYSTEM_BOUNDARY],
        },
        {
            "id": "L1-03", "difficulty": "L1",
            "question": "t01 表（供应商主数据）有哪些列？",
            "expected_tools": ["erp_get_schema"],
            "expected_answer": "供应商编码,供应商名称,供应商简称,供应商类别,主供物料类别,付款条件,是否有效",
            "answer_type": "set",
            "traps": [],
        },
        {
            "id": "L1-04", "difficulty": "L1",
            "question": "采购订单表（t05）中，采购状态有哪些不同的值？",
            "expected_tools": ["erp_query"],
            "expected_answer": "执行中,已关闭,已完成,部分到货,新建",
            "answer_type": "set",
            "traps": [STRING_TYPE, PAGINATION],
        },
        {
            "id": "L1-05", "difficulty": "L1",
            "question": "t08 物料库存快照表共记录了多少条库存记录？",
            "expected_tools": ["erp_query"],
            "expected_answer": "260",
            "answer_type": "exact",
            "traps": [],
        },
        {
            "id": "L1-06", "difficulty": "L1",
            "question": "t12 计量参数记录表中，有多少条记录被标记为异常？",
            "expected_tools": ["mes_query"],
            "expected_answer": "35",
            "answer_type": "numeric_range",
            "traps": [STRING_TYPE, PAGINATION],
        },
        {
            "id": "L1-07", "difficulty": "L1",
            "question": "t07 生产工单表中，有哪些不同的工单状态？",
            "expected_tools": ["mes_query"],
            "expected_answer": "计划,已完工,生产中,已关闭,已下达",
            "answer_type": "set",
            "traps": [STRING_TYPE],
        },
    ]
    cases.extend(L1)

    # ═══════════════════════════════════════════════════════
    #  L2: 单源多表 — 同源 join
    # ═══════════════════════════════════════════════════════
    L2 = [
        {
            "id": "L2-01", "difficulty": "L2",
            "question": "列出供应商编码为 SUP0007 的供应商名称，以及它的所有采购订单号。",
            "expected_tools": ["erp_query"],
            "expected_answer": "苏州东山精密电子有限公司;PO202600115,PO202600115",  # 至少包含供应商名和订单号
            "answer_type": "exists",
            "traps": [STRING_TYPE],
        },
        {
            "id": "L2-02", "difficulty": "L2",
            "question": "ERP 系统中，采购订单 PO202600115 包含哪些物料？请列出物料编码和物料名称。",
            "expected_tools": ["erp_query"],
            "expected_answer": "RM00114;RM00076;SF00044",
            "answer_type": "set",
            "traps": [STRING_TYPE],
        },
        {
            "id": "L2-03", "difficulty": "L2",
            "question": "在 t04 销售订单中，哪个客户的订单数量最多？",
            "expected_tools": ["erp_list_tables", "erp_query"],
            "expected_answer": None,  # 需要实际查询确定
            "answer_type": "exists",
            "traps": [AGGREGATION, STRING_TYPE, PAGINATION],
        },
        {
            "id": "L2-04", "difficulty": "L2",
            "question": "工单 MO202600002 生产的是哪个货品？该工单关联的 BOM 中包含了哪些子项物料？",
            "expected_tools": ["mes_query", "erp_query"],
            "expected_answer": "FG00011;RM00069,RM00095",  # 物联网终端B型 + 子项
            "answer_type": "exists",
            "traps": [CROSS_SOURCE],
        },
        {
            "id": "L2-05", "difficulty": "L2",
            "question": "MES 系统中，车间 'SMT一车间' 有多少个工单？",
            "expected_tools": ["mes_query"],
            "expected_answer": None,  # 需实际查询
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION],
        },
        {
            "id": "L2-06", "difficulty": "L2",
            "question": "t06 到货记录中，检验状态为 '不合格' 的到货单有哪些？列出到货单号和批次号。",
            "expected_tools": ["erp_query"],
            "expected_answer": None,  # 需实际查询
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION],
        },
        {
            "id": "L2-07", "difficulty": "L2",
            "question": "t06 表中，入库仓库编码为 'WH01' 的到货记录有多少条？",
            "expected_tools": ["erp_query"],
            "expected_answer": None,  # 需实际查询
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION],
        },
    ]
    cases.extend(L2)

    # ═══════════════════════════════════════════════════════
    #  L3: 单源聚合 — 分页感知 + 字符串数值比较
    # ═══════════════════════════════════════════════════════
    L3 = [
        {
            "id": "L3-01", "difficulty": "L3",
            "question": "ERP 系统中，采购数量最多的前 5 个采购订单行是哪些？列出采购订单行ID和采购数量。",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION, AGGREGATION],
        },
        {
            "id": "L3-02", "difficulty": "L3",
            "question": "在 t05 采购订单中，采购状态为 '部分到货' 的订单占比是多少（百分比）？",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION, AGGREGATION],
        },
        {
            "id": "L3-03", "difficulty": "L3",
            "question": "t06 到货记录中，有多少个不同的供应商编码？",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION, AGGREGATION],
        },
        {
            "id": "L3-04", "difficulty": "L3",
            "question": "t11 质检记录中，合格率最低的 3 条记录是哪些？列出批次号和合格率。",
            "expected_tools": ["mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION, AGGREGATION],
        },
        {
            "id": "L3-05", "difficulty": "L3",
            "question": "t11 质检记录中，检验结论为 '不合格' 的批次有多少个？",
            "expected_tools": ["mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION],
        },
        {
            "id": "L3-06", "difficulty": "L3",
            "question": "t08 库存快照中，可用量为 0 的物料有哪些？列出物料编码。",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION, NULL_HANDLING],
        },
        {
            "id": "L3-07", "difficulty": "L3",
            "question": "t08 库存快照中，哪个仓库（仓库名称）的账面数量总和最大？",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION, AGGREGATION],
        },
    ]
    cases.extend(L3)

    # ═══════════════════════════════════════════════════════
    #  L4: 跨源 join — 跨系统 tool 切换
    # ═══════════════════════════════════════════════════════
    L4 = [
        {
            "id": "L4-01", "difficulty": "L4",
            "question": "批次号 BRM00001250701034 对应的质检结果是什么？列出检验结论、合格率、不良描述。",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": "合格;1.0;",
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE],
        },
        {
            "id": "L4-02", "difficulty": "L4",
            "question": "供应商编码 SUP0007 的供应商名称是什么？它的到货批次中，质检不合格的有哪些？",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": "苏州东山精密电子有限公司",
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE],
        },
        {
            "id": "L4-03", "difficulty": "L4",
            "question": "销售订单 SO202600010 关联的生产工单是哪个？该工单的完工状态是什么？",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": "MO202600001;计划",
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, NULL_HANDLING],
        },
        {
            "id": "L4-04", "difficulty": "L4",
            "question": "物料编码 RM00002 的物料名称是什么？它在 MES 系统中被领用了多少次？",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": "FPC连接器增强版",
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, PAGINATION],
        },
        {
            "id": "L4-05", "difficulty": "L4",
            "question": "工单 MO202600002 领用了哪些物料？列出物料编码和对应的供应商名称。",
            "expected_tools": ["mes_query", "erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, ONE_TO_MANY],
        },
        {
            "id": "L4-06", "difficulty": "L4",
            "question": "到货批次 BRM00081251117238 的供应商是谁？该批次的质检结论是什么？",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": "SUP0005;不合格",
            "answer_type": "exists",
            "traps": [CROSS_SOURCE],
        },
        {
            "id": "L4-07", "difficulty": "L4",
            "question": "销售订单 SO202600016 关联了哪些生产工单？这些工单的完工情况如何？",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, ONE_TO_MANY],
        },
    ]
    cases.extend(L4)

    # ═══════════════════════════════════════════════════════
    #  L5: 跨源多跳 — 多步推理
    # ═══════════════════════════════════════════════════════
    L5 = [
        {
            "id": "L5-01", "difficulty": "L5",
            "question": "找出所有到货检验合格但对应的 MES 质检不合格的批次号。",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, PAGINATION, ONE_TO_MANY],
        },
        {
            "id": "L5-02", "difficulty": "L5",
            "question": "哪个供应商的物料在质检环节的不合格率最高？列出供应商名称和不合格率。",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, PAGINATION, AGGREGATION],
        },
        {
            "id": "L5-03", "difficulty": "L5",
            "question": "从采购到货到质检完成，哪些批次的周期最长（到货日期到质检日期的时间差）？列出前 3 个批次。",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, TIME_FILTER, ONE_TO_MANY],
        },
        {
            "id": "L5-04", "difficulty": "L5",
            "question": "哪些生产工单（t07）领用的物料（t10）中包含质检不合格的批次（t11）？列出工单号。",
            "expected_tools": ["mes_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [ONE_TO_MANY, STRING_TYPE, PAGINATION],
        },
        {
            "id": "L5-05", "difficulty": "L5",
            "question": "ERP 中采购状态为 '执行中' 的订单，对应的供应商在 MES 质检中的平均合格率是多少？",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, PAGINATION, AGGREGATION],
        },
        {
            "id": "L5-06", "difficulty": "L5",
            "question": "哪些工单的计量参数（t12）出现过异常？列出工单号和异常说明。",
            "expected_tools": ["mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION],
        },
        {
            "id": "L5-07", "difficulty": "L5",
            "question": "t03 BOM 中，父项 FG00001 的完整子项物料清单是什么？这些子项物料在 t08 中的库存可用量分别是多少？",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION, NULL_HANDLING],
        },
    ]
    cases.extend(L5)

    # ═══════════════════════════════════════════════════════
    #  L6: 语义推理 — 需要理解业务含义
    # ═══════════════════════════════════════════════════════
    L6 = [
        {
            "id": "L6-01", "difficulty": "L6",
            "question": "哪些供应商存在'来料质量风险'？即：该供应商的物料在 t11 质检中出现过不合格或部分合格。列出供应商编码和名称。",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, PAGINATION, AGGREGATION],
        },
        {
            "id": "L6-02", "difficulty": "L6",
            "question": "哪些生产工单因为领用了不合格批次的物料而存在质量风险？列出工单号和货品名称。",
            "expected_tools": ["mes_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [ONE_TO_MANY, STRING_TYPE, PAGINATION],
        },
        {
            "id": "L6-03", "difficulty": "L6",
            "question": "根据 t08 库存快照，哪些物料的库存可用量低于账面数量的 50%？这些物料在 t05 中是否有未完成的采购订单？",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION, AGGREGATION],
        },
        {
            "id": "L6-04", "difficulty": "L6",
            "question": "哪些供应商（t01）的'是否有效'标记为 N，但仍然有未完成的采购订单（t05 中采购状态为执行中或新建）？",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION],
        },
        {
            "id": "L6-05", "difficulty": "L6",
            "question": "t06 到货中检验状态为 '待检' 的批次，在 t11 中是否已经有质检记录？找出所有'已到货但未质检完成'的批次。",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, PAGINATION, NULL_HANDLING],
        },
        {
            "id": "L6-06", "difficulty": "L6",
            "question": "分析 t12 计量参数异常记录，哪些车间/工单的异常最频繁？列出异常次数最多的前 3 个工单。",
            "expected_tools": ["mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, PAGINATION, AGGREGATION],
        },
        {
            "id": "L6-07", "difficulty": "L6",
            "question": "综合考虑 t05 采购订单状态、t06 到货检验状态、t11 质检结论，找出'采购到货质检全链路'中存在问题的供应商。",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, PAGINATION, AGGREGATION],
        },
    ]
    cases.extend(L6)

    # ═══════════════════════════════════════════════════════
    #  L7: 时间序列 + 异常检测
    # ═══════════════════════════════════════════════════════
    L7 = [
        {
            "id": "L7-01", "difficulty": "L7",
            "question": "2026 年 3 月到货的物料中，哪些在质检环节被判定为不合格？列出批次号和供应商编码。",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, TIME_FILTER, PAGINATION],
        },
        {
            "id": "L7-02", "difficulty": "L7",
            "question": "2026 年第一季度（1-3月），哪个供应商的到货合格率最低？",
            "expected_tools": ["erp_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, TIME_FILTER, PAGINATION, AGGREGATION],
        },
        {
            "id": "L7-03", "difficulty": "L7",
            "question": "t07 生产工单中，2026 年 5 月完工的工单有多少个？列出这些工单中关联的销售订单号（去重）。",
            "expected_tools": ["mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, TIME_FILTER, PAGINATION, NULL_HANDLING],
        },
        {
            "id": "L7-04", "difficulty": "L7",
            "question": "t12 计量参数中，2026 年 4 月的异常记录有多少条？主要集中在哪些车间？",
            "expected_tools": ["mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, TIME_FILTER, PAGINATION, AGGREGATION],
        },
        {
            "id": "L7-05", "difficulty": "L7",
            "question": "对比 t05 采购订单的 '要求到货日' 和 t06 的 '实际到货日期'，哪些订单延迟到货超过 7 天？",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, TIME_FILTER, PAGINATION, NULL_HANDLING],
        },
        {
            "id": "L7-06", "difficulty": "L7",
            "question": "t08 库存快照中，2026 年 5 月的快照数据显示哪些物料库存可用量不足（可用量 < 冻结量）？",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, TIME_FILTER, PAGINATION],
        },
        {
            "id": "L7-07", "difficulty": "L7",
            "question": "分析 t07 工单的计划开工日与实际开工日偏差，找出延迟开工超过 5 天的工单。",
            "expected_tools": ["mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [STRING_TYPE, TIME_FILTER, PAGINATION, NULL_HANDLING],
        },
    ]
    cases.extend(L7)

    # ═══════════════════════════════════════════════════════
    #  对抗性测试 (Adversarial)
    # ═══════════════════════════════════════════════════════
    ADV = [
        {
            "id": "ADV-01", "difficulty": "ADV",
            "question": "查询 t99 表的所有数据。",
            "expected_tools": [],
            "expected_answer": "不存在",
            "answer_type": "exists",
            "traps": [ADVERSARIAL],
        },
        {
            "id": "ADV-02", "difficulty": "ADV",
            "question": "所有表中哪些表包含 '日期' 列？列出表名和列名。",
            "expected_tools": ["erp_list_tables", "mes_list_tables"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [ADVERSARIAL, COLUMN_AMBIGUITY],
        },
        {
            "id": "ADV-03", "difficulty": "ADV",
            "question": "把 t05 采购订单的全部数据一次性返回给我。",
            "expected_tools": ["erp_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [ADVERSARIAL, PAGINATION],
        },
        {
            "id": "ADV-04", "difficulty": "ADV",
            "question": "在 MES 系统中查询 t05 采购订单表。",
            "expected_tools": [],
            "expected_answer": "ERP",
            "answer_type": "exists",
            "traps": [ADVERSARIAL, SYSTEM_BOUNDARY],
        },
        {
            "id": "ADV-05", "difficulty": "ADV",
            "question": "t11 质检记录中，'来料检验' 和 '成品检验' 的合格率有什么差异？",
            "expected_tools": ["mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [ADVERSARIAL, STRING_TYPE, PAGINATION, AGGREGATION],
        },
    ]
    cases.extend(ADV)

    # ═══════════════════════════════════════════════════════
    #  综合题 (Integration)
    # ═══════════════════════════════════════════════════════
    INT = [
        {
            "id": "INT-01", "difficulty": "INT",
            "question": "从采购→到货→质检→领用→生产，全链路追踪批次 BRM00081251117238：这个批次的物料被哪些工单领用了？这些工单的完工状态如何？",
            "expected_tools": ["erp_query", "mes_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, PAGINATION, ONE_TO_MANY],
        },
        {
            "id": "INT-02", "difficulty": "INT",
            "question": "对供应商 SUP0007 做一个全面的供应链分析：它的基本信息、采购订单总数、到货合格率、质检表现、以及关联的生产工单完成情况。",
            "expected_tools": ["erp_query", "erp_query", "erp_query", "mes_query", "mes_query"],
            "expected_answer": None,
            "answer_type": "exists",
            "traps": [CROSS_SOURCE, STRING_TYPE, PAGINATION, AGGREGATION],
        },
    ]
    cases.extend(INT)

    return cases


def get_cases_by_difficulty(difficulty: str) -> list[dict[str, Any]]:
    """按难度筛选测试用例"""
    all_cases = build_test_cases()
    return [c for c in all_cases if c["difficulty"] == difficulty]


def get_case_by_id(case_id: str) -> Optional[dict[str, Any]]:
    """按 ID 获取单个测试用例"""
    for c in build_test_cases():
        if c["id"] == case_id:
            return c
    return None