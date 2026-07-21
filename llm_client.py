#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock Data Harness — LLM 客户端 (llm_client.py)

封装原生 Ollama API (/api/chat)，实现 tool-calling 循环。
"""

import json
import re
import time
import urllib.request
import urllib.error
from typing import Any

# ── 配置 ──────────────────────────────────────────────────
OLLAMA_BASE = "http://localhost:11434"
MODEL = "qwen3.5:9b"
REQUEST_TIMEOUT = 120  # 秒，模型推理可能较慢
MAX_TOOL_ROUNDS = 10  # 最多 tool 调用轮次


class LLMError(Exception):
    """LLM 调用错误"""
    pass


class LLMClient:
    """封装 Qwen 3.5-9B via Ollama 原生 API"""

    def __init__(self, base_url: str = OLLAMA_BASE, model: str = MODEL):
        self.base_url = base_url
        self.model = model
        self._tool_names: list[str] = []

    def set_tools(self, tool_definitions: list[dict]) -> None:
        """注册可用的 tool 列表"""
        self._tool_names = [t["name"] for t in tool_definitions]

    def _raw_chat(self, messages: list[dict]) -> dict[str, Any]:
        """单次原生 API 调用"""
        payload = json.dumps({
            "model": self.model,
            "think": False,
            "stream": False,
            "messages": messages,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise LLMError(f"Ollama HTTP {e.code}: {body[:500]}")
        except urllib.error.URLError as e:
            raise LLMError(f"Ollama 连接失败（服务是否已启动？）: {e.reason}")
        except Exception as e:
            raise LLMError(f"Ollama 调用异常: {e}")

    def _parse_tool_call(self, content: str) -> list[dict]:
        """
        从模型回复中解析 tool_call。
        支持多种格式：
        1. JSON 格式：{"tool": "erp_query", "arguments": {"table_id": "t05", ...}}
        2. 代码块中的 JSON：```json\n{...}\n```
        3. 函数调用格式：erp_query(table_id="t05", limit=50)
        4. 自然语言中的 tool 调用
        """
        calls = []

        # 尝试 1：提取 JSON 代码块
        json_blocks = re.findall(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        for block in json_blocks:
            try:
                obj = json.loads(block.strip())
                if isinstance(obj, dict) and "tool" in obj:
                    calls.append(self._normalize_call(obj))
                elif isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, dict) and "tool" in item:
                            calls.append(self._normalize_call(item))
            except json.JSONDecodeError:
                pass

        if calls:
            return calls

        # 尝试 2：提取内联 JSON 对象
        json_objs = re.findall(r'\{[^{}]*"tool"\s*:\s*"[^"]+"[^{}]*\}', content)
        for obj_str in json_objs:
            try:
                obj = json.loads(obj_str)
                if "tool" in obj:
                    calls.append(self._normalize_call(obj))
            except json.JSONDecodeError:
                pass

        if calls:
            return calls

        # 尝试 3：Python 函数调用风格
        # 匹配 erp_query(table_id="t05", limit=50) 或 mes_query(table_id="t07")
        func_pattern = r'\b(erp_list_tables|erp_get_schema|erp_query|mes_list_tables|mes_get_schema|mes_query)\s*\((.*?)\)'
        for match in re.finditer(func_pattern, content, re.DOTALL):
            tool_name = match.group(1)
            args_str = match.group(2)
            args = self._parse_python_args(args_str)
            if tool_name in self._tool_names:
                calls.append({"tool": tool_name, "arguments": args})

        return calls

    def _normalize_call(self, obj: dict) -> dict:
        """标准化 tool call 格式"""
        args = obj.get("arguments", obj.get("args", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        return {"tool": obj["tool"], "arguments": args}

    def _parse_python_args(self, args_str: str) -> dict:
        """解析 Python 风格的函数参数"""
        args = {}
        # 匹配 key=value 对
        kv_pattern = r'(\w+)\s*=\s*("[^"]*"|\'[^\']*\'|\d+)'
        for match in re.finditer(kv_pattern, args_str):
            key = match.group(1)
            val = match.group(2)
            # 去掉引号
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            else:
                try:
                    val = int(val)
                except ValueError:
                    pass
            args[key] = val
        return args

    def chat_with_tools(
        self,
        messages: list[dict],
        tool_dispatch: dict[str, Any],
        max_rounds: int = MAX_TOOL_ROUNDS,
    ) -> dict[str, Any]:
        """
        带 tool 循环的对话。

        返回:
        {
            "final_answer": str,
            "tool_calls": [{"tool": str, "arguments": dict, "result": dict}],
            "rounds": int,
            "errors": [str],
        }
        """
        tool_calls_log: list[dict] = []
        errors: list[str] = []

        for round_idx in range(max_rounds):
            # 调用 LLM
            try:
                response = self._raw_chat(messages)
            except LLMError as e:
                errors.append(f"Round {round_idx + 1}: {e}")
                break

            content = response.get("message", {}).get("content", "")

            # 尝试解析 tool_call
            tool_calls = self._parse_tool_call(content)

            if not tool_calls:
                # 没有 tool_call，认为是最终答案
                return {
                    "final_answer": content.strip(),
                    "tool_calls": tool_calls_log,
                    "rounds": round_idx + 1,
                    "errors": errors,
                    "raw_response": response,
                }

            # 执行 tool 调用
            assistant_msg = content
            tool_results_content = []

            for tc in tool_calls:
                tool_name = tc["tool"]
                tool_args = tc["arguments"]
                if tool_name not in tool_dispatch:
                    result = {"error": "unknown_tool", "tool": tool_name, "hint": f"未知工具 '{tool_name}'，可用: {list(tool_dispatch.keys())}"}
                    errors.append(f"Round {round_idx + 1}: 未知工具 {tool_name}")
                else:
                    try:
                        if tool_args:
                            result = tool_dispatch[tool_name](**tool_args)
                        else:
                            result = tool_dispatch[tool_name]()
                    except Exception as e:
                        result = {"error": "tool_execution_error", "tool": tool_name, "detail": str(e)}
                        errors.append(f"Round {round_idx + 1}: {tool_name} 执行失败: {e}")

                # 截断过大的结果，防止超出 context window
                result_str = json.dumps(result, ensure_ascii=False)
                if len(result_str) > 8000:
                    if "rows" in result:
                        row_count = len(result["rows"])
                        result["rows"] = result["rows"][:50]
                        result["_truncated"] = True
                        result["_truncated_hint"] = f"结果过大，仅显示前 50 行（共 {row_count} 行）。请缩小查询范围或使用分页。"
                    result_str = json.dumps(result, ensure_ascii=False)

                tool_calls_log.append({"tool": tool_name, "arguments": tool_args, "result": result})
                tool_results_content.append(f"[工具调用结果 {tool_name}({json.dumps(tool_args, ensure_ascii=False)})]:\n{result_str}")

            # 构造下一轮 messages
            tool_results_text = "\n\n".join(tool_results_content)
            messages.append({"role": "assistant", "content": assistant_msg})
            messages.append({"role": "user", "content": f"以下是工具调用的结果，请根据这些结果继续分析或回答问题：\n\n{tool_results_text}"})

        # 超过最大轮次
        return {
            "final_answer": content.strip() if 'content' in dir() else "",
            "tool_calls": tool_calls_log,
            "rounds": max_rounds,
            "errors": errors + [f"达到最大 tool 调用轮次 ({max_rounds})"],
            "truncated": True,
        }


def check_ollama_health() -> dict[str, Any]:
    """检查 Ollama 服务是否可用"""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return {"ok": True, "response": resp.read().decode("utf-8")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_model_available(model: str = MODEL) -> dict[str, Any]:
    """检查模型是否已下载"""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            if model in models:
                return {"ok": True, "model": model}
            # 检查部分匹配
            for m in models:
                if model in m or m in model:
                    return {"ok": True, "model": m, "matched": True}
            return {"ok": False, "error": f"模型 '{model}' 未找到，可用模型: {models}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}