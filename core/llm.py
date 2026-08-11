"""LLM 客户端：OpenAI 兼容接口（DeepSeek 等），带重试与 token/成本统计"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from core.env import load_dotenv

# DeepSeek 约 $0.27/M input, $1.10/M output（cache miss 口径，随版本更新）
COST_PER_1K = {"input": 0.00027, "output": 0.0011}


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, cfg: dict, api_key: str | None = None):
        self.cfg = cfg
        self.base_url = cfg["base_url"].rstrip("/")
        self.model = cfg["model"]
        self.temperature = cfg.get("temperature", 0.3)
        self.max_tokens = cfg.get("max_tokens", 1500)
        self.timeout = cfg.get("timeout", 120)
        self.retries = cfg.get("retries", 3)
        load_dotenv()
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise LLMError("缺少 API key：请设置环境变量 DEEPSEEK_API_KEY")

    def chat(self,
             messages: list[dict],
             *,
             temperature: float | None = None,
             max_tokens: int | None = None,
             model: str | None = None,
             json_mode: bool = False) -> tuple[str, dict]:
        """返回 (text, meta)；meta 含 tokens 与 estimated_cost"""
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        for attempt in range(self.retries):
            try:
                t0 = time.time()
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=self.timeout,
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage", {})
                meta = {
                    "latency_ms": int((time.time() - t0) * 1000),
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "attempts": attempt + 1,   # 重试日志：成功前实际尝试次数
                    "estimated_cost": round(
                        usage.get("prompt_tokens", 0) / 1000 * COST_PER_1K["input"]
                        + usage.get("completion_tokens", 0) / 1000 * COST_PER_1K["output"], 6),
                }
                return data["choices"][0]["message"]["content"], meta
            except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise LLMError(f"LLM 调用失败: {last_err}")

    def chat_json(self,
                  messages: list[dict],
                  **kwargs) -> tuple[dict, dict]:
        text, meta = self.chat(messages, json_mode=True, **kwargs)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            # 模型偶尔在 JSON 外套代码块
            import re
            m = re.search(r"\{.*\}", text, re.S)
            obj = json.loads(m.group(0)) if m else {}
        return obj, meta
