"""Client boundary for the private LibreOffice conversion service."""

from __future__ import annotations

import io
import zipfile
from typing import Protocol

import httpx

from .resume_import import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE


class DocumentConversionError(RuntimeError):
    """A document could not be converted or validated."""


class DocumentConverter(Protocol):
    def docx_to_pdf(self, payload: bytes, filename: str) -> bytes: ...

    def pdf_to_docx(self, payload: bytes, filename: str) -> bytes: ...

    def image_to_text(self, payload: bytes, filename: str) -> str: ...


def _validate_pdf(payload: bytes) -> bytes:
    trailer = payload[-2048:]
    if len(payload) < 32 or not payload.startswith(b"%PDF-") or b"%%EOF" not in trailer:
        raise DocumentConversionError("The converter returned an invalid PDF.")
    return payload


def _validate_docx(payload: bytes) -> bytes:
    if len(payload) < 32 or not payload.startswith(b"PK"):
        raise DocumentConversionError("The converter returned an invalid DOCX.")
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile as error:
        raise DocumentConversionError("The converter returned an invalid DOCX.") from error
    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise DocumentConversionError("The converter returned an invalid DOCX.")
    return payload


class HttpDocumentConverter:
    """Call the converter over the private Compose network."""

    def __init__(self, endpoint: str, timeout_seconds: int = 150):
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("The document converter endpoint must use HTTP or HTTPS.")
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def docx_to_pdf(self, payload: bytes, filename: str) -> bytes:
        try:
            response = httpx.post(
                f"{self.endpoint}/v1/convert/docx-to-pdf",
                files={"file": (filename, payload, DOCX_MEDIA_TYPE)},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as error:
            raise DocumentConversionError(
                "The LibreOffice converter could not be reached."
            ) from error
        if response.status_code != 200:
            raise DocumentConversionError(
                f"The LibreOffice converter returned HTTP {response.status_code}."
            )
        if response.headers.get("content-type", "").split(";", 1)[0] != PDF_MEDIA_TYPE:
            raise DocumentConversionError("The converter returned an unexpected media type.")
        return _validate_pdf(response.content)

    def pdf_to_docx(self, payload: bytes, filename: str) -> bytes:
        try:
            response = httpx.post(
                f"{self.endpoint}/v1/convert/pdf-to-docx",
                files={"file": (filename, payload, PDF_MEDIA_TYPE)},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as error:
            raise DocumentConversionError(
                "The LibreOffice converter could not be reached."
            ) from error
        if response.status_code != 200:
            raise DocumentConversionError(
                f"The LibreOffice converter returned HTTP {response.status_code}."
            )
        if response.headers.get("content-type", "").split(";", 1)[0] != DOCX_MEDIA_TYPE:
            raise DocumentConversionError("The converter returned an unexpected media type.")
        return _validate_docx(response.content)

    def image_to_text(self, payload: bytes, filename: str) -> str:
        try:
            response = httpx.post(
                f"{self.endpoint}/v1/extract/image-text",
                files={"file": (filename, payload, "application/octet-stream")},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as error:
            raise DocumentConversionError(
                "The image text extractor could not be reached."
            ) from error
        if response.status_code != 200:
            raise DocumentConversionError(
                f"The image text extractor returned HTTP {response.status_code}."
            )
        try:
            text = response.json()["text"]
        except (ValueError, KeyError, TypeError) as error:
            raise DocumentConversionError(
                "The image text extractor returned an invalid response."
            ) from error
        if not isinstance(text, str) or len(text) > 100_000:
            raise DocumentConversionError(
                "The image text extractor returned invalid text."
            )
        return text.strip()


class UnavailableDocumentConverter:
    def docx_to_pdf(self, payload: bytes, filename: str) -> bytes:
        del payload, filename
        raise DocumentConversionError("The LibreOffice converter is not configured.")

    def pdf_to_docx(self, payload: bytes, filename: str) -> bytes:
        del payload, filename
        raise DocumentConversionError("The LibreOffice converter is not configured.")

    def image_to_text(self, payload: bytes, filename: str) -> str:
        del payload, filename
        raise DocumentConversionError("The image text extractor is not configured.")


def create_document_converter(
    endpoint: str | None,
    timeout_seconds: int,
) -> DocumentConverter:
    if not endpoint:
        return UnavailableDocumentConverter()
    return HttpDocumentConverter(endpoint, timeout_seconds)
