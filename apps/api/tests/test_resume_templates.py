import tempfile
import unittest
import zipfile
from pathlib import Path

from axelyn_api.resume_import import normalize_resume_text, unmapped_resume_content
from axelyn_api.resume_templates import render_resume


class ResumeTemplateTests(unittest.TestCase):
    def test_every_template_renders_all_sections_without_layout_objects(self):
        draft = {
            "full_name": "Taylor Example",
            "headline": "Platform Engineer",
            "contact_line": "taylor@example.com | Kuala Lumpur",
            "summary": "Builds reliable systems.",
            "sections": {
                "experience": ["Engineer | Example", "• Built production APIs."],
                "projects": ["Open source platform"],
                "education": ["BSc Computer Science"],
                "skills": ["Python, PostgreSQL"],
                "languages": ["English"],
                "additional": ["Available immediately"],
            },
            "custom_sections": [
                {"title": "Publications", "lines": ["Reliable Systems Review"]}
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            documents = []
            for template_id in ("ats-classic", "ats-modern", "ats-compact"):
                output = Path(directory) / f"{template_id}.docx"
                selected, version = render_resume(
                    draft={**draft, "template_id": template_id},
                    output=output,
                    title="Taylor resume",
                    description="Test resume",
                )
                self.assertEqual(template_id, selected)
                self.assertEqual("1", version)
                with zipfile.ZipFile(output) as archive:
                    xml = archive.read("word/document.xml")
                documents.append(xml)
                for text in (
                    b"Taylor Example",
                    b"Built production APIs",
                    b"PUBLICATIONS",
                    b"Reliable Systems Review",
                ):
                    self.assertIn(text, xml)
                self.assertNotIn(b"<w:tbl", xml)
                self.assertNotIn(b"<w:txbxContent", xml)
                self.assertNotIn(b"<w:drawing", xml)
            self.assertEqual(3, len(set(documents)))

    def test_import_recognizes_custom_sections_and_surfaces_unmapped_lines(self):
        normalized = normalize_resume_text(
            "Taylor Example\nPlatform Engineer\ntaylor@example.com\n"
            "Experience\nEngineer | Example\n2022 - Present\n"
            "Publications\nReliable Systems Review\n"
            "Security Clearance\nSecret"
        )

        self.assertEqual(
            ["Publications", "Security Clearance"],
            [section["title"] for section in normalized["custom_sections"]],
        )
        draft = {
            **normalized,
            "extracted_text": (
                "Taylor Example\nPlatform Engineer\ntaylor@example.com\n"
                "Experience\nEngineer | Example\n2022 - Present\n"
                "Portfolio note that was not mapped"
            ),
        }
        self.assertEqual(
            ["Portfolio note that was not mapped"],
            unmapped_resume_content(draft),
        )


if __name__ == "__main__":
    unittest.main()
