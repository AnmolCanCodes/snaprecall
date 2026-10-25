"""Shared fixtures. The suite needs neither a real provider nor Tesseract."""

import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOPICS: dict[str, tuple[str, ...]] = {
    "payment": ("payment", "money", "paid", "rahul", "rupees"),
    "error": ("error", "docker", "permission"),
    "ticket": ("ticket", "flight"),
    "chat": ("chat", "message"),
}
DEFAULT_REPLY = {
    "summary": "Payment of 2500 rupees to Rahul",
    "tags": ["payment", "upi"],
    "app_type": "payment",
    "visible_text": "Rahul 2500",
}


class FakeLLMClient:
    """Stand-in for LLMClient with deterministic topic-based vectors."""

    def __init__(self) -> None:
        self.chat_calls = 0
        self.embed_calls = 0
        self.unavailable = False
        self.chat_reply = json.dumps(DEFAULT_REPLY)

    @staticmethod
    def _outage() -> None:
        from app.services.llm_client import ProviderUnavailableError

        raise ProviderUnavailableError("fake outage")

    async def describe_image(self, model: str, prompt: str, image_b64: str) -> str:
        self.chat_calls += 1
        if self.unavailable:
            self._outage()
        return self.chat_reply

    async def chat_with_image(self, model: str, prompt: str, image_b64: str) -> str:
        return await self.describe_image(model, prompt, image_b64)

    async def embed(
        self, model: str, texts: list[str], task: str = "document"
    ) -> list[list[float]]:
        self.embed_calls += 1
        if self.unavailable:
            self._outage()
        return [self._vector(text) for text in texts]

    async def list_models(self) -> list[str]:
        if self.unavailable:
            self._outage()
        return ["gemma3:4b", "embeddinggemma:latest", "gemini-embedding-001", "gemma-4-26b-a4b-it"]

    async def aclose(self) -> None:
        pass

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.lower()
        vector = [1.0 if any(w in lowered for w in words) else 0.0 for words in TOPICS.values()]
        return vector if any(vector) else [0.1, 0.1, 0.1, 0.1]


# Backwards compatibility alias for existing test suites
FakeOllama = FakeLLMClient


@pytest.fixture(autouse=True)
def shots_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point every setting at a throwaway directory and clear cached singletons."""
    from app.config import get_settings
    from app.services.gemini_client import get_gemini_client
    from app.services.llm_client import get_daily_tracker, get_llm_client
    from app.services.ollama_client import get_ollama_client

    shots = tmp_path / "shots"
    shots.mkdir()
    env = {
        "SCREENSHOT_DIR": str(shots),
        "DATA_DIR": str(tmp_path / "data"),
        "SCAN_RECURSIVE": "false",
        "WATCH_ENABLED": "false",
        "BACKFILL_ON_START": "false",
        "SUPPORTED_EXTENSIONS": "png,jpg,jpeg,webp",
        "THUMBNAIL_SIZE": "64",
        "LLM_PROVIDER": "ollama",
        "GEMINI_API_KEY": "",
        "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
        "REQUEST_TIMEOUT_SECONDS": "120",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "VISION_MODEL": "gemma3:4b",
        "EMBEDDING_MODEL": "embeddinggemma",
        "EMBEDDING_DIM": "4",
        "OCR_ENGINE": "none",
        "TESSERACT_CMD": "",
        "WORKER_THROTTLE_SECONDS": "0",
        "WORKER_MAX_RETRIES": "2",
        "DAILY_REQUEST_BUDGET": "0",
        "SEARCH_DEFAULT_LIMIT": "24",
        "SEARCH_CANDIDATES": "50",
        "RRF_K": "60",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    get_settings.cache_clear()
    get_llm_client.cache_clear()
    get_gemini_client.cache_clear()
    get_ollama_client.cache_clear()
    get_daily_tracker().reset()

    yield shots

    get_settings.cache_clear()
    get_llm_client.cache_clear()
    get_gemini_client.cache_clear()
    get_ollama_client.cache_clear()
    get_daily_tracker().reset()


@pytest.fixture
def db() -> None:
    """Create the schema in the temporary data directory."""
    from app.db import init_db

    init_db()


@pytest.fixture
def fake_ollama(monkeypatch: pytest.MonkeyPatch) -> FakeLLMClient:
    """Replace the LLM client everywhere it is looked up."""
    fake = FakeLLMClient()
    monkeypatch.setattr("app.services.llm_client.get_llm_client", lambda: fake)
    for module in ("app.services.vision", "app.services.embeddings", "app.api.health"):
        monkeypatch.setattr(f"{module}.get_llm_client", lambda: fake)
    return fake


@pytest.fixture
def make_png() -> Callable[..., Path]:
    """Return a factory that writes a tiny valid image."""

    def _make(path: Path, color: str = "white") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (48, 32), color).save(path, format="PNG")
        return path

    return _make


@pytest.fixture
def add_image(db: None) -> Callable[..., int]:
    """Return a factory that inserts an image row, optionally with a vector."""

    def _add(
        path: str,
        *,
        status: str = "pending",
        summary: str = "",
        ocr_text: str = "",
        tags: list[str] | None = None,
        app_type: str = "",
        sha256: str | None = None,
        vector: list[float] | None = None,
        indexed_at: str | None = None,
        mtime: float = 1.0,
    ) -> int:
        from app.db import connection, transaction, upsert_vector

        with connection() as conn, transaction(conn):
            cursor = conn.execute(
                "INSERT INTO images(path, filename, sha256, mtime, status, summary, tags, "
                "app_type, ocr_text, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    path,
                    Path(path).name,
                    sha256,
                    mtime,
                    status,
                    summary,
                    json.dumps(tags or []),
                    app_type,
                    ocr_text,
                    indexed_at,
                ),
            )
            image_id = int(cursor.lastrowid or 0)
            if vector is not None:
                upsert_vector(conn, image_id, vector)
        return image_id

    return _add


@pytest.fixture
def client(db: None) -> TestClient:
    """A test client without lifespan, so no worker or watcher is started."""
    from app.main import create_app

    return TestClient(create_app())