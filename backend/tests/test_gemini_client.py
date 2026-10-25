"""Unit tests for GeminiClient using httpx.MockTransport."""

import json

import httpx
import pytest

from app.services.gemini_client import GeminiClient
from app.services.llm_client import (
    ProviderResponseError,
    ProviderUnavailableError,
    QuotaExhaustedError,
    RateLimitError,
)


@pytest.mark.asyncio
async def test_describe_image_success() -> None:
    expected_reply = "A screenshot of an invoice for 500 dollars"
    sent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        data = json.loads(request.content)
        assert "contents" in data
        parts = data["contents"][0]["parts"]
        assert parts[0]["text"] == "Describe this"
        assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
        assert parts[1]["inline_data"]["data"] == "base64data=="

        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": expected_reply}],
                        "role": "model",
                    }
                }
            ]
        }
        return httpx.Response(200, json=body)

    client = GeminiClient(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="test-key",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )

    result = await client.describe_image("gemma-4-26b-a4b-it", "Describe this", "base64data==")
    assert result == expected_reply
    assert len(sent_requests) == 1
    assert sent_requests[0].headers.get("x-goog-api-key") == "test-key"
    await client.aclose()


@pytest.mark.asyncio
async def test_429_rate_limit_with_retry_after() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "42.5"},
            json={"error": {"message": "Rate limit reached. Try again later."}},
        )

    client = GeminiClient(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="test-key",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RateLimitError) as exc_info:
        await client.describe_image("model", "prompt", "b64")
    assert exc_info.value.retry_after_seconds == 42.5
    await client.aclose()


@pytest.mark.asyncio
async def test_429_quota_exhausted() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "code": 429,
                    "message": "Resource exhausted. Daily quota exceeded.",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )

    client = GeminiClient(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="test-key",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(QuotaExhaustedError):
        await client.describe_image("model", "prompt", "b64")
    await client.aclose()


@pytest.mark.asyncio
async def test_401_does_not_leak_key() -> None:
    secret_key = "super_secret_api_key_12345"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "API key not valid. Please pass a valid API key."}},
        )

    client = GeminiClient(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key=secret_key,
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderResponseError) as exc_info:
        await client.describe_image("model", "prompt", "b64")

    error_str = str(exc_info.value)
    assert secret_key not in error_str
    assert "Invalid or unauthorized Gemini API key" in error_str
    await client.aclose()


@pytest.mark.asyncio
async def test_timeout_mapping() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Connection timed out")

    client = GeminiClient(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="test-key",
        timeout_seconds=1.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError):
        await client.describe_image("model", "prompt", "b64")
    await client.aclose()


@pytest.mark.asyncio
async def test_embedding_batch_and_payload_shape() -> None:
    sent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        data = json.loads(request.content)
        assert "requests" in data
        assert len(data["requests"]) == 2
        req0 = data["requests"][0]
        assert req0["model"] == "models/gemini-embedding-001"
        assert req0["taskType"] == "RETRIEVAL_DOCUMENT"
        assert req0["content"]["parts"][0]["text"] == "Doc 1"
        assert req0["outputDimensionality"] == 4

        body = {
            "embeddings": [
                {"values": [0.1, 0.2, 0.3, 0.4]},
                {"values": [0.5, 0.6, 0.7, 0.8]},
            ]
        }
        return httpx.Response(200, json=body)

    client = GeminiClient(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="test-key",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )

    vectors = await client.embed(
        "gemini-embedding-001", ["Doc 1", "Doc 2"], task="document"
    )
    assert len(vectors) == 2
    assert vectors[0] == [0.1, 0.2, 0.3, 0.4]
    assert vectors[1] == [0.5, 0.6, 0.7, 0.8]
    await client.aclose()


@pytest.mark.asyncio
async def test_embedding_query_task_type() -> None:
    sent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        data = json.loads(request.content)
        assert data["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
        body = {"embeddings": [{"values": [0.9, 0.8, 0.7, 0.6]}]}
        return httpx.Response(200, json=body)

    client = GeminiClient(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="test-key",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )

    vectors = await client.embed("gemini-embedding-001", ["Search query"], task="query")
    assert len(vectors) == 1
    assert vectors[0] == [0.9, 0.8, 0.7, 0.6]
    await client.aclose()


@pytest.mark.asyncio
async def test_list_models_returns_both_forms() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "models/gemma-4-26b-a4b-it"},
                    {"name": "models/gemini-embedding-001"},
                ]
            },
        )

    client = GeminiClient(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="test-key",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )

    models = await client.list_models()
    assert "models/gemma-4-26b-a4b-it" in models
    assert "gemma-4-26b-a4b-it" in models
    await client.aclose()
