#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ollama API 客户端 — 封装原生 /api/chat 接口，支持 think:false"""

import json
import time
import logging
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama 原生 API 客户端（/api/chat，think:false 可靠生效）"""

    def __init__(self, base_url=None, model=None, timeout=None):
        self.base_url = (base_url or OLLAMA_BASE_URL).rstrip("/")
        self.model = model or OLLAMA_MODEL
        self.timeout = timeout or OLLAMA_TIMEOUT

    # ── 健康检查 ──────────────────────────────────────
    def health_check(self) -> dict:
        """检查 Ollama 服务是否在线"""
        try:
            req = Request(f"{self.base_url}/", method="GET")
            with urlopen(req, timeout=5) as resp:
                return {"ok": True, "status": resp.status}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── 列出模型 ──────────────────────────────────────
    def list_models(self) -> list:
        """返回已安装模型列表"""
        try:
            req = Request(f"{self.base_url}/api/tags", method="GET")
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning(f"list_models failed: {e}")
            return []

    # ── 聊天（非流式）──────────────────────────────────
    def chat(self, messages: list, system: str = None,
             temperature: float = 0.3, max_tokens: int = 2048,
             think: bool = False) -> dict:
        """
        发送聊天请求，返回 dict:
          {"ok": True, "content": "...", "tokens_in": ..., "tokens_out": ..., "elapsed_ms": ...}
          {"ok": False, "error": "..."}
        """
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": full_messages,
            "stream": False,
            "think": think,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        t0 = time.perf_counter()
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = Request(
                f"{self.base_url}/api/chat",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
                data = json.loads(raw)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                content = data.get("message", {}).get("content", "")
                return {
                    "ok": True,
                    "content": content,
                    "tokens_in": data.get("prompt_eval_count", 0),
                    "tokens_out": data.get("eval_count", 0),
                    "elapsed_ms": elapsed_ms,
                }
        except HTTPError as e:
            return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
        except URLError as e:
            return {"ok": False, "error": f"Connection error: {e.reason}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── 聊天（流式，返回生成器）────────────────────────
    def chat_stream(self, messages: list, system: str = None,
                    temperature: float = 0.3, max_tokens: int = 2048,
                    think: bool = False):
        """流式聊天，逐 token yield"""
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": full_messages,
            "stream": True,
            "think": think,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = Request(
                f"{self.base_url}/api/chat",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=self.timeout) as resp:
                for line in resp:
                    line = line.decode().strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            yield f"[ERROR: {e}]"


# ── 全局单例 ──────────────────────────────────────────
_client = None


def get_client() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client