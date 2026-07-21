#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock Data Harness — 工具层 (tools.py)

封装 6 个 tool 函数，供 LLM 通过 function-calling 风格调用。
每个 tool 内部自动注入正确的 token，模型永不知道 token 字符串。
"""

import json
import time
import urllib.request
import urllib.error
from functools import lru_cache
from typing import Any

# ── 配置 ──────────────────────────────────────────────────
ERP_BASE = "http://114.215.204.62:8005"
MES_BASE = "http://114.215.204.62:8006"
ERP_TOKEN = "erp-token-2026"
MES_TOKEN = "mes-token-2026"
REQUEST_TIMEOUT = 15  # 秒
MAX_RETRIES = 1

# ── 所有表的 schema 注册表 ───────────────────────────────
# 用于验证 tool 调用合法性 + 注入 system prompt
SCHEMA_REGISTRY: dict[str, dict[str, Any]] = {
    # ── ERP (8005) ──
    "t01": {"system": "ERP", "name": "供应商主数据", "columns": ["供应商编码", "供应商名称", "供应商简称", "供应商类别", "主供物料类别", "付款条件", "是否有效"]},
    "t02": {"system": "ERP", "name": "物料货品主数据", "columns": ["物料编码", "物料名称", "规格型号", "基本单位", "物料类别", "是否启用"]},
    "t03": {"system": "ERP", "name": "BOM物料清单", "columns": ["BOM行ID", "父项编码", "父项名称", "子项编码", "子项名称", "单位用量", "单位", "BOM版本", "生效日期", "失效日期", "是否当前版本"]},
    "t04": {"system": "ERP", "name": "销售订单", "columns": ["销售订单号", "客户编码", "客户名称", "货品编码", "货品名称", "订单数量", "已发货量", "销售单价", "订单日期", "要求交货日", "订单状态"]},
    "t05": {"system": "ERP", "name": "采购订单", "columns": ["采购订单行ID", "采购订单号", "供应商编码", "供应商名称", "物料编码", "物料名称", "采购数量", "已到货量", "含税单价(元)", "采购日期", "要求到货日", "供应商确认到货日", "采购状态"]},
    "t06": {"system": "ERP", "name": "采购到货记录", "columns": ["到货记录ID", "到货单号", "采购订单号", "供应商编码", "物料编码", "实际到货日期", "到货数量", "批次号", "入库仓库编码", "检验状态"]},
    "t08": {"system": "ERP", "name": "物料库存快照", "columns": ["库存记录ID", "物料/货品编码", "物料/货品名称", "仓库编码", "仓库名称", "账面数量", "冻结量", "可用量", "快照日期"]},
    "t09": {"system": "ERP", "name": "MRP建议表", "columns": ["MRP建议ID", "物料编码", "物料名称", "建议量", "建议类型", "建议日期", "优先级"]},
    # ── MES (8006) ──
    "t07": {"system": "MES", "name": "生产工单", "columns": ["工单ID", "工单号", "关联销售单号", "货品编码", "货品名称", "计划产量", "已完工量", "计划开工日", "计划完工日", "实际开工日", "实际完工日", "工单状态", "优先级", "生产车间"]},
    "t10": {"system": "MES", "name": "MES物料领用记录", "columns": ["领用记录ID", "领用单号", "工单号", "物料编码", "物料名称", "批次号", "计划用量", "实际领用量", "领用日期", "操作员工号"]},
    "t11": {"system": "MES", "name": "MES质检批次记录", "columns": ["质检记录ID", "批次号", "关联工单号", "物料/货品编码", "物料/货品名称", "供应商编码", "检验类型", "检验日期", "检验员", "送检数量", "合格数量", "不合格数量", "合格率", "检验结论", "不良类别", "不良描述"]},
    "t12": {"system": "MES", "name": "MES计量参数记录", "columns": ["计量记录ID", "设备/仪表编码", "设备/仪表名称", "计量类型", "参数项名称", "参数值", "单位", "采集时间", "标准下限", "标准上限", "是否异常", "异常说明", "关联工单号", "车间"]},
}

# 跨源 join 键映射
CROSS_SOURCE_JOINS = [
    {"left": ("t06", "批次号"), "right": ("t11", "批次号"), "description": "到货批次 ↔ 质检批次"},
    {"left": ("t04", "销售订单号"), "right": ("t07", "关联销售单号"), "description": "销售订单 ↔ 生产工单"},
    {"left": ("t02", "物料编码"), "right": ("t10", "物料编码"), "description": "物料主数据 ↔ 领用记录"},
]

# 查询缓存
_cache: dict[str, dict[str, Any]] = {}


def _cache_key(source: str, table_id: str, limit: int, offset: int) -> str:
    return f"{source}:{table_id}:{limit}:{offset}"


def _http_get(url: str, token: str) -> dict[str, Any]:
    """带重试的 HTTP GET 请求"""
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            last_error = e
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            if e.code == 401:
                return {"error": "unauthorized", "hint": f"鉴权失败，请检查是否调用了正确系统的接口（当前 token 不属于目标系统）", "http_status": 401}
            if e.code == 404:
                return {"error": "not_found", "hint": f"表或资源不存在，请检查 table_id 是否属于当前系统", "http_status": 404}
            if e.code == 400:
                return {"error": "bad_request", "hint": "请求参数错误", "http_status": 400, "detail": error_body}
            if attempt < MAX_RETRIES:
                time.sleep(1)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(1)
    return {"error": "network_error", "hint": f"网络请求失败: {str(last_error)}", "http_status": 0}


# ═══════════════════════════════════════════════════════════
#  6 个 Tool 函数
# ═══════════════════════════════════════════════════════════

def _do_query(source: str, base_url: str, token: str, table_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """通用查询逻辑"""
    tid = table_id.lower().strip()
    limit = max(1, min(limit, 5000))
    offset = max(0, offset)

    # 检查缓存
    ck = _cache_key(source, tid, limit, offset)
    if ck in _cache:
        return {**_cache[ck], "_cached": True}

    # 先检查表是否存在
    if tid not in SCHEMA_REGISTRY:
        # 尝试给出提示
        suggestions = [t for t in SCHEMA_REGISTRY if SCHEMA_REGISTRY[t]["system"] == source]
        return {
            "error": "table_not_found",
            "table_id": tid,
            "hint": f"表 '{tid}' 不存在于 {source} 系统中",
            "available_tables_in_{}".format(source): suggestions,
        }

    # 检查表是否属于当前系统
    if SCHEMA_REGISTRY[tid]["system"] != source:
        correct_system = SCHEMA_REGISTRY[tid]["system"]
        return {
            "error": "wrong_system",
            "table_id": tid,
            "hint": f"表 '{tid}' 属于 {correct_system} 系统，请使用 {correct_system.lower()}_query() 工具",
            "actual_system": correct_system,
        }

    url = f"{base_url}/api/tables/{tid}?limit={limit}&offset={offset}"
    result = _http_get(url, token)

    if "error" not in result:
        result["_source"] = source
        result["_returned"] = result.get("count", len(result.get("rows", [])))
        result["_total"] = result.get("total", result.get("_returned", 0))
        result["_has_more"] = result["_returned"] < result["_total"]
        if result["_has_more"]:
            result["_pagination_hint"] = f"已返回 {result['_returned']}/{result['_total']} 条，还有 {result['_total'] - result['_returned']} 条未返回。如需更多请用 offset={offset + limit} 翻页"

        # 缓存
        _cache[ck] = result

    return result


def _do_list_tables(source: str, base_url: str, token: str) -> dict[str, Any]:
    """通用表目录"""
    ck = _cache_key(source, "__tables__", 0, 0)
    if ck in _cache:
        return {**_cache[ck], "_cached": True}

    url = f"{base_url}/api/tables"
    result = _http_get(url, token)

    if "error" not in result:
        # 注入 schema 信息
        tables = result.get("tables", [])
        enriched = []
        for t in tables:
            tid = t.get("id", "")
            if tid in SCHEMA_REGISTRY:
                t["columns"] = SCHEMA_REGISTRY[tid]["columns"]
                t["system"] = SCHEMA_REGISTRY[tid]["system"]
            enriched.append(t)
        result["tables"] = enriched
        result["_source"] = source
        _cache[ck] = result

    return result


def _do_get_schema(source: str, token: str, table_id: str) -> dict[str, Any]:
    """通用 schema 查询"""
    tid = table_id.lower().strip()

    if tid in SCHEMA_REGISTRY:
        meta = SCHEMA_REGISTRY[tid]
        if meta["system"] != source:
            return {
                "error": "wrong_system",
                "table_id": tid,
                "hint": f"表 '{tid}' 属于 {meta['system']} 系统，请使用 {meta['system'].lower()}_get_schema() 工具",
                "actual_system": meta["system"],
            }
        return {
            "id": tid,
            "name": meta["name"],
            "system": meta["system"],
            "columns": [{"name": c} for c in meta["columns"]],
            "column_count": len(meta["columns"]),
        }

    return {"error": "table_not_found", "table_id": tid, "hint": f"表 '{tid}' 不在已知的 schema 注册表中"}


# ── 公开 Tool 定义 ───────────────────────────────────────

def erp_list_tables() -> dict[str, Any]:
    """列出 ERP 系统中所有表及其列信息"""
    return _do_list_tables("ERP", ERP_BASE, ERP_TOKEN)


def erp_get_schema(table_id: str) -> dict[str, Any]:
    """获取 ERP 系统中某张表的列定义"""
    return _do_get_schema("ERP", ERP_TOKEN, table_id)


def erp_query(table_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """查询 ERP 系统中某张表的数据，支持分页（limit≤5000）"""
    return _do_query("ERP", ERP_BASE, ERP_TOKEN, table_id, limit, offset)


def mes_list_tables() -> dict[str, Any]:
    """列出 MES 系统中所有表及其列信息"""
    return _do_list_tables("MES", MES_BASE, MES_TOKEN)


def mes_get_schema(table_id: str) -> dict[str, Any]:
    """获取 MES 系统中某张表的列定义"""
    return _do_get_schema("MES", MES_TOKEN, table_id)


def mes_query(table_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """查询 MES 系统中某张表的数据，支持分页（limit≤5000）"""
    return _do_query("MES", MES_BASE, MES_TOKEN, table_id, limit, offset)


# ── Tool 元数据（供 LLM prompt 使用） ─────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "erp_list_tables",
        "description": "列出 ERP 系统(8005端口)中所有表及其列信息。返回表名、中文名、列名列表。",
        "parameters": {},
    },
    {
        "name": "erp_get_schema",
        "description": "获取 ERP 系统中某张表的列定义。",
        "parameters": {"table_id": "表ID，如 t01, t02, t03, t04, t05, t06, t08, t09"},
    },
    {
        "name": "erp_query",
        "description": "查询 ERP 系统中某张表的数据。limit 最大 5000，offset 从 0 开始。注意：所有字段值均为字符串类型。",
        "parameters": {"table_id": "表ID", "limit": "返回条数(默认100，最大5000)", "offset": "偏移量(默认0)"},
    },
    {
        "name": "mes_list_tables",
        "description": "列出 MES 系统(8006端口)中所有表及其列信息。返回表名、中文名、列名列表。",
        "parameters": {},
    },
    {
        "name": "mes_get_schema",
        "description": "获取 MES 系统中某张表的列定义。",
        "parameters": {"table_id": "表ID，如 t07, t10, t11, t12"},
    },
    {
        "name": "mes_query",
        "description": "查询 MES 系统中某张表的数据。limit 最大 5000，offset 从 0 开始。注意：所有字段值均为字符串类型。",
        "parameters": {"table_id": "表ID", "limit": "返回条数(默认100，最大5000)", "offset": "偏移量(默认0)"},
    },
]

TOOL_DISPATCH = {
    "erp_list_tables": erp_list_tables,
    "erp_get_schema": erp_get_schema,
    "erp_query": erp_query,
    "mes_list_tables": mes_list_tables,
    "mes_get_schema": mes_get_schema,
    "mes_query": mes_query,
}


def clear_cache() -> None:
    """清除查询缓存"""
    _cache.clear()


def get_cache_stats() -> dict[str, Any]:
    """获取缓存统计"""
    return {"cached_entries": len(_cache), "keys": list(_cache.keys())}