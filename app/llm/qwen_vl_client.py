"""Qwen-VL-Max multi-modal chat client (DashScope OpenAI-compatible).

支持多 key 轮询 + failover (跟 :mod:`app.llm.minimax_client` 同款):
- 从 ``settings.qwen_vl.api_keys`` 读多个 key
- 每次 ``avision()`` 按 round-robin 选 key, 失败 (尤其 429 / 5xx) 自动切下一个
- 客户端维护 key 池 + 失败计数, 冷却期内的 key 跳过

复用现有的 ``DASHSCOPE_API_KEY`` 环境变量 (阿里百炼 OpenAI 兼容
endpoint), 跟 :class:`app.llm.embedding_client.DashScopeEmbeddingClient`
共享同一 credential, 0 新接入成本。

设计 (Phase PDF-C.3)
--------------------
* **调用方式**: ``client.avision(image_png, prompt) -> markdown_str``.
  image_png 是 PyMuPDF 渲染的 PNG bytes, 通过 base64 inline 进
  multimodal message content.
* **endpoint**: DashScope OpenAI 兼容
  ``https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions``,
  model ``qwen-vl-max``.
* **失败冷却**: 同一 key 失败 N 秒内不再尝试 (默认 60s, 跟
  MiniMaxChatClient 同款).
* **Pi 端友好**: 纯网络调用, 不耗 CPU, 不引新 apt 包.

约束 (跟 Phase PDF-C.1+C.2 + INC-005 "0 改 runtime" 同款)
--------------------------------------------------------
* **0 改** ``app/llm/minimax_client.py`` (它已经是现有, 跟它同款 pattern
  参考).
* **0 改** ``app/llm/embedding_client.py`` (它已经是现有, 跟它同款
  pattern 参考).
* 默认 **opt-in** (loader.py 加 ``prefer_vision=False`` kwarg),
  Phase C.1+C.2 行为完全不变.
"""

from __future__ import annotations

import base64
import logging
import os
import threading
import time
from typing import Any, List

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class QwenVLClient:
    """Async multi-modal client for DashScope Qwen-VL-Max.

    多 key 支持 (跟 MiniMaxChatClient 同款, 从环境读):
        DASHSCOPE_API_KEY      # 优先 (主 key)
        DASHSCOPE_API_KEY_2    # 备用 1
        DASHSCOPE_API_KEY_3    # 备用 2
        ...

    ``settings.qwen_vl.api_keys`` 列表按上述顺序排列; 单 key 时退化为
    单 key 模式。failover 走 round-robin + 60s 冷却窗口。
    """

    # 失败冷却: 同一 key 失败 N 秒内不再尝试 (默认 60s, 跟
    # MiniMaxChatClient.COOLDOWN_SECONDS 同款)
    COOLDOWN_SECONDS = 60

    BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    MODEL = "qwen-vl-max"
    # 默认请求路径: chat/completions
    CHAT_COMPLETIONS_PATH = "/chat/completions"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_keys = self._collect_keys(settings)
        if not self._api_keys:
            raise RuntimeError(
                "QwenVLClient: 至少需要一个 DASHSCOPE_API_KEY "
                "(settings.qwen_vl.api_keys 或 DASHSCOPE_API_KEY 环境变量)"
            )

        self._lock = threading.Lock()
        self._cursor = 0
        # 每个 key 的失败时间戳 (epoch seconds); < COOLDOWN_SECONDS 时跳过
        self._fail_ts: List[float] = [0.0] * len(self._api_keys)
        self._timeout = settings.qwen_vl.timeout

        logger.info(
            "QwenVLClient: loaded %d key(s) from base_url=%s, model=%s",
            len(self._api_keys),
            self.BASE_URL,
            self.MODEL,
        )

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        return self.MODEL

    @property
    def base_url(self) -> str:
        return self.BASE_URL

    @property
    def key_count(self) -> int:
        return len(self._api_keys)

    async def avision(
        self,
        image_png: bytes,
        prompt: str,
        **kw: Any,
    ) -> str:
        """Send ``image_png`` + ``prompt`` to Qwen-VL-Max and return markdown.

        Parameters
        ----------
        image_png:
            PNG image bytes (e.g. PyMuPDF rendered page).
        prompt:
            Extraction prompt (e.g. "Extract structured markdown").
        **kw:
            API-specific options (``max_tokens``, ``temperature``, etc).

        Returns
        -------
        str
            Markdown text returned by the model (already stripped).

        Raises
        ------
        RuntimeError
            When all keys fail after retries, or when the response
            shape is malformed.
        """
        if not image_png:
            raise ValueError("image_png must be non-empty bytes")

        # base64 encode image for the multimodal content block
        image_b64 = base64.b64encode(image_png).decode("ascii")
        payload: dict[str, Any] = {
            "model": self.MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}"
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        # 透传可选的 API-specific 选项 (max_tokens, temperature, ...)
        for key in (
            "max_tokens",
            "temperature",
            "top_p",
            "stream",
            "stop",
        ):
            if key in kw:
                payload[key] = kw[key]

        last_exc: Exception | None = None
        n = len(self._api_keys)
        for attempt in range(n):
            idx = self._pick_key()
            if idx is None:
                # 全部冷却中
                break
            key = self._api_keys[idx]
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as http:
                    resp = await http.post(
                        f"{self.BASE_URL}{self.CHAT_COMPLETIONS_PATH}",
                        headers={"Authorization": f"Bearer {key}"},
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                return self._extract_content(data)
            except Exception as exc:
                last_exc = exc
                self._mark_failed(idx)
                logger.warning(
                    "Qwen-VL key #%d/%d failed (attempt %d/%d): %s",
                    idx + 1,
                    n,
                    attempt + 1,
                    n,
                    _short_err(exc),
                )
                continue

        msg = (
            f"Qwen-VL vision request failed after trying {n} key(s): "
            f"{_short_err(last_exc) if last_exc else 'all keys in cooldown'}"
        )
        logger.error(msg)
        raise RuntimeError(msg) from last_exc

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _pick_key(self) -> int | None:
        """选择下一个可用 key (跳过冷却中的)."""
        now = time.time()
        with self._lock:
            n = len(self._api_keys)
            start = self._cursor
            for i in range(n):
                idx = (start + i) % n
                if now - self._fail_ts[idx] >= self.COOLDOWN_SECONDS:
                    return idx
        return None

    def _mark_failed(self, idx: int) -> None:
        """记录 key 失败时间戳 (开始冷却)."""
        with self._lock:
            self._fail_ts[idx] = time.time()

    def _extract_content(self, data: dict) -> str:
        """Extract the assistant text from a DashScope multimodal response.

        ``choices[0].message.content`` is normally a ``str`` but
        multimodal completions can return a list of typed blocks. We
        concatenate any ``text`` blocks.
        """
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.exception("Unexpected Qwen-VL response shape: %s", data)
            raise RuntimeError(
                f"Malformed Qwen-VL vision response: {exc}"
            ) from exc

        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            return " ".join(p for p in parts if p).strip()
        # Fallback: stringify whatever it is.
        return str(content or "").strip()

    @classmethod
    def _collect_keys(cls, settings: Settings) -> List[str]:
        """从 settings + 环境读所有可用的 key.

        优先级:
          1. ``settings.qwen_vl.api_keys`` (list, 已合并 .env + config)
          2. 如果没 list, 退化为单 key: ``settings.qwen_vl.api_key``
          3. 进一步 fallback 到 ``DASHSCOPE_API_KEY`` +
             ``DASHSCOPE_API_KEY_2`` / ``_3`` / ... 环境变量
        """
        keys = list(getattr(settings.qwen_vl, "api_keys", None) or [])
        if keys:
            return [k for k in keys if k]

        # 单 key fallback
        single = getattr(settings.qwen_vl, "api_key", None)
        if single and single != "REPLACE_ME":
            return [single]

        # 环境变量 fallback (跟 embedding_client 复用 DASHSCOPE_API_KEY)
        env_keys: List[str] = []
        main = os.getenv("DASHSCOPE_API_KEY", "").strip()
        if main:
            env_keys.append(main)
        for suffix in (2, 3, 4, 5, 6, 7, 8, 9, 10):
            extra = os.getenv(f"DASHSCOPE_API_KEY_{suffix}", "").strip()
            if extra:
                env_keys.append(extra)

        return env_keys


def _short_err(exc: Exception) -> str:
    """提取异常关键信息 (避免暴露完整堆栈/响应体)."""
    msg = str(exc)
    if len(msg) > 300:
        msg = msg[:300] + "..."
    return f"{type(exc).__name__}: {msg}"


__all__ = ["QwenVLClient"]