"""Async HTTP client for the local Ollama server."""

import logging
from functools import lru_cache
from typing import Any

import httpx

from app.config import get_settings
from app.services.llm_client import (
    ProviderResponseError,
    ProviderUnavailableError,
    TaskType,
    get_daily_tracker,
)

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 5.0
ERROR_BODY_LIMIT = 200

DOCUMENT_PREFIX = "title: none | text: "
QUERY_PREFIX = "task: search result | query: "


def _error_text(response: httpx.Response) -> str:
    """Extract a short error message from a failed Ollama response."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:ERROR_BODY_LIMIT]
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return body["error"][:ERROR_BODY_LIMIT]
    return response.text[:ERROR_BODY_LIMIT]


class OllamaClient:
    """Wrapper over the Ollama REST API implementing LLMClient."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
                trust_env=False,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a request and return the decoded JSON object, mapping failures to errors."""
        get_daily_tracker().increment()
        try:
            response = await self._get_client().request(method, path, json=payload)
        except httpx.TransportError as exc:
            raise ProviderUnavailableError(
                f"Cannot reach Ollama at {self._base_url} ({exc.__class__.__name__})"
            ) from exc
        if response.status_code >= 500:
            raise ProviderUnavailableError(
                f"Ollama returned HTTP {response.status_code}: {_error_text(response)}"
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"Ollama rejected the request (HTTP {response.status_code}): "
                f"{_error_text(response)}. If the model is missing, run 'ollama pull <model>'."
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError("Ollama returned a body that is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ProviderResponseError("Ollama returned an unexpected JSON shape")
        return data

    async def describe_image(self, model: str, prompt: str, image_b64: str) -> str:
        """Ask a vision model about one image and return its raw JSON text reply."""
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        data = await self._request("POST", "/api/chat", payload)
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderResponseError("Ollama chat response has no message content")
        return content

    # Backwards-compatible alias
    async def chat_with_image(self, model: str, prompt: str, image_b64: str) -> str:
        return await self.describe_image(model, prompt, image_b64)

    async def embed(
        self, model: str, texts: list[str], task: TaskType = "document"
    ) -> list[list[float]]:
        """Embed texts with EmbeddingGemma task prefixes and return vectors."""
        if not texts:
            return []
        prefix = DOCUMENT_PREFIX if task == "document" else QUERY_PREFIX
        prefixed_texts = [f"{prefix}{t}" for t in texts]

        data = await self._request(
            "POST", "/api/embed", {"model": model, "input": prefixed_texts}
        )
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ProviderResponseError(
                "Ollama embed response is missing a vector for every input"
            )
        try:
            return [[float(value) for value in vector] for vector in vectors]
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError(
                "Ollama embed response contains non numeric values"
            ) from exc

    async def list_models(self) -> list[str]:
        """Return the names of the models currently pulled in Ollama."""
        data = await self._request("GET", "/api/tags")
        models = data.get("models")
        if not isinstance(models, list):
            raise ProviderResponseError("Ollama tags response has no model list")
        return [item["name"] for item in models if isinstance(item, dict) and "name" in item]


@lru_cache
def get_ollama_client() -> OllamaClient:
    """Return the process wide Ollama client built from settings."""
    settings = get_settings()
    return OllamaClient(settings.ollama_base_url, settings.request_timeout_seconds)


async def close_ollama_client() -> None:
    """Close the shared client and reset the cache so a new one can be created."""
    await get_ollama_client().aclose()
    get_ollama_client.cache_clear()