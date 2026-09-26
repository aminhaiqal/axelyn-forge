import unittest
import zipfile
from io import BytesIO
from unittest.mock import patch

import httpx

from axelyn_api.converter import DocumentConversionError, HttpDocumentConverter


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"


def valid_docx() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    return output.getvalue()


class DocumentConverterClientTests(unittest.TestCase):
    @patch("axelyn_api.converter.httpx.post")
    def test_sends_docx_to_private_endpoint_and_accepts_valid_pdf(self, post):
        post.return_value = httpx.Response(
            200,
            content=VALID_PDF,
            headers={"Content-Type": "application/pdf"},
        )
        converter = HttpDocumentConverter("http://converter:8100", timeout_seconds=90)

        result = converter.docx_to_pdf(b"PK document", "resume.docx")

        self.assertEqual(VALID_PDF, result)
        self.assertEqual(
            "http://converter:8100/v1/convert/docx-to-pdf",
            post.call_args.args[0],
        )
        self.assertEqual(90, post.call_args.kwargs["timeout"])
        self.assertEqual("resume.docx", post.call_args.kwargs["files"]["file"][0])

    @patch("axelyn_api.converter.httpx.post")
    def test_rejects_invalid_pdf_response(self, post):
        post.return_value = httpx.Response(
            200,
            content=b"not a pdf",
            headers={"Content-Type": "application/pdf"},
        )
        converter = HttpDocumentConverter("http://converter:8100")

        with self.assertRaisesRegex(DocumentConversionError, "invalid PDF"):
            converter.docx_to_pdf(b"PK document", "resume.docx")

    @patch("axelyn_api.converter.httpx.post")
    def test_sends_pdf_to_private_endpoint_and_accepts_valid_docx(self, post):
        docx = valid_docx()
        post.return_value = httpx.Response(
            200,
            content=docx,
            headers={
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                )
            },
        )
        converter = HttpDocumentConverter("http://converter:8100", timeout_seconds=90)

        result = converter.pdf_to_docx(VALID_PDF, "resume.pdf")

        self.assertEqual(docx, result)
        self.assertEqual(
            "http://converter:8100/v1/convert/pdf-to-docx",
            post.call_args.args[0],
        )
        self.assertEqual("resume.pdf", post.call_args.kwargs["files"]["file"][0])

    @patch("axelyn_api.converter.httpx.post")
    def test_rejects_invalid_docx_response(self, post):
        post.return_value = httpx.Response(
            200,
            content=b"not a docx",
            headers={
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                )
            },
        )
        converter = HttpDocumentConverter("http://converter:8100")

        with self.assertRaisesRegex(DocumentConversionError, "invalid DOCX"):
            converter.pdf_to_docx(VALID_PDF, "resume.pdf")

    @patch("axelyn_api.converter.httpx.post")
    def test_sends_image_to_private_ocr_endpoint(self, post):
        post.return_value = httpx.Response(
            200,
            json={"text": "Senior Python engineer"},
            headers={"Content-Type": "application/json"},
        )
        converter = HttpDocumentConverter("http://converter:8100", timeout_seconds=90)

        result = converter.image_to_text(b"image", "job.png")

        self.assertEqual("Senior Python engineer", result)
        self.assertEqual(
            "http://converter:8100/v1/extract/image-text",
            post.call_args.args[0],
        )
        self.assertEqual("job.png", post.call_args.kwargs["files"]["file"][0])


if __name__ == "__main__":
    unittest.main()
