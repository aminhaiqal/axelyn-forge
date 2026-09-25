"""Small SQLite repository for public service requests."""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import ServiceRequestAccepted, ServiceRequestCreate


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
