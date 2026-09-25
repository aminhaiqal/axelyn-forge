"""Private object storage for uploaded and generated resume artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import quote

import httpx


class ObjectStore(Protocol):
    def put(self, key: str, payload: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


def _validated_key(key: str) -> PurePosixPath:
    path = PurePosixPath(key)
    if (
        not key
        or path.is_absolute()
        or ".." in path.parts
        or any(not part or part == "." for part in path.parts)
    ):
        raise ValueError("Invalid private object key.")
    return path


class FileObjectStore:
    """Filesystem-backed private storage for tests and single-host development."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        relative = _validated_key(key)
        return self.root.joinpath(*relative.parts)

    def put(self, key: str, payload: bytes, content_type: str) -> None:
        del content_type
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as error:
            raise KeyError(key) from error

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class HttpObjectStore:
    """Server-to-server gateway for the private Cloudflare R2 bucket."""

    def __init__(self, endpoint: str, token: str):
        if not endpoint.startswith("https://"):
            raise ValueError("The object-storage endpoint must use HTTPS.")
        if not token:
            raise ValueError("The object-storage token is required.")
        self.endpoint = endpoint.rstrip("/")
        self.token = token

    def _url(self, key: str) -> str:
        _validated_key(key)
        return f"{self.endpoint}/objects/{quote(key, safe='/')}"

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def put(self, key: str, payload: bytes, content_type: str) -> None:
        response = httpx.put(
            self._url(key),
            content=payload,
            headers=self._headers(content_type),
            timeout=45,
        )
        response.raise_for_status()

    def get(self, key: str) -> bytes:
        response = httpx.get(
            self._url(key),
            headers=self._headers(),
            timeout=45,
        )
        if response.status_code == 404:
            raise KeyError(key)
        response.raise_for_status()
        return response.content

    def delete(self, key: str) -> None:
        response = httpx.delete(
            self._url(key),
            headers=self._headers(),
            timeout=30,
        )
        if response.status_code not in (204, 404):
            response.raise_for_status()


def create_object_store(
    *,
    storage_path: Path,
    endpoint: str | None,
    token: str | None,
) -> ObjectStore:
    if endpoint:
        return HttpObjectStore(endpoint, token or "")
    return FileObjectStore(storage_path)
