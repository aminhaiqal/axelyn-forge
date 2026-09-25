"""Small SQLite repository for public service requests and Forge briefs."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    ForgeBriefAccepted,
    ForgeBriefAnalysis,
    ForgeBriefCreate,
    ServiceRequestAccepted,
    ServiceRequestCreate,
)


class ServiceRequestStore:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS service_requests (
                    id TEXT PRIMARY KEY,
                    service_id TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    company TEXT,
                    project_summary TEXT NOT NULL,
                    job_posting_url TEXT,
                    timeline TEXT,
                    consented_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS forge_briefs (
                    id TEXT PRIMARY KEY,
                    target_role TEXT NOT NULL,
                    company TEXT,
                    job_description TEXT NOT NULL,
                    career_evidence TEXT NOT NULL,
                    outputs_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    consented_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            forge_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(forge_briefs)")
            }
            if "user_id" not in forge_columns:
                connection.execute("ALTER TABLE forge_briefs ADD COLUMN user_id TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS forge_briefs_user_id_created_at "
                "ON forge_briefs (user_id, created_at DESC)"
            )

    def ping(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def create(self, payload: ServiceRequestCreate) -> ServiceRequestAccepted:
        request_id = "req_" + uuid.uuid4().hex
        created_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO service_requests (
                    id,
                    service_id,
                    full_name,
                    email,
                    company,
                    project_summary,
                    job_posting_url,
                    timeline,
                    consented_at,
                    status,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    payload.service_id,
                    payload.full_name,
                    str(payload.email),
                    payload.company,
                    payload.project_summary,
                    str(payload.job_posting_url) if payload.job_posting_url else None,
                    payload.timeline,
                    created_at,
                    "received",
                    created_at,
                ),
            )
        return ServiceRequestAccepted(
            id=request_id,
            service_id=payload.service_id,
            status="received",
            created_at=created_at,
            message="Your request is in. We will review the brief and reply by email.",
        )

    def create_forge_brief(
        self,
        payload: ForgeBriefCreate,
        analysis: ForgeBriefAnalysis,
        user_id: str,
    ) -> ForgeBriefAccepted:
        brief_id = "frg_" + uuid.uuid4().hex
        created_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO forge_briefs (
                    id,
                    user_id,
                    target_role,
                    company,
                    job_description,
                    career_evidence,
                    outputs_json,
                    analysis_json,
                    consented_at,
                    status,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    brief_id,
                    user_id,
                    payload.target_role,
                    payload.company,
                    payload.job_description,
                    payload.career_evidence,
                    json.dumps(payload.outputs),
                    json.dumps(analysis.model_dump()),
                    created_at,
                    "ready",
                    created_at,
                ),
            )
        return ForgeBriefAccepted(
            id=brief_id,
            status="ready",
            created_at=created_at,
            target_role=payload.target_role,
            company=payload.company,
            outputs=payload.outputs,
            **analysis.model_dump(),
        )
