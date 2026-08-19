import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forge.errors import PDFConversionError
from forge.pdf import convert_docx_to_pdf, validate_pdf_file

from .helpers import TEMPLATE


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def successful_libreoffice(command, **kwargs):
    output_dir = Path(command[command.index("--outdir") + 1])
    source = Path(command[-1])
    (output_dir / f"{source.stem}.pdf").write_bytes(VALID_PDF)
    return subprocess.CompletedProcess(command, 0, stdout="converted", stderr="")


class PDFConversionTests(unittest.TestCase):
    def test_conversion_is_atomic_and_preserves_source_docx(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "Amin_Haiqal_Resume_Engineer.pdf"
            original_hash = file_hash(TEMPLATE)
            with patch("forge.pdf.shutil.which", return_value="/usr/bin/soffice"), patch(
                "forge.pdf.subprocess.run",
                side_effect=successful_libreoffice,
            ) as run:
                result = convert_docx_to_pdf(TEMPLATE, output)

            self.assertEqual(output, result)
            self.assertEqual(original_hash, file_hash(TEMPLATE))
            self.assertEqual(VALID_PDF, output.read_bytes())
            command = run.call_args.args[0]
            self.assertIn("--headless", command)
            self.assertIn("pdf:writer_pdf_Export", command)
            self.assertTrue(
                any(item.startswith("-env:UserInstallation=file:") for item in command)
            )
            self.assertEqual("svp", run.call_args.kwargs["env"]["SAL_USE_VCLPLUGIN"])

    def test_missing_libreoffice_fails_clearly_without_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "resume.pdf"
            with patch("forge.pdf.shutil.which", return_value=None):
                with self.assertRaisesRegex(PDFConversionError, "was not found"):
                    convert_docx_to_pdf(TEMPLATE, output)
            self.assertFalse(output.exists())

    def test_converter_error_and_invalid_pdf_do_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "resume.pdf"
            output.write_bytes(VALID_PDF)
            with patch("forge.pdf.shutil.which", return_value="/usr/bin/soffice"), patch(
                "forge.pdf.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["soffice"],
                    1,
                    stdout="",
                    stderr="conversion failed",
                ),
            ):
                with self.assertRaisesRegex(PDFConversionError, "conversion failed"):
                    convert_docx_to_pdf(TEMPLATE, output)
            self.assertEqual(VALID_PDF, output.read_bytes())

            with self.assertRaisesRegex(PDFConversionError, "invalid PDF"):
                invalid = Path(temp_dir) / "invalid.pdf"
                invalid.write_text("not a PDF", encoding="utf-8")
                validate_pdf_file(invalid)

    def test_extensions_and_timeout_are_validated_before_conversion(self):
        with self.assertRaisesRegex(PDFConversionError, ".docx extension"):
            convert_docx_to_pdf("resume.doc", "resume.pdf")
        with self.assertRaisesRegex(PDFConversionError, ".pdf extension"):
            convert_docx_to_pdf(TEMPLATE, "resume.txt")
        with self.assertRaisesRegex(PDFConversionError, "positive integer"):
            convert_docx_to_pdf(TEMPLATE, "resume.pdf", timeout_seconds=0)


if __name__ == "__main__":
    unittest.main()
