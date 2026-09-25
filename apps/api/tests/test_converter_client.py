import unittest
from unittest.mock import patch

import httpx

from axelyn_api.converter import DocumentConversionError, HttpDocumentConverter


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"


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


if __name__ == "__main__":
    unittest.main()
