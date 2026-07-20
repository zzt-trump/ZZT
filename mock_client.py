#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mock 数据源客户端 — 从 ERP/MES 双源拉取 schema 和样本数据"""

import json
import logging
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from config import DATA_SOURCES, MOCK_TIMEOUT, CROSS_SOURCE_JOINS

logger = logging.getLogger(__name__)


class MockDataSource:
    """单个 Mock 数据源（ERP 或 MES）"""

    def __init__(self, source_cfg: dict):
        self.name = source_cfg["name"]
        self.base_url = source_cfg["base_url"].rstrip("/")
        self.token = source_cfg["token"]
        self.table_ids = source_cfg.get("tables", [])

    def _get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        req = Request(url, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        })
        try:
            with urlopen(req, timeout=MOCK_TIMEOUT) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            logger.error(f"[{self.name}] HTTP {e.code} on {path}")
            return {"error": f"HTTP {e.code}", "path": path}
        except URLError as e:
            logger.error(f"[{self.name}] connection error on {path}: {e.reason}")
            return {"error": str(e.reason), "path": path}

    def health(self) -> dict:
        return self._get("/health")

    def list_tables(self) -> list:
        r = self._get("/api/tables")
        return r.get("tables", [])

    def get_schema(self, table_id: str) -> dict:
        return self._get(f"/api/tables/{table_id}/schema")

    def get_data(self, table_id: str, limit: int = 100, offset: int = 0) -> dict:
        return self._get(f"/api/tables/{table_id}?limit={limit}&offset={offset}")

    def get_all_data(self, table_id: str, max_rows: int = 500) -> list:
        """分页取全量（最多 max_rows 行）"""
        rows = []
        offset = 0
        while offset < max_rows:
            r = self.get_data(table_id, limit=100, offset=offset)
            if "error" in r:
                break
            batch = r.get("rows", [])
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < 100:
                break
            offset += 100
        return rows[:max_rows]

    def fetch_full_snapshot(self) -> dict:
        """
        拉取该源所有表的 schema + 样本数据（首 20 行），返回：
        {
          "source_name": "ERP",
          "tables": {
            "t01": {
              "name": "供应商主数据",
              "columns": ["供应商编码", "供应商名称", ...],
              "sample_rows": [{...}, ...],
              "total_rows": 220
            },
            ...
          }
        }
        """
        tables = self.list_tables()
        snapshot = {"source_name": self.name, "tables": {}}
        for t in tables:
            tid = t.get("id", "")
            if not tid:
                continue
            schema = self.get_schema(tid)
            cols = [c.get("name", c) if isinstance(c, dict) else c
                    for c in schema.get("columns", [])]
            data = self.get_data(tid, limit=20, offset=0)
            sample = data.get("rows", [])
            total = data.get("total", 0)
            snapshot["tables"][tid] = {
                "name": t.get("name", tid),
                "columns": cols,
                "sample_rows": sample,
                "total_rows": total,
            }
        return snapshot


class MockDataHub:
    """双源聚合门面"""

    def __init__(self):
        self.sources = {s["name"]: MockDataSource(s) for s in DATA_SOURCES}
        self.erp = self.sources.get("ERP")
        self.mes = self.sources.get("MES")

    def health_all(self) -> dict:
        return {name: src.health() for name, src in self.sources.items()}

    def fetch_full_snapshot(self) -> dict:
        """拉取全部双源数据快照"""
        return {name: src.fetch_full_snapshot() for name, src in self.sources.items()}

    def get_join_info(self) -> list:
        return CROSS_SOURCE_JOINS

    def get_column_values(self, source_name: str, table_id: str,
                          column: str, limit: int = 50) -> list:
        """获取某表某列的不重复值（用于生成测试题的选项）"""
        src = self.sources.get(source_name)
        if not src:
            return []
        rows = src.get_all_data(table_id, max_rows=limit)
        vals = set()
        for r in rows:
            v = r.get(column)
            if v is not None:
                vals.add(str(v))
        return sorted(vals)[:limit]


# ── 全局缓存 ──────────────────────────────────────────
_cache = None


def get_hub() -> MockDataHub:
    global _cache
    if _cache is None:
        _cache = MockDataHub()
    return _cache