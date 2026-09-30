"""SQLite metadata repository with user-scoped resume access."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


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

                CREATE TABLE IF NOT EXISTS resume_source_artifacts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    object_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (user_id, source_id, kind),
                    FOREIGN KEY (source_id) REFERENCES resume_sources(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS resume_source_artifacts_owner_created
                    ON resume_source_artifacts (user_id, created_at DESC);

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

                CREATE TABLE IF NOT EXISTS job_matches (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_role TEXT NOT NULL,
                    company TEXT,
                    job_description_object_key TEXT NOT NULL,
                    resume_snapshot_object_key TEXT NOT NULL,
                    analysis_object_key TEXT NOT NULL,
                    match_state TEXT NOT NULL,
                    match_percentage INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES resume_sources(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS job_matches_owner_created
                    ON job_matches (user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS job_match_documents (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    match_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (match_id) REFERENCES job_matches(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS job_match_documents_owner_created
                    ON job_match_documents (user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS forge_ai_threads (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    match_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    baseline_score INTEGER NOT NULL,
                    current_score INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    memory_json TEXT NOT NULL,
                    memory_version INTEGER NOT NULL,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (user_id, match_id),
                    FOREIGN KEY (match_id) REFERENCES job_matches(id) ON DELETE CASCADE,
                    FOREIGN KEY (source_id) REFERENCES resume_sources(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS forge_ai_threads_owner_updated
                    ON forge_ai_threads (user_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS forge_ai_messages (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    claim_status TEXT NOT NULL,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (thread_id) REFERENCES forge_ai_threads(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS forge_ai_messages_thread_created
                    ON forge_ai_messages (user_id, thread_id, created_at);

                CREATE TABLE IF NOT EXISTS job_applications (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    job_title TEXT NOT NULL,
                    job_url TEXT,
                    location TEXT,
                    work_arrangement TEXT,
                    employment_type TEXT,
                    status TEXT NOT NULL,
                    applied_on TEXT,
                    next_action_on TEXT,
                    notes TEXT,
                    resume_source_id TEXT,
                    resume_variant_id TEXT,
                    resume_name TEXT NOT NULL,
                    resume_target_role TEXT,
                    resume_snapshot_object_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (resume_source_id) REFERENCES resume_sources(id) ON DELETE SET NULL,
                    FOREIGN KEY (resume_variant_id) REFERENCES resume_variants(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS job_applications_owner_updated
                    ON job_applications (user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS job_applications_owner_status
                    ON job_applications (user_id, status);

                CREATE TABLE IF NOT EXISTS job_application_interview_briefs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    application_id TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (user_id, application_id),
                    FOREIGN KEY (application_id) REFERENCES job_applications(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS interview_briefs_owner_updated
                    ON job_application_interview_briefs (user_id, updated_at DESC);
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

    def upsert_source_artifacts(
        self,
        *,
        user_id: str,
        source_id: str,
        artifacts: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Create or refresh a source's private normalized artifact bundle."""
        if self.get_source(user_id, source_id) is None:
            return None
        now = _now()
        with self._connect() as connection:
            for artifact in artifacts:
                connection.execute(
                    """
                    INSERT INTO resume_source_artifacts (
                        id, user_id, source_id, kind, filename, media_type,
                        byte_size, object_key, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (user_id, source_id, kind) DO UPDATE SET
                        filename = excluded.filename,
                        media_type = excluded.media_type,
                        byte_size = excluded.byte_size,
                        object_key = excluded.object_key,
                        updated_at = excluded.updated_at
                    """,
                    (
                        _identifier("rsa"),
                        user_id,
                        source_id,
                        artifact["kind"],
                        artifact["filename"],
                        artifact["media_type"],
                        artifact["byte_size"],
                        artifact["object_key"],
                        now,
                        now,
                    ),
                )
        return self.list_source_artifacts(user_id, source_id)

    def list_source_artifacts(
        self,
        user_id: str,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT * FROM resume_source_artifacts
            WHERE user_id = ?
        """
        parameters: tuple[str, ...] = (user_id,)
        if source_id is not None:
            query += " AND source_id = ?"
            parameters = (user_id, source_id)
        query += " ORDER BY created_at DESC, rowid DESC"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def get_source_artifact(
        self, user_id: str, artifact_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM resume_source_artifacts
                WHERE id = ? AND user_id = ?
                """,
                (artifact_id, user_id),
            ).fetchone()
        return self._dict(row)

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

    def create_job_application(
        self,
        *,
        application_id: str,
        user_id: str,
        company_name: str,
        job_title: str,
        job_url: str | None,
        location: str | None,
        work_arrangement: str | None,
        employment_type: str | None,
        status: str,
        applied_on: str | None,
        next_action_on: str | None,
        notes: str | None,
        resume_source_id: str,
        resume_variant_id: str | None,
        resume_name: str,
        resume_target_role: str | None,
        resume_snapshot_object_key: str,
    ) -> dict[str, Any]:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO job_applications (
                    id, user_id, company_name, job_title, job_url, location,
                    work_arrangement, employment_type, status, applied_on,
                    next_action_on, notes, resume_source_id, resume_variant_id,
                    resume_name, resume_target_role, resume_snapshot_object_key,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application_id,
                    user_id,
                    company_name,
                    job_title,
                    job_url,
                    location,
                    work_arrangement,
                    employment_type,
                    status,
                    applied_on,
                    next_action_on,
                    notes,
                    resume_source_id,
                    resume_variant_id,
                    resume_name,
                    resume_target_role,
                    resume_snapshot_object_key,
                    now,
                    now,
                ),
            )
        application = self.get_job_application(user_id, application_id)
        assert application is not None
        return application

    def list_job_applications(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM job_applications
                WHERE user_id = ?
                ORDER BY updated_at DESC, created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_job_application(
        self, user_id: str, application_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_applications WHERE id = ? AND user_id = ?",
                (application_id, user_id),
            ).fetchone()
        return self._dict(row)

    def update_job_application(
        self,
        *,
        user_id: str,
        application_id: str,
        company_name: str,
        job_title: str,
        job_url: str | None,
        location: str | None,
        work_arrangement: str | None,
        employment_type: str | None,
        status: str,
        applied_on: str | None,
        next_action_on: str | None,
        notes: str | None,
        resume_source_id: str | None,
        resume_variant_id: str | None,
        resume_name: str,
        resume_target_role: str | None,
        resume_snapshot_object_key: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE job_applications
                SET company_name = ?, job_title = ?, job_url = ?, location = ?,
                    work_arrangement = ?, employment_type = ?, status = ?,
                    applied_on = ?, next_action_on = ?, notes = ?,
                    resume_source_id = ?, resume_variant_id = ?, resume_name = ?,
                    resume_target_role = ?, resume_snapshot_object_key = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    company_name,
                    job_title,
                    job_url,
                    location,
                    work_arrangement,
                    employment_type,
                    status,
                    applied_on,
                    next_action_on,
                    notes,
                    resume_source_id,
                    resume_variant_id,
                    resume_name,
                    resume_target_role,
                    resume_snapshot_object_key,
                    _now(),
                    application_id,
                    user_id,
                ),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_job_application(user_id, application_id)

    def delete_job_application(self, user_id: str, application_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM job_applications WHERE id = ? AND user_id = ?",
                (application_id, user_id),
            )
        return cursor.rowcount > 0

    def get_interview_brief(
        self, user_id: str, application_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM job_application_interview_briefs
                WHERE user_id = ? AND application_id = ?
                """,
                (user_id, application_id),
            ).fetchone()
        return self._dict(row)

    def upsert_interview_brief(
        self,
        *,
        user_id: str,
        application_id: str,
        object_key: str,
        model: str,
    ) -> dict[str, Any] | None:
        if self.get_job_application(user_id, application_id) is None:
            return None
        now = _now()
        existing = self.get_interview_brief(user_id, application_id)
        with self._connect() as connection:
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO job_application_interview_briefs (
                        id, user_id, application_id, object_key, model,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _identifier("brief"),
                        user_id,
                        application_id,
                        object_key,
                        model,
                        now,
                        now,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE job_application_interview_briefs
                    SET object_key = ?, model = ?, updated_at = ?
                    WHERE user_id = ? AND application_id = ?
                    """,
                    (object_key, model, now, user_id, application_id),
                )
        return self.get_interview_brief(user_id, application_id)

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

    def create_documents(
        self,
        *,
        user_id: str,
        variant_id: str,
        documents: Sequence[dict[str, str]],
    ) -> list[dict[str, Any]] | None:
        """Record one generated bundle in a single metadata transaction."""
        if self.get_variant(user_id, variant_id) is None:
            return None
        created_at = _now()
        rows = [
            {
                "id": _identifier("doc"),
                "filename": document["filename"],
                "media_type": document["media_type"],
                "object_key": document["object_key"],
                "template_id": document["template_id"],
                "template_version": document["template_version"],
            }
            for document in documents
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO generated_documents (
                    id, user_id, variant_id, filename, media_type, object_key,
                    template_id, template_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["id"],
                        user_id,
                        variant_id,
                        row["filename"],
                        row["media_type"],
                        row["object_key"],
                        row["template_id"],
                        row["template_version"],
                        created_at,
                    )
                    for row in rows
                ],
            )
        return [
            {
                **row,
                "user_id": user_id,
                "variant_id": variant_id,
                "created_at": created_at,
            }
            for row in rows
        ]

    def list_documents(
        self,
        user_id: str,
        variant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT * FROM generated_documents
            WHERE user_id = ?
        """
        parameters: tuple[str, ...] = (user_id,)
        if variant_id is not None:
            query += " AND variant_id = ?"
            parameters = (user_id, variant_id)
        query += " ORDER BY created_at DESC, rowid DESC"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def get_document(self, user_id: str, document_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM generated_documents WHERE id = ? AND user_id = ?",
                (document_id, user_id),
            ).fetchone()
        return self._dict(row)

    def create_job_match(
        self,
        *,
        match_id: str,
        user_id: str,
        source_id: str,
        target_role: str,
        company: str | None,
        job_description_object_key: str,
        resume_snapshot_object_key: str,
        analysis_object_key: str,
        match_state: str,
        match_percentage: int,
    ) -> dict[str, Any] | None:
        if self.get_source(user_id, source_id) is None:
            return None
        created_at = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO job_matches (
                    id, user_id, source_id, target_role, company,
                    job_description_object_key, resume_snapshot_object_key,
                    analysis_object_key,
                    match_state, match_percentage, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    user_id,
                    source_id,
                    target_role,
                    company,
                    job_description_object_key,
                    resume_snapshot_object_key,
                    analysis_object_key,
                    match_state,
                    match_percentage,
                    created_at,
                ),
            )
        return self.get_job_match(user_id, match_id)

    def get_job_match(self, user_id: str, match_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_matches WHERE id = ? AND user_id = ?",
                (match_id, user_id),
            ).fetchone()
        return self._dict(row)

    def list_job_matches(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT matches.id, matches.source_id, sources.display_name AS resume_name,
                       matches.target_role, matches.company, matches.match_state,
                       matches.match_percentage, matches.created_at,
                       EXISTS (
                           SELECT 1 FROM job_match_documents AS documents
                           WHERE documents.user_id = matches.user_id
                             AND documents.match_id = matches.id
                       ) AS has_documents
                FROM job_matches AS matches
                JOIN resume_sources AS sources
                  ON sources.id = matches.source_id
                 AND sources.user_id = matches.user_id
                WHERE matches.user_id = ?
                ORDER BY matches.created_at DESC, matches.rowid DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_job_match_documents(
        self,
        *,
        user_id: str,
        match_id: str,
        documents: Sequence[dict[str, str]],
    ) -> list[dict[str, Any]] | None:
        if self.get_job_match(user_id, match_id) is None:
            return None
        created_at = _now()
        rows = [
            {
                "id": _identifier("jdoc"),
                "filename": document["filename"],
                "media_type": document["media_type"],
                "object_key": document["object_key"],
            }
            for document in documents
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO job_match_documents (
                    id, user_id, match_id, filename, media_type, object_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["id"], user_id, match_id, row["filename"],
                        row["media_type"], row["object_key"], created_at,
                    )
                    for row in rows
                ],
            )
        return [
            {**row, "user_id": user_id, "match_id": match_id, "created_at": created_at}
            for row in rows
        ]

    def get_job_match_document(
        self, user_id: str, document_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_match_documents WHERE id = ? AND user_id = ?",
                (document_id, user_id),
            ).fetchone()
        return self._dict(row)

    def list_job_match_documents(
        self, user_id: str, match_id: str
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM job_match_documents
                WHERE user_id = ? AND match_id = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (user_id, match_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_forge_ai_thread(
        self,
        *,
        user_id: str,
        match_id: str,
        source_id: str,
        title: str,
        baseline_score: int,
        memory_json: str,
        status: str,
    ) -> dict[str, Any] | None:
        existing = self.get_forge_ai_thread_for_match(user_id, match_id)
        if existing is not None:
            return existing
        if self.get_job_match(user_id, match_id) is None:
            return None
        thread_id = _identifier("fai")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO forge_ai_threads (
                    id, user_id, match_id, source_id, title,
                    baseline_score, current_score, status,
                    memory_json, memory_version, model, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, ?, ?)
                """,
                (
                    thread_id,
                    user_id,
                    match_id,
                    source_id,
                    title,
                    baseline_score,
                    baseline_score,
                    status,
                    memory_json,
                    now,
                    now,
                ),
            )
        return self.get_forge_ai_thread(user_id, thread_id)

    def get_forge_ai_thread(
        self, user_id: str, thread_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM forge_ai_threads WHERE id = ? AND user_id = ?",
                (thread_id, user_id),
            ).fetchone()
        return self._dict(row)

    def get_forge_ai_thread_for_match(
        self, user_id: str, match_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM forge_ai_threads WHERE match_id = ? AND user_id = ?",
                (match_id, user_id),
            ).fetchone()
        return self._dict(row)

    def list_forge_ai_threads(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT threads.*,
                       matches.target_role, matches.company,
                       sources.display_name AS resume_name,
                       (
                           SELECT COUNT(*) FROM forge_ai_messages AS messages
                           WHERE messages.user_id = threads.user_id
                             AND messages.thread_id = threads.id
                       ) AS message_count
                FROM forge_ai_threads AS threads
                JOIN job_matches AS matches
                  ON matches.id = threads.match_id
                 AND matches.user_id = threads.user_id
                JOIN resume_sources AS sources
                  ON sources.id = threads.source_id
                 AND sources.user_id = threads.user_id
                WHERE threads.user_id = ?
                ORDER BY threads.updated_at DESC, threads.rowid DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_forge_ai_message(
        self,
        *,
        user_id: str,
        thread_id: str,
        role: str,
        content: str,
        citations_json: str,
        claim_status: str,
        model: str | None,
    ) -> dict[str, Any] | None:
        if self.get_forge_ai_thread(user_id, thread_id) is None:
            return None
        message_id = _identifier("fmsg")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO forge_ai_messages (
                    id, user_id, thread_id, role, content, citations_json,
                    claim_status, model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    user_id,
                    thread_id,
                    role,
                    content,
                    citations_json,
                    claim_status,
                    model,
                    now,
                ),
            )
            connection.execute(
                "UPDATE forge_ai_threads SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, thread_id, user_id),
            )
        return self.get_forge_ai_message(user_id, message_id)

    def get_forge_ai_message(
        self, user_id: str, message_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM forge_ai_messages WHERE id = ? AND user_id = ?",
                (message_id, user_id),
            ).fetchone()
        return self._dict(row)

    def list_forge_ai_messages(
        self, user_id: str, thread_id: str
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM forge_ai_messages
                WHERE user_id = ? AND thread_id = ?
                ORDER BY created_at, rowid
                """,
                (user_id, thread_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_forge_ai_thread(
        self,
        *,
        user_id: str,
        thread_id: str,
        current_score: int,
        status: str,
        memory_json: str,
        model: str,
    ) -> dict[str, Any] | None:
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE forge_ai_threads
                SET current_score = ?, status = ?, memory_json = ?,
                    memory_version = memory_version + 1,
                    model = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    current_score,
                    status,
                    memory_json,
                    model,
                    now,
                    thread_id,
                    user_id,
                ),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_forge_ai_thread(user_id, thread_id)

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
            job_match_rows = connection.execute(
                """
                SELECT job_description_object_key, resume_snapshot_object_key,
                       analysis_object_key
                FROM job_matches WHERE user_id = ? AND source_id = ?
                """,
                (user_id, source_id),
            ).fetchall()
            job_document_rows = connection.execute(
                """
                SELECT object_key FROM job_match_documents
                WHERE user_id = ? AND match_id IN (
                    SELECT id FROM job_matches WHERE user_id = ? AND source_id = ?
                )
                """,
                (user_id, user_id, source_id),
            ).fetchall()
            source_artifact_rows = connection.execute(
                """
                SELECT object_key FROM resume_source_artifacts
                WHERE user_id = ? AND source_id = ?
                """,
                (user_id, source_id),
            ).fetchall()
        return [
            str(source["original_object_key"]),
            str(source["draft_object_key"]),
            *(str(row["normalized_object_key"]) for row in variant_rows),
            *(str(row["object_key"]) for row in source_artifact_rows),
            *(str(row["object_key"]) for row in document_rows),
            *(
                key
                for row in job_match_rows
                for key in (
                    str(row["job_description_object_key"]),
                    str(row["resume_snapshot_object_key"]),
                    str(row["analysis_object_key"]),
                )
            ),
            *(str(row["object_key"]) for row in job_document_rows),
        ]

    def delete_source(self, user_id: str, source_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM resume_sources WHERE id = ? AND user_id = ?",
                (source_id, user_id),
            )
        return cursor.rowcount > 0
