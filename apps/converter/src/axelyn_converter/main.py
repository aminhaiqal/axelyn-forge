"""Private DOCX-to-PDF service backed by headless LibreOffice."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from forge.errors import DocxError, PDFConversionError
from forge.pdf import convert_docx_to_pdf

from . import __version__

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA_TYPE = "application/pdf"
DEFAULT_MAX_DOCX_BYTES = 12 * 1024 * 1024
Converter = Callable[[Path, Path], Path]


def create_app(
    *,
    convert: Converter = convert_docx_to_pdf,
    executable_check: Callable[[str], str | None] = shutil.which,
    max_docx_bytes: int = DEFAULT_MAX_DOCX_BYTES,
    max_concurrent: int = 1,
) -> FastAPI:
    """Create the internal converter with bounded LibreOffice concurrency."""
    if max_concurrent < 1:
        raise ValueError("max_concurrent must be positive")
    slots = threading.BoundedSemaphore(max_concurrent)
    app = FastAPI(
        title="Axelyn Forge Converter",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz", include_in_schema=False)
    def health() -> dict[str, str]:
        if executable_check("soffice") is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LibreOffice is unavailable.",
            )
        return {
            "status": "ok",
            "service": "axelyn-forge-converter",
            "version": __version__,
            "engine": "libreoffice",
        }

    @app.post("/v1/convert/docx-to-pdf", include_in_schema=False)
    def docx_to_pdf(file: UploadFile = File()) -> Response:
        filename = Path(file.filename or "document.docx").name
        if Path(filename).suffix.casefold() != ".docx":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A DOCX file is required.",
            )
        payload = file.file.read(max_docx_bytes + 1)
        if len(payload) > max_docx_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="The DOCX exceeds the converter size limit.",
            )
        if not payload.startswith(b"PK"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The upload is not a valid DOCX archive.",
            )
        if not slots.acquire(timeout=30):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The document converter is busy. Try again shortly.",
            )
        try:
            with tempfile.TemporaryDirectory(prefix="forge-converter-") as directory:
                workspace = Path(directory)
                source = workspace / "source.docx"
                output = workspace / "output.pdf"
                source.write_bytes(payload)
                try:
                    convert(source, output)
                except DocxError as error:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="The upload is not a valid DOCX document.",
                    ) from error
                except PDFConversionError as error:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="LibreOffice could not convert this document.",
                    ) from error
                pdf = output.read_bytes()
        finally:
            slots.release()

        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip("-.")
        pdf_name = f"{safe_stem or 'document'}.pdf"
        return Response(
            pdf,
            media_type=PDF_MEDIA_TYPE,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{pdf_name}"',
                "X-Content-Type-Options": "nosniff",
                "X-Document-Engine": "LibreOffice",
            },
        )

    return app


app = create_app(
    max_concurrent=int(os.environ.get("FORGE_CONVERTER_CONCURRENCY", "1")),
    max_docx_bytes=int(
        os.environ.get("FORGE_CONVERTER_MAX_DOCX_BYTES", str(DEFAULT_MAX_DOCX_BYTES))
    ),
)


def run() -> None:
    uvicorn.run(
        "axelyn_converter.main:app",
        host=os.environ.get("FORGE_CONVERTER_HOST", "0.0.0.0"),
        port=int(os.environ.get("FORGE_CONVERTER_PORT", "8100")),
        reload=False,
    )
