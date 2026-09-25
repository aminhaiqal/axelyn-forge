"""Environment-backed API settings."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple


def _origins(value: str) -> Tuple[str, ...]:
    return tuple(origin.strip().rstrip("/") for origin in value.split(",") if origin.strip())


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    database_path: Path = Path(".state/forge.sqlite3")
    storage_path: Path = Path(".state/objects")
    storage_endpoint: Optional[str] = None
    storage_token: Optional[str] = None
    resume_template_path: Path = Path("templates/Axelyn_Standard_Resume_v1.docx")
    max_resume_bytes: int = 10 * 1024 * 1024
    max_resume_files: int = 5
    cors_origins: Tuple[str, ...] = (
        "http://localhost:4321",
        "http://localhost:8080",
    )
    clerk_secret_key: Optional[str] = None
    clerk_jwt_key: Optional[str] = None
    clerk_authorized_parties: Tuple[str, ...] = (
        "http://localhost:4321",
        "http://127.0.0.1:4321",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "https://forge.axelyn.com",
    )

    @classmethod
    def from_environ(
        cls,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "Settings":
        values = os.environ if environ is None else environ
        return cls(
            environment=values.get("FORGE_ENVIRONMENT", "development").strip()
            or "development",
            database_path=Path(
                values.get("FORGE_DATABASE", ".state/forge.sqlite3").strip()
                or ".state/forge.sqlite3"
            ),
            storage_path=Path(
                values.get("FORGE_STORAGE_PATH", ".state/objects").strip()
                or ".state/objects"
            ),
            storage_endpoint=(values.get("FORGE_STORAGE_ENDPOINT") or "").rstrip("/")
            or None,
            storage_token=values.get("FORGE_STORAGE_TOKEN") or None,
            resume_template_path=Path(
                values.get(
                    "FORGE_RESUME_TEMPLATE",
                    "templates/Axelyn_Standard_Resume_v1.docx",
                ).strip()
                or "templates/Axelyn_Standard_Resume_v1.docx"
            ),
            max_resume_bytes=int(
                values.get("FORGE_MAX_RESUME_BYTES", str(10 * 1024 * 1024))
            ),
            max_resume_files=int(values.get("FORGE_MAX_RESUME_FILES", "5")),
            cors_origins=_origins(
                values.get(
                    "FORGE_CORS_ORIGINS",
                    "http://localhost:4321,http://localhost:8080",
                )
            ),
            clerk_secret_key=values.get("CLERK_SECRET_KEY") or None,
            clerk_jwt_key=(values.get("CLERK_JWT_KEY") or "").replace("\\n", "\n")
            or None,
            clerk_authorized_parties=_origins(
                values.get(
                    "CLERK_AUTHORIZED_PARTIES",
                    (
                        "http://localhost:4321,http://127.0.0.1:4321,"
                        "http://localhost:8080,http://127.0.0.1:8080,"
                        "https://forge.axelyn.com"
                    ),
                )
            ),
        )
