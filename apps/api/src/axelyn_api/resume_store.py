"""SQLite metadata repository with user-scoped resume access."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class ResumeStore:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS resume_sources (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    target_role TEXT,
                    original_filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    original_object_key TEXT NOT NULL,
                    draft_object_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    warning TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS resume_sources_owner_created
                    ON resume_sources (user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS resume_variants (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    target_role TEXT,
                    normalized_object_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (user_id, source_id),
                    FOREIGN KEY (source_id) REFERENCES resume_sources(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS resume_variants_owner_created
                    ON resume_variants (user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS generated_documents (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    variant_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    template_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (variant_id) REFERENCES resume_variants(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS generated_documents_owner_created
                    ON generated_documents (user_id, created_at DESC);
                """
            )

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def create_source(
        self,
        *,
        source_id: str,
        user_id: str,
        display_name: str,
        target_role: str | None,
        original_filename: str,
        media_type: str,
        byte_size: int,
        sha256: str,
        original_object_key: str,
        draft_object_key: str,
        status: str,
        warning: str | None,
    ) -> dict[str, Any]:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO resume_sources (
                    id, user_id, display_name, target_role, original_filename,
                    media_type, byte_size, sha256, original_object_key,
                    draft_object_key, status, warning, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    user_id,
                    display_name,
                    target_role,
                    original_filename,
                    media_type,
                    byte_size,
                    sha256,
                    original_object_key,
                    draft_object_key,
                    status,
                    warning,
                    now,
                    now,
                ),
            )
        source = self.get_source(user_id, source_id)
        assert source is not None
        return source

    def list_sources(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM resume_sources
                WHERE user_id = ?
                ORDER BY updated_at DESC, created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_source(self, user_id: str, source_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM resume_sources WHERE id = ? AND user_id = ?",
                (source_id, user_id),
            ).fetchone()
        return self._dict(row)

    def update_source(
        self,
        *,
        user_id: str,
        source_id: str,
        display_name: str,
        target_role: str | None,
        draft_object_key: str,
        status: str,
        warning: str | None,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE resume_sources
                SET display_name = ?, target_role = ?, draft_object_key = ?,
                    status = ?, warning = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    display_name,
                    target_role,
                    draft_object_key,
                    status,
                    warning,
                    _now(),
                    source_id,
                    user_id,
                ),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_source(user_id, source_id)

    def accept_source(
        self,
        *,
        user_id: str,
        source_id: str,
        name: str,
        target_role: str | None,
        normalized_object_key: str,
    ) -> dict[str, Any] | None:
        source = self.get_source(user_id, source_id)
        if source is None:
            return None
        now = _now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, created_at FROM resume_variants
                WHERE source_id = ? AND user_id = ?
                """,
                (source_id, user_id),
            ).fetchone()
            if row is None:
                variant_id = _identifier("rsv")
                created_at = now
                connection.execute(
                    """
                    INSERT INTO resume_variants (
                        id, user_id, source_id, name, target_role,
                        normalized_object_key, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'ready', ?, ?)
                    """,
                    (
                        variant_id,
                        user_id,
                        source_id,
                        name,
                        target_role,
                        normalized_object_key,
                        created_at,
                        now,
                    ),
                )
            else:
                variant_id = str(row["id"])
                connection.execute(
                    """
                    UPDATE resume_variants
                    SET name = ?, target_role = ?, normalized_object_key = ?,
                        status = 'ready', updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (
                        name,
                        target_role,
                        normalized_object_key,
                        now,
                        variant_id,
                        user_id,
                    ),
                )
            connection.execute(
                """
                UPDATE resume_sources
                SET status = 'ready', updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, source_id, user_id),
            )
        return self.get_variant(user_id, variant_id)

    def list_variants(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM resume_variants
                WHERE user_id = ?
                ORDER BY updated_at DESC, created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_variant(self, user_id: str, variant_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM resume_variants WHERE id = ? AND user_id = ?",
                (variant_id, user_id),
            ).fetchone()
        return self._dict(row)

    def create_document(
        self,
        *,
        user_id: str,
        variant_id: str,
        filename: str,
        media_type: str,
        object_key: str,
        template_id: str,
        template_version: str,
    ) -> dict[str, Any] | None:
        if self.get_variant(user_id, variant_id) is None:
            return None
        document_id = _identifier("doc")
        created_at = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO generated_documents (
                    id, user_id, variant_id, filename, media_type, object_key,
                    template_id, template_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    user_id,
                    variant_id,
                    filename,
                    media_type,
                    object_key,
                    template_id,
                    template_version,
                    created_at,
                ),
            )
        return self.get_document(user_id, document_id)

    def get_document(self, user_id: str, document_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM generated_documents WHERE id = ? AND user_id = ?",
                (document_id, user_id),
            ).fetchone()
        return self._dict(row)

    def source_object_keys(self, user_id: str, source_id: str) -> list[str] | None:
        source = self.get_source(user_id, source_id)
        if source is None:
            return None
        with self._connect() as connection:
            document_rows = connection.execute(
                """
                SELECT object_key FROM generated_documents
                WHERE user_id = ? AND variant_id IN (
                    SELECT id FROM resume_variants
                    WHERE user_id = ? AND source_id = ?
                )
                """,
                (user_id, user_id, source_id),
            ).fetchall()
            variant_rows = connection.execute(
                """
                SELECT normalized_object_key FROM resume_variants
                WHERE user_id = ? AND source_id = ?
                """,
                (user_id, source_id),
            ).fetchall()
        return [
            str(source["original_object_key"]),
            str(source["draft_object_key"]),
            *(str(row["normalized_object_key"]) for row in variant_rows),
            *(str(row["object_key"]) for row in document_rows),
        ]

    def delete_source(self, user_id: str, source_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM resume_sources WHERE id = ? AND user_id = ?",
                (source_id, user_id),
            )
        return cursor.rowcount > 0
