import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from axelyn_converter.main import create_app


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.converted_payloads: list[bytes] = []

        def convert(source: Path, output: Path) -> Path:
            self.converted_payloads.append(source.read_bytes())
            output.write_bytes(VALID_PDF)
            return output

        app = create_app(
            convert=convert,
            executable_check=lambda _: "/usr/bin/soffice",
            max_docx_bytes=128,
        )
        self.client = TestClient(app)

    def test_health_reports_libreoffice_engine(self):
        response = self.client.get("/healthz")

        self.assertEqual(200, response.status_code)
        self.assertEqual("libreoffice", response.json()["engine"])

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


if __name__ == "__main__":
    unittest.main()
