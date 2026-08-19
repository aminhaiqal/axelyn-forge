"""Safe, atomic DOCX-to-PDF conversion through headless LibreOffice."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Optional, Union

from .docx import validate_docx_archive
from .errors import PDFConversionError

PathLike = Union[str, Path]
DEFAULT_LIBREOFFICE_EXECUTABLE = "soffice"
DEFAULT_PDF_TIMEOUT_SECONDS = 120


def validate_pdf_file(path: PathLike) -> Path:
    """Require the minimal structural markers of a non-empty PDF file."""
    source = Path(path)
    if not source.is_file():
        raise PDFConversionError(f"PDF output was not created: {source}")
    try:
        size = source.stat().st_size
        with source.open("rb") as handle:
            header = handle.read(8)
            handle.seek(max(0, size - 2048))
            trailer = handle.read()
    except OSError as exc:
        raise PDFConversionError(f"Could not validate PDF output {source}: {exc}") from exc
    if size < 32 or not header.startswith(b"%PDF-") or b"%%EOF" not in trailer:
        raise PDFConversionError(f"LibreOffice produced an invalid PDF: {source}")
    return source


def _diagnostic(stdout: str, stderr: str) -> str:
    value = " ".join((stderr or stdout).split())
    return value[:800] if value else "no converter diagnostics were returned"


def convert_docx_to_pdf(
    source: PathLike,
    output: PathLike,
    *,
    executable: str = DEFAULT_LIBREOFFICE_EXECUTABLE,
    timeout_seconds: int = DEFAULT_PDF_TIMEOUT_SECONDS,
    environ: Optional[Mapping[str, str]] = None,
) -> Path:
    """Convert one DOCX without modifying it and atomically publish a validated PDF."""
    input_path = Path(source)
    output_path = Path(output)
    if input_path.suffix.lower() != ".docx":
        raise PDFConversionError(f"DOCX input must use the .docx extension: {input_path}")
    if output_path.suffix.lower() != ".pdf":
        raise PDFConversionError(f"PDF output must use the .pdf extension: {output_path}")
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise PDFConversionError("PDF conversion timeout must be a positive integer")
    if not input_path.is_file():
        raise PDFConversionError(f"DOCX input does not exist: {input_path}")
    validate_docx_archive(input_path)

    converter = shutil.which(executable)
    if converter is None:
        raise PDFConversionError(
            f"LibreOffice executable '{executable}' was not found; install LibreOffice Writer"
        )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=str(output_path.parent),
            prefix=".forge-pdf-",
        ) as temp_dir:
            workspace = Path(temp_dir)
            staged_docx = workspace / f"{output_path.stem}.docx"
            staged_pdf = workspace / output_path.name
            profile = workspace / "libreoffice-profile"
            profile.mkdir()
            shutil.copy2(input_path, staged_docx)

            command = [
                converter,
                "--headless",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--nofirststartwizard",
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(workspace),
                str(staged_docx),
            ]
            process_environment = dict(os.environ if environ is None else environ)
            process_environment["SAL_USE_VCLPLUGIN"] = "svp"
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=process_environment,
            )
            if completed.returncode != 0:
                raise PDFConversionError(
                    "LibreOffice DOCX-to-PDF conversion failed: "
                    + _diagnostic(completed.stdout, completed.stderr)
                )
            validate_pdf_file(staged_pdf)
            os.replace(staged_pdf, output_path)
    except subprocess.TimeoutExpired as exc:
        raise PDFConversionError(
            f"LibreOffice DOCX-to-PDF conversion timed out after {timeout_seconds} seconds"
        ) from exc
    except PDFConversionError:
        raise
    except OSError as exc:
        raise PDFConversionError(f"Could not publish PDF output {output_path}: {exc}") from exc

    return validate_pdf_file(output_path)
