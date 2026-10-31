"""Model providers. Gauntlet talks to any OpenAI-compatible chat endpoint:
the LLM Gateway, vLLM, a hosted API, or the bundled mock server used in CI.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


class ProviderError(RuntimeError):
    """Raised when a provider call fails after retries."""


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


class Provider(Protocol):
    def complete(
        self,
        model: str,
        messages: Sequence[Mapping[str, str]],
        params: Mapping[str, Any],
    ) -> Completion: ...


class OpenAICompatibleProvider:
    """Minimal client for ``POST {base_url}/chat/completions``.

    The API key is read from ``GAUNTLET_API_KEY`` unless passed explicitly and is
    never logged or included in error messages.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        backoff_s: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        key = api_key if api_key is not None else os.environ.get("GAUNTLET_API_KEY", "")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self._client = client or httpx.Client(timeout=timeout_s, headers=headers)
        self._max_retries = max_retries
        self._backoff_s = backoff_s

    def close(self) -> None:
        self._client.close()

    def complete(
        self,
        model: str,
        messages: Sequence[Mapping[str, str]],
        params: Mapping[str, Any],
    ) -> Completion:
        body: dict[str, Any] = {"model": model, "messages": list(messages)}
        for key in ("temperature", "max_tokens", "top_p", "seed"):
            if key in params:
                body[key] = params[key]

        last_error = "no attempt made"
        for attempt in range(self._max_retries + 1):
            started = time.perf_counter()
            try:
                resp = self._client.post(self._url, json=body)
            except httpx.TransportError as exc:
                last_error = f"transport error: {type(exc).__name__}"
            else:
                latency_ms = (time.perf_counter() - started) * 1000
                if resp.status_code == 200:
                    return _parse_completion(resp.json(), latency_ms)
                last_error = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRYABLE_STATUS:
                    break
            if attempt < self._max_retries:
                time.sleep(self._backoff_s * (2**attempt))
        raise ProviderError(f"{model}: {last_error}")


def _parse_completion(data: Mapping[str, Any], latency_ms: float) -> Completion:
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("malformed completion response") from exc
    usage = data.get("usage") or {}
    return Completion(
        text=str(text),
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        latency_ms=latency_ms,
    )
