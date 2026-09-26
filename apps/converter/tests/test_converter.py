import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from axelyn_converter.main import create_app


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"


def valid_docx() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    return output.getvalue()


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.converted_payloads: list[bytes] = []
        self.converted_pdf_payloads: list[bytes] = []
        self.ocr_images: list[tuple[int, int]] = []

        def convert(source: Path, output: Path) -> Path:
            self.converted_payloads.append(source.read_bytes())
            output.write_bytes(VALID_PDF)
            return output

        def extract_text(source: Path) -> str:
            with Image.open(source) as image:
                self.ocr_images.append(image.size)
            return "Python platform engineer"

        def convert_pdf(source: Path, output: Path) -> Path:
            self.converted_pdf_payloads.append(source.read_bytes())
            output.write_bytes(valid_docx())
            return output

        app = create_app(
            convert=convert,
            convert_pdf=convert_pdf,
            extract_text=extract_text,
            executable_check=lambda _: "/usr/bin/soffice",
            max_docx_bytes=128,
            max_image_bytes=1024,
        )
        self.client = TestClient(app)

    def test_health_reports_libreoffice_engine(self):
        response = self.client.get("/healthz")

        self.assertEqual(200, response.status_code)
        self.assertEqual("libreoffice", response.json()["engine"])
        self.assertEqual("tesseract", response.json()["ocr_engine"])

    def test_docx_is_converted_to_private_uncached_pdf(self):
        payload = b"PK\x03\x04example-docx"
        response = self.client.post(
            "/v1/convert/docx-to-pdf",
            files={"file": ("Taylor Resume.docx", payload, "application/octet-stream")},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(VALID_PDF, response.content)
        self.assertEqual([payload], self.converted_payloads)
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertEqual("LibreOffice", response.headers["x-document-engine"])
        self.assertIn("Taylor-Resume.pdf", response.headers["content-disposition"])

    def test_invalid_extension_and_oversized_upload_are_rejected(self):
        wrong_extension = self.client.post(
            "/v1/convert/docx-to-pdf",
            files={"file": ("resume.pdf", b"PK document", "application/pdf")},
        )
        oversized = self.client.post(
            "/v1/convert/docx-to-pdf",
            files={"file": ("resume.docx", b"PK" + b"x" * 128, "application/octet-stream")},
        )

        self.assertEqual(422, wrong_extension.status_code)
        self.assertEqual(413, oversized.status_code)

    def test_pdf_is_converted_to_private_uncached_docx(self):
        response = self.client.post(
            "/v1/convert/pdf-to-docx",
            files={"file": ("Taylor Resume.pdf", VALID_PDF, "application/pdf")},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(valid_docx(), response.content)
        self.assertEqual([VALID_PDF], self.converted_pdf_payloads)
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertEqual("LibreOffice", response.headers["x-document-engine"])
        self.assertIn("Taylor-Resume.docx", response.headers["content-disposition"])

    def test_png_is_normalized_and_extracted_with_ocr(self):
        output = BytesIO()
        Image.new("RGB", (20, 12), "white").save(output, format="PNG")

        response = self.client.post(
            "/v1/extract/image-text",
            files={"file": ("job.png", output.getvalue(), "image/png")},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual({"text": "Python platform engineer"}, response.json())
        self.assertEqual([(20, 12)], self.ocr_images)

    def test_ocr_rejects_non_image_content(self):
        response = self.client.post(
            "/v1/extract/image-text",
            files={"file": ("job.png", b"not an image", "image/png")},
        )

        self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()
