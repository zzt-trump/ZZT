#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock Data Harness — Schema 注册表 (schema_registry.py)

预加载所有 12 张表的列名、所属系统、跨源 join 键映射。
供 tools.py 验证 tool 调用合法性，供 prompts.py 注入 system prompt。
"""

from typing import Optional

from tools import SCHEMA_REGISTRY, CROSS_SOURCE_JOINS

__all__ = ["SCHEMA_REGISTRY", "CROSS_SOURCE_JOINS"]


def get_tables_by_system(system: str) -> list[str]:
    """按系统获取表 ID 列表"""
    return sorted([tid for tid, meta in SCHEMA_REGISTRY.items() if meta["system"] == system])


def validate_table(table_id: str, expected_system: Optional[str] = None) -> dict:
    """验证表是否存在于注册表中，可选验证是否属于指定系统"""
    tid = table_id.lower().strip()
    if tid not in SCHEMA_REGISTRY:
        return {"valid": False, "error": f"表 '{tid}' 不存在", "all_tables": list(SCHEMA_REGISTRY.keys())}
    if expected_system and SCHEMA_REGISTRY[tid]["system"] != expected_system:
        return {"valid": False, "error": f"表 '{tid}' 属于 {SCHEMA_REGISTRY[tid]['system']}，不是 {expected_system}"}
    return {"valid": True, "table": SCHEMA_REGISTRY[tid]}


def get_join_keys() -> list[dict]:
    """获取跨源 join 键映射"""
    return CROSS_SOURCE_JOINS


def schema_summary() -> str:
    """生成 schema 摘要文本，用于注入 system prompt"""
    lines = ["## 数据源 Schema 摘要", ""]
    for system in ["ERP", "MES"]:
        lines.append(f"### {system} 系统")
        for tid in get_tables_by_system(system):
            meta = SCHEMA_REGISTRY[tid]
            cols = ", ".join(meta["columns"])
            lines.append(f"- **{tid}** ({meta['name']}): {cols}")
        lines.append("")

    lines.append("### 跨系统关联键")
    for j in CROSS_SOURCE_JOINS:
        lines.append(f"- {j['left'][0]}.{j['left'][1]} ↔ {j['right'][0]}.{j['right'][1]} ({j['description']})")

    return "\n".join(lines)