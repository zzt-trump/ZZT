#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock Data Harness — 查询缓存 (cache.py)

以 (source, table_id, limit, offset) 为 key，
单次会话内自动去重，防止模型重复查询同一数据。
"""

from tools import clear_cache, get_cache_stats

__all__ = ["clear_cache", "get_cache_stats"]