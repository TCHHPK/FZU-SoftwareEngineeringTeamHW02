"""统一大模型客户端。

设计目标（针对本项目 11 天工期和答辩需求）：
  1. OpenAI 兼容协议 + 可配 base_url —— 一处切换 DeepSeek / 通义 / Kimi / 校内 vLLM，
     也便于做「同一模型、不同定制」的公平对比实验（附录 B.3）。
  2. json_call 三重兜底 —— response_format → 抠 JSON 片段 → 重试；一块失败不拖垮整单任务。
  3. 多 key 轮换 + 指数退避 —— 答辩现场最怕限流。
  4. 全量调用日志（prompt 版本、token、耗时、是否降级）—— 写博客和排查问题都要用。
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger("app.llm")

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class LLMError(RuntimeError):
    """所有重试都失败后抛出。调用方应捕获并把任务标为 failed/partial，而不是让进程崩掉。"""


@dataclass
class LLMUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0
    fallbacks: int = 0
    elapsed: float = 0.0
    history: list[dict] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "retries": self.retries,
            "json_fallbacks": self.fallbacks,
            "elapsed_sec": round(self.elapsed, 1),
        }


@dataclass
class LLMConfig:
    """从环境变量读取，便于每个成员用不同的 key 本地调试。"""

    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    api_keys: list[str] = field(default_factory=list)
    timeout: int = 120
    max_retries: int = 3
    temperature: float = 0.2
    max_tokens: int = 4096

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """默认值统一从 app.core.config.settings 取，避免配置出现两处真相。"""
        from app.core.config import settings

        raw_keys = os.getenv("LLM_API_KEYS") or os.getenv("LLM_API_KEY") or ""
        keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        return cls(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_keys=keys,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )


class LLMClient:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self.usage = LLMUsage()
        self._key_cursor = 0

    # ---------------------------------------------------------------- 底层
    def _next_key(self) -> str:
        if not self.config.api_keys:
            raise LLMError("未配置 LLM_API_KEY / LLM_API_KEYS，请复制 .env.example 为 .env 并填写")
        key = self.config.api_keys[self._key_cursor % len(self.config.api_keys)]
        self._key_cursor += 1
        return key

    def _post(self, payload: dict, key: str) -> dict:
        resp = requests.post(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.config.timeout,
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400:
            # 4xx（除 429）通常是请求本身有问题，重试无意义，但换成备用 key 可能有效
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    # ---------------------------------------------------------------- 公开
    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """普通对话，返回文本内容。失败抛 LLMError。"""
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        started = time.time()
        for attempt in range(self.config.max_retries):
            try:
                data = self._post(payload, self._next_key())
                choice = (data.get("choices") or [{}])[0]
                content = (choice.get("message") or {}).get("content") or ""
                usage = data.get("usage") or {}
                self.usage.calls += 1
                self.usage.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.usage.completion_tokens += int(usage.get("completion_tokens") or 0)
                self.usage.elapsed += time.time() - started
                self.usage.history.append({
                    "model": self.config.model,
                    "json_mode": json_mode,
                    "attempt": attempt + 1,
                    "elapsed": round(time.time() - started, 2),
                    "prompt_chars": len(system) + len(user),
                    "completion_chars": len(content),
                })
                if not content.strip():
                    raise LLMError("模型返回空内容")
                return content
            except Exception as exc:  # noqa: BLE001 - 需要覆盖网络/解析各类异常
                last_err = exc
                self.usage.retries += 1
                wait = min(2 ** attempt + random.random(), 20)
                logger.warning("LLM 调用失败(第 %s 次)：%s，%.1fs 后重试", attempt + 1, exc, wait)
                time.sleep(wait)

        self.usage.elapsed += time.time() - started
        raise LLMError(f"LLM 调用在 {self.config.max_retries} 次尝试后仍失败：{last_err}")

    def json_call(
        self,
        system: str,
        user: str,
        *,
        default: Any = None,
        temperature: float | None = None,
    ) -> Any:
        """要求模型返回 JSON。三重兜底：

        ① 先带 response_format=json_object 请求；
        ② 若失败，去掉该参数再请求一次（部分兼容服务不支持）；
        ③ 解析失败则从文本里抠 ```json ... ``` 或第一个 {...} 片段；
        ④ 仍失败返回 default（调用方按「该块跳过并记日志」处理）。
        """
        try:
            raw = self.chat(system, user, temperature=temperature, json_mode=True)
        except LLMError:
            logger.warning("json_mode 请求失败，降级为普通请求")
            raw = self.chat(system, user, temperature=temperature, json_mode=False)

        parsed = _parse_json(raw)
        if parsed is None:
            self.usage.fallbacks += 1
            logger.error("JSON 解析失败，原文前 300 字：%s", raw[:300])
            return default
        return parsed


def _parse_json(raw: str) -> Any | None:
    """从模型输出里尽力抠出 JSON。"""
    text = (raw or "").strip()
    if not text:
        return None

    for candidate in (text, *_JSON_FENCE.findall(text)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 退一步：取第一个 { 到最后一个 } 之间的内容
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # 再退一步：去掉常见的尾随逗号
    if 0 <= start < end:
        cleaned = re.sub(r",\s*([}\]])", r"\1", text[start:end + 1])
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    return None


# 全局单例：整站共用一个用量统计对象，便于评测脚本读取
_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
