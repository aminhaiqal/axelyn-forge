import tempfile
import unittest
import zipfile
from pathlib import Path

from axelyn_api.resume_import import (
    normalize_resume_text,
    standard_template_values,
    unmapped_resume_content,
)
from axelyn_api.resume_templates import render_resume


class ResumeTemplateTests(unittest.TestCase):
    def test_every_template_renders_all_sections_without_layout_objects(self):
        draft = {
            "full_name": "Taylor Example",
            "headline": "Platform Engineer",
            "email_address": "taylor@example.com",
            "phone_number": "+60 12-345 6789",
            "location": "Kuala Lumpur, Malaysia",
            "linkedin_url": "https://linkedin.com/in/taylor-example",
            "portfolio_url": "https://taylor.example",
            "github_url": "https://github.com/taylor-example",
            "summary": "Builds reliable systems.",
            "experience_entries": [
                {
                    "company_name": "Structured Systems",
                    "job_title": "Platform Engineer",
                    "employment_type": "Full-time",
                    "location": "Kuala Lumpur",
                    "work_arrangement": "Remote",
                    "start_date": "2024-01",
                    "currently_working_here": True,
                    "responsibilities": "Owns platform reliability.",
                    "achievements": "Reduced recovery time by 40%.",
                }
            ],
            "education_entries": [
                {
                    "institution_name": "Universiti Teknologi Malaysia",
                    "qualification": "Bachelor of Computer Science",
                    "field_of_study": "Software Engineering",
                    "education_level": "Bachelor’s Degree",
                    "location": "Johor Bahru",
                    "start_date": "2020-09",
                    "end_date": "2024-06",
                    "gpa": "3.72 / 4.00",
                    "honours": "First Class Honours",
                    "thesis_title": "Intelligent Document Classification",
                    "academic_achievements": "Dean’s List",
                }
            ],
            "project_entries": [
                {
                    "project_name": "Monitorscape",
                    "project_type": "Commercial Product",
                    "role": "Backend Developer",
                    "start_date": "2024-02",
                    "currently_working_on_project": True,
                    "personal_contribution": "Designed the event ingestion API.",
                    "technologies": "Python, FastAPI, PostgreSQL, Docker",
                    "impact": "Reduced incident response time by 60%.",
                    "metrics": "Processed 100K events.",
                    "project_status": "Live / Production",
                }
            ],
            "skill_categories": [
                {"category": "Framework", "skills": ["Django", "FastAPI"]},
                {
                    "category": "Programming Language",
                    "skills": ["Python", "Go", "TypeScript"],
                },
                {"category": "Database", "skills": ["PostgreSQL", "Redis"]},
            ],
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

        template_values = standard_template_values(draft)
        self.assertEqual(
            "taylor@example.com | +60 12-345 6789 | Kuala Lumpur, Malaysia | "
            "https://linkedin.com/in/taylor-example | https://taylor.example | "
            "https://github.com/taylor-example",
            template_values["profile.contactLine"],
        )
        self.assertEqual("Monitorscape", template_values["project.monitorscape.title"])
        self.assertEqual(
            "Python, FastAPI, PostgreSQL, Docker",
            template_values["project.monitorscape.technologies"],
        )
        self.assertEqual(
            "Designed the event ingestion API.",
            template_values["project.monitorscape.highlight.1"],
        )
        self.assertEqual("Framework", template_values["skills.backend.label"])
        self.assertEqual(
            "Django, FastAPI", template_values["skills.backend.items"]
        )
        self.assertEqual(
            "Python, Go, TypeScript", template_values["skills.programming.items"]
        )

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
                    b"taylor@example.com",
                    b"https://github.com/taylor-example",
                    b"Structured Systems",
                    b"Reduced recovery time by 40%",
                    b"Built production APIs",
                    b"Universiti Teknologi Malaysia",
                    b"Intelligent Document Classification",
                    "Dean’s List".encode(),
                    b"Monitorscape",
                    b"Designed the event ingestion API",
                    b"Reduced incident response time by 60%",
                    b"Framework: Django, FastAPI",
                    b"Programming Language: Python, Go, TypeScript",
                    b"PUBLICATIONS",
                    b"Reliable Systems Review",
                ):
                    self.assertIn(text, xml)
                self.assertNotIn(b"<w:tbl", xml)
                self.assertNotIn(b"<w:txbxContent", xml)
                self.assertNotIn(b"<w:drawing", xml)
            self.assertEqual(3, len(set(documents)))

    def test_import_recognizes_custom_sections_and_surfaces_unmapped_lines(self):
        contact = normalize_resume_text(
            "Taylor Example\nPlatform Engineer\n"
            "taylor@example.com | +60 12-345 6789 | Klang, Selangor, Malaysia | "
            "linkedin.com/in/taylor-example\nSummary\nBuilds reliable systems."
        )
        self.assertEqual("taylor@example.com", contact["email_address"])
        self.assertEqual("+60 12-345 6789", contact["phone_number"])
        self.assertEqual("Klang, Selangor, Malaysia", contact["location"])
        self.assertEqual(
            "https://linkedin.com/in/taylor-example", contact["linkedin_url"]
        )

        normalized = normalize_resume_text(
            "Taylor Example\nPlatform Engineer\ntaylor@example.com\n"
            "Experience\nEngineer | Example\n2022 - Present\n"
            "Languages\nEnglish and Malay\n"
            "Certifications\nAWS Solutions Architect\n"
            "Publications\nReliable Systems Review\n"
            "Security Clearance\nSecret"
        )

        self.assertEqual(
            ["Languages", "Certifications", "Publications", "Security Clearance"],
            [section["title"] for section in normalized["custom_sections"]],
        )
        self.assertEqual("taylor@example.com", normalized["email_address"])
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
