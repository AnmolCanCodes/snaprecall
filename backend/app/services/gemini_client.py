"""Async HTTP client for the Google Gemini REST API."""

import email.utils
import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import httpx

from app.config import get_settings
from app.services.llm_client import (
    ProviderResponseError,
    ProviderUnavailableError,
    QuotaExhaustedError,
    RateLimitError,
    TaskType,
    get_daily_tracker,
)

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 10.0
ERROR_BODY_LIMIT = 300
EMBEDDING_BATCH_SIZE = 16


def _clean_model_name(model: str) -> str:
    """Normalize model string to not include models/ prefix for URL paths."""
    return model.removeprefix("models/").strip()


def _full_model_name(model: str) -> str:
    """Normalize model string to include models/ prefix for payload bodies."""
    cleaned = _clean_model_name(model)
    return f"models/{cleaned}"


def _parse_retry_after(header_value: str | None) -> float | None:
    """Parse a Retry-After header into seconds as a float, or None."""
    if not header_value:
        return None
    val = header_value.strip()
    try:
        seconds = float(val)
        return max(0.0, seconds)
    except ValueError:
        pass

    try:
        dt = email.utils.parsedate_to_datetime(val)
        now = datetime.now(UTC)
        return max(0.0, (dt - now).total_seconds())
    except Exception:
        return None


def _is_quota_exhausted(body_text: str) -> bool:
    """Check if a 429 response body indicates daily or overall quota exhaustion."""
    lowered = body_text.lower()
    quota_terms = ("quota", "resource_exhausted", "daily", "per day", "exhausted", "free tier")
    matches = sum(1 for term in quota_terms if term in lowered)
    if "daily" in lowered or "per day" in lowered or "quota exhausted" in lowered:
        return True
    return matches >= 2


def _safe_error_detail(response: httpx.Response) -> str:
    """Extract error detail without exposing any potential secrets."""
    try:
        data = response.json()
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return error["message"][:ERROR_BODY_LIMIT]
    except Exception:
        pass
    return response.text[:ERROR_BODY_LIMIT]


class GeminiClient:
    """Client for Gemini generateContent, batchEmbedContents and model listing."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["x-goog-api-key"] = self._api_key
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers=headers,
                transport=self._transport,
                trust_env=False,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client session."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a request to Gemini REST API and map status codes and failures."""
        if not self._api_key:
            raise ProviderResponseError(
                "Gemini API key is not configured. Please set GEMINI_API_KEY in .env."
            )

        client = self._get_client()
        get_daily_tracker().increment()

        try:
            response = await client.request(method, path, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Gemini request timed out") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailableError(
                f"Cannot reach Gemini API ({exc.__class__.__name__})"
            ) from exc

        status = response.status_code
        if status in (401, 403):
            raise ProviderResponseError(
                "Invalid or unauthorized Gemini API key. Please check GEMINI_API_KEY in .env."
            )

        if status == 429:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            if _is_quota_exhausted(response.text):
                raise QuotaExhaustedError("Gemini daily request quota exhausted")
            raise RateLimitError("Gemini rate limit exceeded", retry_after_seconds=retry_after)

        if status >= 500:
            raise ProviderUnavailableError(
                f"Gemini returned HTTP {status}: {_safe_error_detail(response)}"
            )

        if status >= 400:
            raise ProviderResponseError(
                f"Gemini rejected the request (HTTP {status}): {_safe_error_detail(response)}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError("Gemini returned a body that is not valid JSON") from exc

        if not isinstance(data, dict):
            raise ProviderResponseError("Gemini returned an unexpected JSON structure")
        return data

    async def describe_image(self, model: str, prompt: str, image_b64: str) -> str:
        """Call generateContent with an inline JPEG image and user prompt."""
        cleaned_model = _clean_model_name(model)
        path = f"/models/{cleaned_model}:generateContent"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_b64,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
            },
        }

        data = await self._request("POST", path, payload)
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderResponseError("Gemini returned no candidates in response")

        first_candidate = candidates[0]
        if not isinstance(first_candidate, dict):
            raise ProviderResponseError("Gemini candidate is not a dictionary")

        content = first_candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list) or not parts:
            raise ProviderResponseError("Gemini candidate has no content parts")

        first_part = parts[0]
        text = first_part.get("text") if isinstance(first_part, dict) else None
        if not isinstance(text, str):
            raise ProviderResponseError("Gemini candidate part has no text field")

        return text

    async def _embed_batch(
        self, model: str, texts: list[str], task_type: str, output_dim: int
    ) -> list[list[float]]:
        cleaned_model = _clean_model_name(model)
        full_model = _full_model_name(model)
        path = f"/models/{cleaned_model}:batchEmbedContents"

        requests_list = [
            {
                "model": full_model,
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
                "outputDimensionality": output_dim,
            }
            for t in texts
        ]

        data = await self._request("POST", path, {"requests": requests_list})
        raw_embeddings = data.get("embeddings")
        if not isinstance(raw_embeddings, list) or len(raw_embeddings) != len(texts):
            raise ProviderResponseError("Gemini batch embed response length mismatch")

        results: list[list[float]] = []
        for item in raw_embeddings:
            if not isinstance(item, dict):
                raise ProviderResponseError("Gemini embedding element is not a dictionary")
            values = item.get("values")
            if not isinstance(values, list):
                raise ProviderResponseError("Gemini embedding has no values list")
            try:
                results.append([float(val) for val in values])
            except (TypeError, ValueError) as exc:
                raise ProviderResponseError(
                    "Gemini embedding contains non-numeric values"
                ) from exc

        return results

    async def embed(
        self, model: str, texts: list[str], task: TaskType = "document"
    ) -> list[list[float]]:
        """Embed texts using batchEmbedContents in batches up to 16."""
        if not texts:
            return []

        task_type = "RETRIEVAL_DOCUMENT" if task == "document" else "RETRIEVAL_QUERY"
        output_dim = get_settings().embedding_dim

        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            chunk = texts[i : i + EMBEDDING_BATCH_SIZE]
            chunk_vectors = await self._embed_batch(model, chunk, task_type, output_dim)
            all_vectors.extend(chunk_vectors)

        return all_vectors

    async def list_models(self) -> list[str]:
        """Return the names of models available from the Gemini API."""
        data = await self._request("GET", "/models")
        models = data.get("models")
        if not isinstance(models, list):
            raise ProviderResponseError("Gemini models response has no models list")

        names: list[str] = []
        for item in models:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                full_name = item["name"]
                names.append(full_name)
                cleaned = full_name.removeprefix("models/")
                if cleaned not in names:
                    names.append(cleaned)
        return names


@lru_cache
def get_gemini_client() -> GeminiClient:
    """Return the process wide Gemini client built from settings."""
    settings = get_settings()
    return GeminiClient(
        base_url=settings.gemini_base_url,
        api_key=settings.gemini_api_key,
        timeout_seconds=settings.request_timeout_seconds,
    )


async def close_gemini_client() -> None:
    """Close the shared Gemini client and reset the cache."""
    await get_gemini_client().aclose()
    get_gemini_client.cache_clear()
