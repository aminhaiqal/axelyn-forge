"""Transactional SQLite persistence for verified candidate-context chunks."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple, Union

from .context_selection import ContextChunk, parse_markdown_context
from .errors import ContextStoreError

PathLike = Union[str, Path]
CONTEXT_DB_SCHEMA_VERSION = "1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS context_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_documents (
    source TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL,
    content_length INTEGER NOT NULL CHECK (content_length >= 0)
);

CREATE TABLE IF NOT EXISTS context_chunks (
    chunk_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    ordinal INTEGER NOT NULL UNIQUE CHECK (ordinal >= 0),
    title TEXT NOT NULL,
    heading_path_json TEXT NOT NULL,
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    FOREIGN KEY (source) REFERENCES context_documents(source) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS context_chunks_source_idx
ON context_chunks(source, ordinal);
"""


@dataclass(frozen=True)
class ContextIndexReport:
    database: Path
    documents: int
    chunks: int


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_utf8(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContextStoreError(f"Could not read candidate context file {path}: {exc}") from exc
    if not value.strip():
        raise ContextStoreError(f"Candidate context file is empty: {path}")
    return value


def read_context_source(path: PathLike) -> Tuple[List[Tuple[str, str]], List[ContextChunk]]:
    """Read a Markdown file/directory and produce source-aware deterministic chunks."""
    source = Path(path)
    if source.is_file():
        documents = [(source.name, _read_utf8(source))]
    elif source.is_dir():
        files = sorted(item for item in source.rglob("*.md") if item.is_file())
        if not files:
            raise ContextStoreError(
                f"Candidate context directory contains no Markdown files: {source}"
            )
        documents = [(item.relative_to(source).as_posix(), _read_utf8(item)) for item in files]
    else:
        raise ContextStoreError(f"Candidate context path does not exist: {source}")

    chunks: List[ContextChunk] = []
    for document_source, content in documents:
        chunks.extend(parse_markdown_context(content, source=document_source))
    if not chunks:
        raise ContextStoreError(f"Candidate context contains no indexable chunks: {source}")
    return documents, chunks


class SQLiteContextStore:
    def __init__(self, database: PathLike):
        self.database = Path(database)

    def _connect(self, *, create: bool) -> sqlite3.Connection:
        if not create and not self.database.is_file():
            raise ContextStoreError(f"Context database does not exist: {self.database}")
        if self.database.exists() and not self.database.is_file():
            raise ContextStoreError(f"Context database path is not a file: {self.database}")
        if create:
            try:
                self.database.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ContextStoreError(
                    f"Could not create context database directory {self.database.parent}: {exc}"
                ) from exc
        try:
            connection = sqlite3.connect(str(self.database), timeout=10)
        except sqlite3.Error as exc:
            raise ContextStoreError(f"Could not open context database {self.database}: {exc}") from exc
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            "INSERT OR IGNORE INTO context_meta(key, value) VALUES (?, ?)",
            ("schema_version", CONTEXT_DB_SCHEMA_VERSION),
        )
        row = connection.execute(
            "SELECT value FROM context_meta WHERE key = ?", ("schema_version",)
        ).fetchone()
        if row is None or row["value"] != CONTEXT_DB_SCHEMA_VERSION:
            actual = None if row is None else row["value"]
            raise ContextStoreError(
                f"Unsupported context database schema version {actual!r}; "
                f"expected {CONTEXT_DB_SCHEMA_VERSION}"
            )

    def replace(self, documents: Sequence[Tuple[str, str]], chunks: Sequence[ContextChunk]) -> ContextIndexReport:
        """Atomically replace the index with a newly parsed context snapshot."""
        connection = self._connect(create=True)
        try:
            with connection:
                self._initialize(connection)
                connection.execute("DELETE FROM context_chunks")
                connection.execute("DELETE FROM context_documents")
                connection.executemany(
                    """
                    INSERT INTO context_documents(source, content_sha256, content_length)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (source, _sha256(content), len(content))
                        for source, content in documents
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO context_chunks(
                        chunk_id,
                        source,
                        ordinal,
                        title,
                        heading_path_json,
                        content,
                        content_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            chunk.chunk_id,
                            chunk.source,
                            ordinal,
                            chunk.title,
                            json.dumps(list(chunk.heading_path), ensure_ascii=False),
                            chunk.content,
                            _sha256(chunk.content),
                        )
                        for ordinal, chunk in enumerate(chunks)
                    ],
                )
        except sqlite3.Error as exc:
            raise ContextStoreError(
                f"Could not update context database {self.database}: {exc}"
            ) from exc
        finally:
            connection.close()
        return ContextIndexReport(
            database=self.database,
            documents=len(documents),
            chunks=len(chunks),
        )

    def load_chunks(self) -> List[ContextChunk]:
        connection = self._connect(create=False)
        try:
            self._initialize(connection)
            rows = connection.execute(
                """
                SELECT chunk_id, source, title, heading_path_json, content
                FROM context_chunks
                ORDER BY ordinal
                """
            ).fetchall()
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise ContextStoreError(
                f"Could not read context database {self.database}: {exc}"
            ) from exc
        finally:
            connection.close()

        chunks = []
        for row in rows:
            try:
                heading_path = json.loads(row["heading_path_json"])
            except json.JSONDecodeError as exc:
                raise ContextStoreError(
                    f"Invalid heading path for context chunk '{row['chunk_id']}': {exc}"
                ) from exc
            if not isinstance(heading_path, list) or not all(
                isinstance(item, str) for item in heading_path
            ):
                raise ContextStoreError(
                    f"Invalid heading path for context chunk '{row['chunk_id']}'"
                )
            chunks.append(
                ContextChunk(
                    chunk_id=row["chunk_id"],
                    source=row["source"],
                    title=row["title"],
                    heading_path=tuple(heading_path),
                    content=row["content"],
                )
            )
        if not chunks:
            raise ContextStoreError(f"Context database contains no chunks: {self.database}")
        return chunks

    def document_count(self) -> int:
        connection = self._connect(create=False)
        try:
            self._initialize(connection)
            row = connection.execute("SELECT COUNT(*) AS count FROM context_documents").fetchone()
            return int(row["count"])
        except sqlite3.Error as exc:
            raise ContextStoreError(
                f"Could not inspect context database {self.database}: {exc}"
            ) from exc
        finally:
            connection.close()


def sync_context_database(context: PathLike, database: PathLike) -> ContextIndexReport:
    documents, chunks = read_context_source(context)
    return SQLiteContextStore(database).replace(documents, chunks)
