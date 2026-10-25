"""LLM provider abstraction, unified exceptions, request tracking and factory."""

import datetime
import logging
import threading
from functools import lru_cache
from typing import Literal, Protocol, runtime_checkable

from app.config import get_settings

logger = logging.getLogger(__name__)

TaskType = Literal["document", "query"]


class ProviderError(Exception):
    """Base error for all LLM provider interactions."""


class ProviderUnavailableError(ProviderError):
    """Transient failure: provider is unreachable, timed out or returned a 5xx status."""


class ProviderResponseError(ProviderError):
    """Permanent failure: provider rejected the request or returned an unusable payload."""


class RateLimitError(ProviderError):
    """Rate limit hit (HTTP 429) with optional retry-after hint."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class QuotaExhaustedError(ProviderError):
    """Daily or account quota exhausted."""


# Backwards-compatibility aliases
OllamaUnavailableError = ProviderUnavailableError
OllamaResponseError = ProviderResponseError


@runtime_checkable
class LLMClient(Protocol):
    """Interface implemented by all model providers."""

    async def describe_image(self, model: str, prompt: str, image_b64: str) -> str:
        """Ask a vision model about one base64 image and return its text reply."""
        ...

    async def embed(
        self, model: str, texts: list[str], task: TaskType = "document"
    ) -> list[list[float]]:
        """Embed texts and return one vector per input, in order."""
        ...

    async def list_models(self) -> list[str]:
        """Return the names of models available from the provider."""
        ...

    async def aclose(self) -> None:
        """Close the underlying HTTP client session."""
        ...


class DailyRequestTracker:
    """Thread-safe per-day request counter that resets at local midnight."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_date = datetime.datetime.now().astimezone().date()
        self._requests_today = 0

    def _check_rollover(self) -> bool:
        today = datetime.datetime.now().astimezone().date()
        if today != self._current_date:
            self._current_date = today
            self._requests_today = 0
            return True
        return False

    def increment(self) -> int:
        with self._lock:
            self._check_rollover()
            self._requests_today += 1
            return self._requests_today

    @property
    def requests_today(self) -> int:
        with self._lock:
            self._check_rollover()
            return self._requests_today

    def reset(self) -> None:
        with self._lock:
            self._current_date = datetime.datetime.now().astimezone().date()
            self._requests_today = 0


_daily_tracker = DailyRequestTracker()


def get_daily_tracker() -> DailyRequestTracker:
    """Return the singleton in-memory daily request tracker."""
    return _daily_tracker


@lru_cache
def get_llm_client() -> LLMClient:
    """Factory: pick the provider from config. Only place aware of provider selection."""
    settings = get_settings()
    provider = settings.llm_provider
    if provider == "gemini":
        from app.services.gemini_client import get_gemini_client

        return get_gemini_client()
    if provider == "ollama":
        from app.services.ollama_client import get_ollama_client

        return get_ollama_client()
    raise ValueError(f"Unknown LLM provider: {provider}")


async def close_llm_client() -> None:
    """Close any active client and clear cached client instances."""
    try:
        from app.services.gemini_client import close_gemini_client

        await close_gemini_client()
    except Exception:
        logger.debug("Gemini client close failed or not initialized")

    try:
        from app.services.ollama_client import close_ollama_client

        await close_ollama_client()
    except Exception:
        logger.debug("Ollama client close failed or not initialized")

    get_llm_client.cache_clear()
