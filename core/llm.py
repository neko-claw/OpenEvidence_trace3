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
        self.last_attempts = 0   # 最近一次 chat 的实际尝试次数（重试日志）
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
            self.last_attempts = attempt + 1
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


class OfflineLLM:
    """离线回放模型（计划 §10 风险降级：现场网络失败 -> 离线回放模式）。

    不调用任何 API：从 user 消息中的证据块抽取 [E#] / [S#] 编号，
    生成固定结构的演示回答，保证 experiment -> run_condition -> 生成 ->
    引用校验 -> JSONL 留痕的端到端链路在无 key 环境下可验收。
    所有离线回答标记 provider=offline-mock，不得用于正式实验结论。
    """

    model = "offline-mock"
    retries = 1
    last_attempts = 1

    def _chat_text(self, messages: list[dict]) -> str:
        import re
        user = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
        e_ids = sorted(set(int(x) for x in re.findall(r"\[E(\d+)\]", user)))
        s_ids = sorted(set(int(x) for x in re.findall(r"\[S(\d+)\]", user)))
        has_search = bool(re.search(r"通用搜索工具|搜索结果", user))
        lines = ["## 结论摘要\n（离线回放演示回答，不用于正式结论）本回答基于提供的上下文生成。"]
        if e_ids:
            lines.append("## 证据说明")
            for i in e_ids[:3]:
                lines.append(f"- 要点 {i}，与检索证据相关。[E{i}]")
        elif s_ids:
            lines.append("## 证据说明")
            for i in s_ids[:3]:
                lines.append(f"- 要点 {i}，来自通用搜索结果。[S{i}]")
        elif not has_search:
            lines.append("## 证据说明\n（无外部证据条件，基于模型知识作答，不引用来源。）")
        else:
            lines.append("## 证据说明\n本次搜索未返回可用结果，检索缺口见局限说明。")
        lines.append("## 局限与边界\n离线回放：仅供演示与链路验收，不代表真实模型输出；不用于临床诊疗。")
        return "\n".join(lines)

    def chat(self, messages: list[dict], **kwargs) -> tuple[str, dict]:
        return self._chat_text(messages), {
            "latency_ms": 1, "input_tokens": 0, "output_tokens": 0,
            "estimated_cost": 0.0, "attempts": 1,
        }

    def chat_json(self, messages: list[dict], **kwargs) -> tuple[dict, dict]:
        return {}, self.chat(messages, **kwargs)[1]

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
