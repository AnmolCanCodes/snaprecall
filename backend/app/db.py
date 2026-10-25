"""SQLite access: connections, schema creation and crash recovery."""

import logging
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import sqlite_vec

from app.config import get_settings

logger = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 5000

_embedding_mismatch: str | None = None

_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    sha256 TEXT,
    size_bytes INTEGER,
    mtime REAL,
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    summary TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    app_type TEXT NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    visible_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    indexed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_images_status ON images(status);
CREATE INDEX IF NOT EXISTS idx_images_sha256 ON images(sha256);
CREATE INDEX IF NOT EXISTS idx_images_mtime ON images(mtime);

CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
    filename, summary, tags, app_type, ocr_text, visible_text,
    content='images',
    content_rowid='id',
    tokenize = 'unicode61 remove_diacritics 0'
);
"""

_VEC_TABLE_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS vec_images USING vec0(embedding float[{dim}])"
)

_TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS images_ai AFTER INSERT ON images BEGIN
    INSERT INTO images_fts(rowid, filename, summary, tags, app_type, ocr_text, visible_text)
    VALUES (new.id, new.filename, new.summary, new.tags, new.app_type, new.ocr_text,
            new.visible_text);
END;

CREATE TRIGGER IF NOT EXISTS images_ad AFTER DELETE ON images BEGIN
    INSERT INTO images_fts(images_fts, rowid, filename, summary, tags, app_type, ocr_text,
                           visible_text)
    VALUES ('delete', old.id, old.filename, old.summary, old.tags, old.app_type, old.ocr_text,
            old.visible_text);
    DELETE FROM vec_images WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS images_au
AFTER UPDATE OF filename, summary, tags, app_type, ocr_text, visible_text ON images BEGIN
    INSERT INTO images_fts(images_fts, rowid, filename, summary, tags, app_type, ocr_text,
                           visible_text)
    VALUES ('delete', old.id, old.filename, old.summary, old.tags, old.app_type, old.ocr_text,
            old.visible_text);
    INSERT INTO images_fts(rowid, filename, summary, tags, app_type, ocr_text, visible_text)
    VALUES (new.id, new.filename, new.summary, new.tags, new.app_type, new.ocr_text,
            new.visible_text);
END;
"""


class VectorExtensionError(RuntimeError):
    """Raised when the sqlite-vec extension cannot be loaded."""


def get_embedding_mismatch() -> str | None:
    """Return the mismatch reason if startup detected an embedding mismatch."""
    return _embedding_mismatch


def has_embedding_mismatch() -> bool:
    """Return True if an embedding model or dimension mismatch was detected."""
    return _embedding_mismatch is not None


def _load_vector_extension(conn: sqlite3.Connection) -> None:
    """Load sqlite-vec into a connection, then disable extension loading again."""
    if not hasattr(conn, "enable_load_extension"):
        raise VectorExtensionError(
            "This Python build has no loadable SQLite extension support. "
            "Use the python.org or Homebrew Python on macOS."
        )
    try:
        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
    except sqlite3.OperationalError as exc:
        raise VectorExtensionError(f"Could not load the sqlite-vec extension: {exc}") from exc


def connect() -> sqlite3.Connection:
    """Open a new connection with sqlite-vec loaded and project pragmas applied.

    The connection runs in autocommit mode; use transaction() for atomic groups.
    Connections must not be shared across threads.
    """
    conn = sqlite3.connect(
        get_settings().database_path,
        isolation_level=None,
        timeout=BUSY_TIMEOUT_MS / 1000,
    )
    try:
        conn.row_factory = sqlite3.Row
        _load_vector_extension(conn)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        conn.close()
        raise
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """Yield a fresh connection and close it on exit."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside BEGIN IMMEDIATE, committing on success and rolling back on error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def reset_stuck_processing(conn: sqlite3.Connection) -> int:
    """Return rows left in status=processing by a crash to pending and report the count."""
    cursor = conn.execute("UPDATE images SET status = 'pending' WHERE status = 'processing'")
    return cursor.rowcount


def init_db() -> None:
    """Create the data directory, meta table, schema, and verify embedding configuration."""
    global _embedding_mismatch
    _embedding_mismatch = None

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        conn.executescript(_TABLES_SQL)

        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key IN ('embedding_model', 'embedding_dim')"
        ).fetchall()
        meta_dict = {row["key"]: row["value"] for row in rows}

        if "embedding_model" not in meta_dict or "embedding_dim" not in meta_dict:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('embedding_model', ?)",
                (settings.embedding_model,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('embedding_dim', ?)",
                (str(settings.embedding_dim),),
            )
            conn.execute(_VEC_TABLE_SQL.format(dim=settings.embedding_dim))
        else:
            stored_model = meta_dict["embedding_model"]
            stored_dim = int(meta_dict["embedding_dim"])
            if stored_model != settings.embedding_model or stored_dim != settings.embedding_dim:
                _embedding_mismatch = (
                    f"embedding_mismatch: stored '{stored_model}' ({stored_dim}d) differs "
                    f"from configured '{settings.embedding_model}' ({settings.embedding_dim}d)"
                )
                logger.error(
                    "Embedding mismatch detected: db has %s (%dd) vs config %s (%dd). "
                    "Refusing to index until the database is deleted.",
                    stored_model,
                    stored_dim,
                    settings.embedding_model,
                    settings.embedding_dim,
                )
            else:
                conn.execute(_VEC_TABLE_SQL.format(dim=settings.embedding_dim))

        conn.executescript(_TRIGGERS_SQL)
        recovered = reset_stuck_processing(conn)

    if recovered:
        logger.info("Reset %d interrupted image(s) back to pending", recovered)
    logger.info("Database ready at %s", settings.database_path)


def upsert_vector(conn: sqlite3.Connection, image_id: int, vector: Sequence[float]) -> None:
    """Store or replace the embedding for an image (delete then insert, as vec0 requires)."""
    conn.execute("DELETE FROM vec_images WHERE rowid = ?", (image_id,))
    conn.execute(
        "INSERT INTO vec_images(rowid, embedding) VALUES (?, ?)",
        (image_id, sqlite_vec.serialize_float32(list(vector))),
    )


def copy_vector(conn: sqlite3.Connection, source_id: int, target_id: int) -> bool:
    """Copy one image's embedding to another; return False when the source has none."""
    row = conn.execute(
        "SELECT embedding FROM vec_images WHERE rowid = ?", (source_id,)
    ).fetchone()
    if row is None:
        return False
    conn.execute("DELETE FROM vec_images WHERE rowid = ?", (target_id,))
    conn.execute(
        "INSERT INTO vec_images(rowid, embedding) VALUES (?, ?)", (target_id, row["embedding"])
    )
    return True