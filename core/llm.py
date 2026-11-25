"""
大模型统一调用客户端。
职责：封装 OpenAI 兼容接口（DeepSeek / 硅基流动 / 火山引擎 / OpenAI 等），统一处理超时重试与用量日志。
"""

from __future__ import annotations

import time
import requests

from core.config import Settings, get_logger

logger = get_logger("core.llm")


class LLMClient:
    """
    轻量级 OpenAI Chat Completions 兼容客户端，避免引入厚重的 SDK 依赖。
    """

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url
        self.default_model = settings.llm_model

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        timeout: int = 120,
        max_retries: int = 2,
    ) -> str:
        """
        发送对话补全请求并返回模型生成的纯文本内容。
        输入：系统提示词、用户提示词及可选的模型/温度/重试配置。
        输出：去除首尾空白的模型回复正文；鉴权缺失或多次重试仍失败时抛出异常。
        """
        if not self.api_key or self.api_key.startswith("sk-在这里"):
            raise ValueError("未配置有效的 LLM_API_KEY，请在 .env 文件中设置后再运行。")

        target_model = model or self.default_model
        endpoint = f"{self.base_url}/chat/completions"
        payload = {
            "model": target_model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 2):
            start_ts = time.monotonic()
            try:
                resp = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                # 针对限流（429）或网关临时错误（5xx）允许自动退避重试
                if resp.status_code in (429, 500, 502, 503, 504) and attempt <= max_retries:
                    logger.warning(
                        "LLM 接口返回状态码 %s（第 %s 次尝试），等待后重试...",
                        resp.status_code,
                        attempt,
                    )
                    time.sleep(2 * attempt)
                    continue

                resp.raise_for_status()
                data = resp.json()
                elapsed = time.monotonic() - start_ts
                usage = data.get("usage") or {}
                logger.info(
                    "LLM 调用完成 | model=%s | elapsed=%.1fs | prompt_tokens=%s | completion_tokens=%s",
                    target_model,
                    elapsed,
                    usage.get("prompt_tokens", "-"),
                    usage.get("completion_tokens", "-"),
                )
                return data["choices"][0]["message"]["content"].strip()
            except (requests.RequestException, KeyError, IndexError) as exc:
                last_exc = exc
                if attempt <= max_retries:
                    logger.warning("LLM 请求异常（第 %s 次尝试）: %s，即将重试...", attempt, exc)
                    time.sleep(2 * attempt)

        raise RuntimeError(f"LLM 调用失败（已重试 {max_retries} 次）: {last_exc}") from last_exc
