"""MiniMax chat-completion client (OpenAI-compatible async API).

支持多 key 轮询 / failover:
- 从 settings.chat.api_keys 读多个 key (兼容 .env 的 MINIMAX_API_KEY 单值或
  MINIMAX_API_KEY_2 / _3 / ... 多值)
- 每次 achat() 按 round-robin 选 key, 失败 (尤其 429 / 401) 时自动切下一个
- 客户端维护 key 池 + 失败计数, 冷却期内的 key 跳过
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Iterable, List, Mapping, Sequence

from openai import AsyncOpenAI

from app.config import Settings
from app.llm.base import ChatClient

logger = logging.getLogger(__name__)


class MiniMaxChatClient(ChatClient):
    """Async chat client for MiniMax's OpenAI-compatible endpoint.

    多 key 支持 (从环境):
        MINIMAX_API_KEY      # 优先 (主 key)
        MINIMAX_API_KEY_2    # 备用 1
        MINIMAX_API_KEY_3    # 备用 2
        ...
    settings.chat.api_keys 列表按上述顺序排列; 单 key 时退化为单 key 模式。
    """

    # 失败冷却: 同一 key 失败 N 秒内不再尝试 (默认 60s)
    COOLDOWN_SECONDS = 60

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.chat.base_url
        self._timeout = settings.chat.timeout
        self._model = settings.chat.model

        # 收集 keys: 优先 settings.chat.api_keys, 否则从环境读 MINIMAX_API_KEY + _2 + _3 ...
        keys = self._collect_keys(settings)
        if not keys:
            raise RuntimeError(
                "MiniMaxChatClient: 至少需要一个 MINIMAX_API_KEY"
            )

        # 为每个 key 创建独立 AsyncOpenAI 客户端
        self._clients: List[AsyncOpenAI] = [
            AsyncOpenAI(
                api_key=k,
                base_url=self._base_url,
                timeout=self._timeout,
                max_retries=0,  # 我们自己做 retry + 切 key
            )
            for k in keys
        ]
        # 每个 key 的失败时间戳 (epoch seconds); < COOLDOWN_SECONDS 时跳过
        self._fail_ts: List[float] = [0.0] * len(self._clients)
        self._lock = threading.Lock()
        # 上次用的 key 索引, round-robin 起点
        self._cursor = 0

        logger.info(
            "MiniMaxChatClient: loaded %d key(s) from base_url=%s",
            len(self._clients), self._base_url,
        )

    # -------- 公开 API --------

    @property
    def model(self) -> str:
        return self._model

    @property
    def raw_client(self) -> AsyncOpenAI:
        """返回当前 cursor 的 client (向后兼容)."""
        return self._clients[self._cursor]

    @property
    def key_count(self) -> int:
        return len(self._clients)

    async def achat(
        self,
        messages: Sequence[Mapping[str, str]],
        **kw: Any,
    ) -> str:
        """Send ``messages`` to MiniMax and return the assistant text reply.

        按 round-robin 顺序尝试可用 key; 遇 429 / 401 / 5xx 等可恢复错误时
        自动切下一个 key 重试, 直到全部失败。
        """
        if not messages:
            raise ValueError("messages must be a non-empty sequence")

        params: dict[str, Any] = {
            "model": self._model,
            "messages": list(messages),
        }
        for key in (
            "temperature", "top_p", "max_tokens", "stream",
            "stop", "presence_penalty", "frequency_penalty",
        ):
            if key in kw:
                params[key] = kw[key]

        last_exc: Exception | None = None
        n = len(self._clients)
        for attempt in range(n):
            idx = self._pick()
            if idx is None:
                # 全部冷却中
                break
            client = self._clients[idx]
            try:
                resp = await client.chat.completions.create(**params)
            except Exception as exc:
                last_exc = exc
                self._mark_failed(idx, exc)
                logger.warning(
                    "MiniMax key #%d/%d failed (attempt %d/%d): %s",
                    idx + 1, n, attempt + 1, n, _short_err(exc),
                )
                continue

            # 成功 -> 更新 cursor
            with self._lock:
                self._cursor = idx
            return self._extract_content(resp)

        # 所有 key 都失败
        msg = (
            f"MiniMax chat request failed after trying {n} key(s): "
            f"{_short_err(last_exc) if last_exc else 'all keys in cooldown'}"
        )
        logger.error(msg)
        raise RuntimeError(msg) from last_exc

    # -------- 内部 --------

    def _pick(self) -> int | None:
        """选择下一个可用 key (跳过冷却中的)"""
        import time
        now = time.time()
        with self._lock:
            n = len(self._clients)
            start = self._cursor
            for i in range(n):
                idx = (start + i) % n
                if now - self._fail_ts[idx] >= self.COOLDOWN_SECONDS:
                    return idx
        return None

    def _mark_failed(self, idx: int, exc: Exception) -> None:
        import time
        with self._lock:
            self._fail_ts[idx] = time.time()

    def _extract_content(self, resp: Any) -> str:
        try:
            choice = resp.choices[0]
            content = choice.message.content or ""
        except (AttributeError, IndexError, KeyError) as exc:
            logger.exception("Unexpected MiniMax response shape: %s", resp)
            raise RuntimeError(f"Malformed MiniMax chat response: {exc}") from exc
        return content.strip()

    @classmethod
    def _collect_keys(cls, settings: Settings) -> List[str]:
        """从 settings + 环境读所有可用的 key.

        优先级:
          1. settings.chat.api_keys (list, 已合并 .env + config)
          2. 如果没 list, 退化为单 key: settings.chat.api_key
        """
        # 优先用 list
        keys = getattr(settings.chat, "api_keys", None)
        if keys:
            return [k for k in keys if k]
        # fallback 单 key
        single = getattr(settings.chat, "api_key", None)
        if single:
            return [single]
        return []


def _short_err(exc: Exception) -> str:
    """提取异常关键信息 (避免暴露完整堆栈/响应体)."""
    msg = str(exc)
    if len(msg) > 300:
        msg = msg[:300] + "..."
    return f"{type(exc).__name__}: {msg}"