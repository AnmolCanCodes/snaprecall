"""Application settings loaded from the .env file in the repository root."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_FILENAME = "snaprecall.db"
THUMBNAILS_DIRNAME = "thumbnails"


def _split_csv(value: object) -> object:
    """Split a comma separated string into trimmed, non-empty items."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """Typed view of every key defined in .env.example."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    # API
    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # Screenshots
    screenshot_dir: Path | None = None
    scan_recursive: bool = False
    watch_enabled: bool = True
    backfill_on_start: bool = True
    supported_extensions: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["png", "jpg", "jpeg", "webp"]
    )

    # Storage
    data_dir: Path = Path("./data")
    thumbnail_size: int = Field(default=360, ge=32)

    # Model provider
    llm_provider: Literal["gemini", "ollama"] = "gemini"

    # Gemini API (LLM_PROVIDER=gemini)
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    request_timeout_seconds: float = Field(default=120.0, gt=0)

    # Ollama (LLM_PROVIDER=ollama)
    ollama_base_url: str = "http://localhost:11434"

    # Models
    vision_model: str = "gemma-4-26b-a4b-it"
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = Field(default=768, ge=1)
    max_image_side: int = Field(default=1024, ge=64)

    # OCR
    ocr_engine: Literal["tesseract", "none"] = "none"
    ocr_langs: str = "eng+hin"
    tesseract_cmd: str | None = None

    # Worker
    worker_throttle_seconds: float = Field(default=6.0, ge=0)
    worker_max_retries: int = Field(default=3, ge=1)
    daily_request_budget: int = Field(default=0, ge=0)

    # Search
    search_default_limit: int = Field(default=24, ge=1, le=100)
    search_candidates: int = Field(default=50, ge=1)
    rrf_k: int = Field(default=60, ge=1)

    @field_validator("cors_origins", "supported_extensions", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("ocr_engine", mode="before")
    @classmethod
    def _lower_ocr_engine(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _lower_llm_provider(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def _clean_api_key(cls, value: object) -> str:
        return value.strip() if isinstance(value, str) else ""

    @field_validator("gemini_base_url", mode="before")
    @classmethod
    def _clean_gemini_base_url(cls, value: object) -> str:
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return "https://generativelanguage.googleapis.com/v1beta"

    @field_validator("screenshot_dir", "tesseract_cmd", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("supported_extensions")
    @classmethod
    def _normalize_extensions(cls, value: list[str]) -> list[str]:
        extensions = [item.lower().lstrip(".") for item in value]
        if not extensions:
            raise ValueError("SUPPORTED_EXTENSIONS must list at least one extension")
        return extensions

    @field_validator("screenshot_dir")
    @classmethod
    def _resolve_screenshot_dir(cls, value: Path | None) -> Path | None:
        return value.expanduser().resolve() if value is not None else None

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        path = value.expanduser()
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path.resolve()

    @property
    def database_path(self) -> Path:
        """Location of the SQLite database file."""
        return self.data_dir / DATABASE_FILENAME

    @property
    def thumbnails_dir(self) -> Path:
        """Directory that holds generated thumbnails."""
        return self.data_dir / THUMBNAILS_DIRNAME

    @property
    def supported_suffixes(self) -> frozenset[str]:
        """Supported file suffixes with a leading dot, lowercase."""
        return frozenset(f".{extension}" for extension in self.supported_extensions)


@lru_cache
def get_settings() -> Settings:
    """Return the process wide settings instance."""
    return Settings()