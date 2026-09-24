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
    cors_origins: Tuple[str, ...] = (
        "http://localhost:4321",
        "http://localhost:8080",
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
            cors_origins=_origins(
                values.get(
                    "FORGE_CORS_ORIGINS",
                    "http://localhost:4321,http://localhost:8080",
                )
            ),
        )
