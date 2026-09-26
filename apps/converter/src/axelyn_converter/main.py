"""Private DOCX-to-PDF service backed by headless LibreOffice."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Callable

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from forge.errors import DocxError, PDFConversionError
from forge.pdf import convert_docx_to_pdf
from PIL import Image, UnidentifiedImageError

from . import __version__

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA_TYPE = "application/pdf"
DEFAULT_MAX_DOCX_BYTES = 12 * 1024 * 1024
DEFAULT_MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
Converter = Callable[[Path, Path], Path]
PdfConverter = Callable[[Path, Path], Path]
OcrExtractor = Callable[[Path], str]


def _validate_docx(path: Path) -> bytes:
    try:
        payload = path.read_bytes()
        with zipfile.ZipFile(BytesIO(payload), "r") as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile) as error:
        raise RuntimeError("LibreOffice produced an invalid DOCX.") from error
    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise RuntimeError("LibreOffice produced an invalid DOCX.")
    return payload


def convert_pdf_to_docx(source: Path, output: Path) -> Path:
    """Import a PDF through LibreOffice Writer and save it as editable DOCX."""
    workspace = output.parent
    profile = workspace / "libreoffice-pdf-profile"
    profile.mkdir(exist_ok=True)
    try:
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--infilter=writer_pdf_import",
                "--convert-to",
                "docx:Office Open XML Text",
                "--outdir",
                str(workspace),
                str(source),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("LibreOffice could not convert the PDF to DOCX.") from error

    generated = workspace / f"{source.stem}.docx"
    if result.returncode != 0 or not generated.is_file():
        raise RuntimeError("LibreOffice could not convert the PDF to DOCX.")
    _validate_docx(generated)
    generated.replace(output)
    return output


def extract_image_text(source: Path) -> str:
    try:
        result = subprocess.run(
            ["tesseract", str(source), "stdout", "-l", "eng", "--psm", "6"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as error:
        raise RuntimeError("Tesseract could not extract text from this image.") from error
    return result.stdout.strip()


def create_app(
    *,
    convert: Converter = convert_docx_to_pdf,
    convert_pdf: PdfConverter = convert_pdf_to_docx,
    extract_text: OcrExtractor = extract_image_text,
    executable_check: Callable[[str], str | None] = shutil.which,
    max_docx_bytes: int = DEFAULT_MAX_DOCX_BYTES,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
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
        if executable_check("tesseract") is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Tesseract OCR is unavailable.",
            )
        return {
            "status": "ok",
            "service": "axelyn-forge-converter",
            "version": __version__,
            "engine": "libreoffice",
            "ocr_engine": "tesseract",
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

    @app.post("/v1/convert/pdf-to-docx", include_in_schema=False)
    def pdf_to_docx(file: UploadFile = File()) -> Response:
        filename = Path(file.filename or "document.pdf").name
        if Path(filename).suffix.casefold() != ".pdf":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A PDF file is required.",
            )
        payload = file.file.read(max_docx_bytes + 1)
        if len(payload) > max_docx_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="The PDF exceeds the converter size limit.",
            )
        if not payload.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The upload is not a valid PDF document.",
            )
        if not slots.acquire(timeout=30):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The document converter is busy. Try again shortly.",
            )
        try:
            with tempfile.TemporaryDirectory(prefix="forge-converter-") as directory:
                workspace = Path(directory)
                source = workspace / "source.pdf"
                output = workspace / "normalized.docx"
                source.write_bytes(payload)
                try:
                    convert_pdf(source, output)
                    docx = _validate_docx(output)
                except RuntimeError as error:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="LibreOffice could not convert this PDF to Word.",
                    ) from error
        finally:
            slots.release()

        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip("-.")
        docx_name = f"{safe_stem or 'document'}.docx"
        return Response(
            docx,
            media_type=DOCX_MEDIA_TYPE,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{docx_name}"',
                "X-Content-Type-Options": "nosniff",
                "X-Document-Engine": "LibreOffice",
            },
        )

    @app.post("/v1/extract/image-text", include_in_schema=False)
    def image_to_text(file: UploadFile = File()) -> dict[str, str]:
        filename = Path(file.filename or "job-description.png").name
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A PNG or JPEG image is required.",
            )
        payload = file.file.read(max_image_bytes + 1)
        if len(payload) > max_image_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="The image exceeds the OCR size limit.",
            )
        try:
            with Image.open(BytesIO(payload)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="The image dimensions exceed the OCR limit.",
                    )
                if image.format not in {"PNG", "JPEG"}:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="The upload is not a valid PNG or JPEG image.",
                    )
                image.load()
                normalized = image.convert("RGB")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The upload is not a valid PNG or JPEG image.",
            ) from error

        if not slots.acquire(timeout=30):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The document converter is busy. Try again shortly.",
            )
        try:
            with tempfile.TemporaryDirectory(prefix="forge-ocr-") as directory:
                source = Path(directory) / "source.png"
                normalized.save(source, format="PNG", optimize=True)
                try:
                    text = extract_text(source).strip()
                except RuntimeError as error:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="OCR could not read this image.",
                    ) from error
        finally:
            slots.release()
        return {"text": text[:100_000]}

    return app


app = create_app(
    max_concurrent=int(os.environ.get("FORGE_CONVERTER_CONCURRENCY", "1")),
    max_docx_bytes=int(
        os.environ.get("FORGE_CONVERTER_MAX_DOCX_BYTES", str(DEFAULT_MAX_DOCX_BYTES))
    ),
    max_image_bytes=int(
        os.environ.get("FORGE_CONVERTER_MAX_IMAGE_BYTES", str(DEFAULT_MAX_IMAGE_BYTES))
    ),
)


def run() -> None:
    uvicorn.run(
        "axelyn_converter.main:app",
        host=os.environ.get("FORGE_CONVERTER_HOST", "0.0.0.0"),
        port=int(os.environ.get("FORGE_CONVERTER_PORT", "8100")),
        reload=False,
    )
