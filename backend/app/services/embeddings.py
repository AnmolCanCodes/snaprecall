"""Document and query embeddings via configured LLM provider."""

import logging
from dataclasses import dataclass

from app.config import get_settings
from app.services.llm_client import ProviderResponseError, get_llm_client

logger = logging.getLogger(__name__)

MAX_DOCUMENT_CHARS = 4000
EMBEDDING_BATCH_LIMIT = 16


@dataclass(frozen=True)
class DocumentRecord:
    """The text fields of one screenshot that feed the embedding and the index."""

    summary: str
    tags: list[str]
    app_type: str
    visible_text: str
    ocr_text: str


def build_document_text(record: DocumentRecord) -> str:
    """Combine the searchable fields, most informative first, within a safe length."""
    parts: list[str] = []
    if record.summary:
        parts.append(f"Summary: {record.summary}")
    if record.app_type:
        parts.append(f"Type: {record.app_type}")
    if record.tags:
        parts.append("Tags: " + ", ".join(record.tags))
    if record.visible_text:
        parts.append(f"Visible text: {record.visible_text}")
    if record.ocr_text:
        parts.append(f"OCR text: {record.ocr_text}")
    return "\n".join(parts)[:MAX_DOCUMENT_CHARS]


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed documents in batches of up to 16 and verify dimensions."""
    if not texts:
        return []

    settings = get_settings()
    client = get_llm_client()
    expected_dim = settings.embedding_dim
    results: list[list[float]] = []

    for i in range(0, len(texts), EMBEDDING_BATCH_LIMIT):
        chunk = texts[i : i + EMBEDDING_BATCH_LIMIT]
        vectors = await client.embed(settings.embedding_model, chunk, task="document")
        for vec in vectors:
            if len(vec) != expected_dim:
                raise ProviderResponseError(
                    f"Embedding model '{settings.embedding_model}' returned {len(vec)} dimensions "
                    f"but EMBEDDING_DIM is {expected_dim}. Set EMBEDDING_DIM={len(vec)} "
                    "in .env and delete the data directory so the index can be rebuilt."
                )
            results.append(vec)

    return results


async def embed_document(text: str) -> list[float]:
    """Embed document text and verify vector dimension."""
    vectors = await embed_documents([text])
    return vectors[0]


async def embed_query(text: str) -> list[float]:
    """Embed a search query with query task type and verify vector dimension."""
    settings = get_settings()
    client = get_llm_client()
    expected_dim = settings.embedding_dim

    vectors = await client.embed(settings.embedding_model, [text], task="query")
    if not vectors:
        raise ProviderResponseError("Provider returned no embedding vector for query")

    vector = vectors[0]
    if len(vector) != expected_dim:
        raise ProviderResponseError(
            f"Embedding model '{settings.embedding_model}' returned {len(vector)} dimensions "
            f"but EMBEDDING_DIM is {expected_dim}. Set EMBEDDING_DIM={len(vector)} "
            "in .env and delete the data directory so the index can be rebuilt."
        )
    return vector