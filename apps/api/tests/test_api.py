import sqlite3
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from axelyn_api.config import Settings
from axelyn_api.main import create_app


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"


class FakeDocumentConverter:
    def __init__(self):
        self.requests: list[tuple[bytes, str]] = []
        self.ocr_requests: list[tuple[bytes, str]] = []

    def docx_to_pdf(self, payload: bytes, filename: str) -> bytes:
        self.requests.append((payload, filename))
        return VALID_PDF

    def image_to_text(self, payload: bytes, filename: str) -> str:
        self.ocr_requests.append((payload, filename))
        return (
            "Python APIs and reliable cloud services. Production Python APIs power reliable "
            "cloud services. Build production Python APIs for reliable cloud platforms."
        )


class ApiTests(unittest.TestCase):
    @staticmethod
    def authenticate_user(request: Request) -> str:
        sessions = {
            "Bearer test-session": "user_test_123",
            "Bearer other-session": "user_other_456",
        }
        user_id = sessions.get(request.headers.get("authorization", ""))
        if user_id is None:
            raise HTTPException(status_code=401, detail="Valid authentication is required.")
        return user_id

    @staticmethod
    def resume_docx() -> bytes:
        content_types = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
          <Default Extension="xml" ContentType="application/xml"/>
        </Types>"""
        document = b"""<?xml version="1.0" encoding="UTF-8"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body>
            <w:p><w:r><w:t>Taylor Example</w:t></w:r></w:p>
            <w:p><w:r><w:t>Backend Engineer</w:t></w:r></w:p>
            <w:p><w:r><w:t>taylor@example.com | +1 555 123 4567</w:t></w:r></w:p>
            <w:p><w:r><w:t>Summary</w:t></w:r></w:p>
            <w:p><w:r><w:t>Builds reliable Python services for cloud platforms.</w:t></w:r></w:p>
            <w:p><w:r><w:t>Experience</w:t></w:r></w:p>
            <w:p><w:r><w:t>Senior Engineer | Example Systems</w:t></w:r></w:p>
            <w:p><w:r><w:t>2022 - Present</w:t></w:r></w:p>
            <w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>Built production APIs.</w:t></w:r></w:p>
          </w:body>
        </w:document>"""
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("word/document.xml", document)
        return output.getvalue()

    @staticmethod
    def resume_pdf() -> bytes:
        content = (
            b"BT /F1 12 Tf 72 720 Td (Taylor Example) Tj "
            b"0 -18 Td (Backend Engineer) Tj "
            b"0 -18 Td (Summary) Tj "
            b"0 -18 Td (Builds reliable APIs.) Tj "
            b"0 -18 Td (Experience) Tj "
            b"0 -18 Td (Senior Engineer) Tj "
            b"0 -18 Td (2022 - Present) Tj "
            b"0 -18 Td (- Built production APIs.) Tj ET"
        )
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
            ),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        ]
        payload = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, 1):
            offsets.append(len(payload))
            payload.extend(f"{index} 0 obj\n".encode())
            payload.extend(obj)
            payload.extend(b"\nendobj\n")
        xref = len(payload)
        payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
        payload.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            payload.extend(f"{offset:010d} 00000 n \n".encode())
        payload.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n"
            ).encode()
        )
        return bytes(payload)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "forge.sqlite3"
        self.storage = Path(self.temp_dir.name) / "objects"
        self.document_converter = FakeDocumentConverter()
        app = create_app(
            Settings(
                environment="test",
                database_path=self.database,
                storage_path=self.storage,
                cors_origins=(),
            ),
            authenticate_user=self.authenticate_user,
            document_converter=self.document_converter,
        )
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)

    def test_health_and_service_catalog(self):
        health = self.client.get("/api/v1/health")
        services = self.client.get("/api/v1/services")

        self.assertEqual(200, health.status_code)
        self.assertEqual("ok", health.json()["status"])
        self.assertEqual(200, services.status_code)
        self.assertEqual(
            ["resume-tailoring", "application-kit", "resume-system"],
            [service["id"] for service in services.json()],
        )

    def test_valid_service_request_is_accepted_and_persisted(self):
        response = self.client.post(
            "/api/v1/service-requests",
            json={
                "service_id": "application-kit",
                "full_name": "Taylor Example",
                "email": "taylor@example.com",
                "company": "Example Co",
                "project_summary": (
                    "I need a resume and cover letter for a backend engineering role."
                ),
                "job_posting_url": "https://example.com/jobs/123",
                "timeline": "Within two weeks",
                "consent": True,
            },
        )

        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertTrue(body["id"].startswith("req_"))
        self.assertEqual("received", body["status"])

        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT service_id, email, status FROM service_requests WHERE id = ?",
                (body["id"],),
            ).fetchone()
        self.assertEqual(("application-kit", "taylor@example.com", "received"), row)

    def test_unknown_service_and_short_brief_are_rejected(self):
        response = self.client.post(
            "/api/v1/service-requests",
            json={
                "service_id": "unknown",
                "full_name": "Taylor Example",
                "email": "taylor@example.com",
                "project_summary": "Too short",
                "consent": True,
            },
        )

        self.assertEqual(422, response.status_code)

    def test_removed_forge_brief_endpoint_is_unavailable(self):
        response = self.client.post(
            "/api/v1/forge-briefs",
            headers={"Authorization": "Bearer test-session"},
            json={
                "target_role": "Senior backend engineer",
                "job_description": "A" * 120,
                "career_evidence": "B" * 120,
            },
        )

        self.assertEqual(404, response.status_code)

    def test_current_user_returns_authenticated_subject(self):
        response = self.client.get(
            "/api/v1/me",
            headers={"Authorization": "Bearer test-session"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"user_id": "user_test_123"}, response.json())

    def test_private_resume_import_review_render_and_download(self):
        headers = {"Authorization": "Bearer test-session"}
        imported = self.client.post(
            "/api/v1/resumes/imports",
            headers=headers,
            data={"target_role": "Backend Engineer"},
            files=[
                (
                    "files",
                    (
                        "backend-resume.docx",
                        self.resume_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(201, imported.status_code, imported.text)
        item = imported.json()["items"][0]
        self.assertEqual("stored", item["status"])
        source_id = item["source"]["id"]
        self.assertEqual("needs_review", item["source"]["status"])

        owner_list = self.client.get("/api/v1/resumes", headers=headers)
        other_list = self.client.get(
            "/api/v1/resumes",
            headers={"Authorization": "Bearer other-session"},
        )
        other_read = self.client.get(
            f"/api/v1/resumes/{source_id}",
            headers={"Authorization": "Bearer other-session"},
        )
        self.assertEqual(1, len(owner_list.json()))
        self.assertEqual([], other_list.json())
        self.assertEqual(404, other_read.status_code)

        detail = self.client.get(f"/api/v1/resumes/{source_id}", headers=headers)
        self.assertEqual(200, detail.status_code)
        source = detail.json()
        self.assertEqual("Taylor Example", source["draft"]["full_name"])
        original_transcript = source["draft"]["extracted_text"]
        source["draft"]["sections"]["experience"][-1] = (
            "• Delivered editable resume content through Forge."
        )
        saved = self.client.put(
            f"/api/v1/resumes/{source_id}/draft",
            headers=headers,
            json={
                **source["draft"],
                "extracted_text": "Attempted transcript replacement",
                "display_name": "Backend resume",
                "target_role": "Backend Engineer",
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        source = saved.json()
        self.assertEqual(original_transcript, source["draft"]["extracted_text"])

        editable_word = self.client.get(
            f"/api/v1/resumes/{source_id}/editable.docx",
            headers=headers,
        )
        other_word = self.client.get(
            f"/api/v1/resumes/{source_id}/editable.docx",
            headers={"Authorization": "Bearer other-session"},
        )
        self.assertEqual(200, editable_word.status_code, editable_word.text)
        self.assertEqual(404, other_word.status_code)
        self.assertTrue(editable_word.content.startswith(b"PK"))
        self.assertIn(
            "Backend-resume-editable.docx",
            editable_word.headers["content-disposition"],
        )
        with zipfile.ZipFile(BytesIO(editable_word.content)) as archive:
            document_xml = archive.read("word/document.xml")
        self.assertIn(b"Delivered editable resume content", document_xml)

        accepted = self.client.post(
            f"/api/v1/resumes/{source_id}/accept",
            headers=headers,
            json={
                **source["draft"],
                "display_name": "Backend resume",
                "target_role": "Backend Engineer",
                "variant_name": "Backend Engineer - Master",
            },
        )
        self.assertEqual(200, accepted.status_code, accepted.text)
        variant_id = accepted.json()["id"]

        rendered = self.client.post(
            f"/api/v1/resume-variants/{variant_id}/render",
            headers=headers,
        )
        self.assertEqual(201, rendered.status_code, rendered.text)
        documents = rendered.json()["documents"]
        self.assertEqual(2, len(documents))
        self.assertEqual(
            {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/pdf",
            },
            {document["media_type"] for document in documents},
        )
        self.assertEqual(1, len(self.document_converter.requests))
        self.assertTrue(self.document_converter.requests[0][0].startswith(b"PK"))

        downloads = {}
        for document in documents:
            response = self.client.get(
                f"/api/v1/documents/{document['id']}/download",
                headers=headers,
            )
            self.assertEqual(200, response.status_code)
            self.assertIn("attachment", response.headers["content-disposition"])
            downloads[document["media_type"]] = response.content
        self.assertTrue(
            downloads[
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ].startswith(b"PK")
        )
        self.assertEqual(VALID_PDF, downloads["application/pdf"])

        listed = self.client.get("/api/v1/generated-documents", headers=headers)
        other_listed = self.client.get(
            "/api/v1/generated-documents",
            headers={"Authorization": "Bearer other-session"},
        )
        self.assertEqual(2, len(listed.json()))
        self.assertEqual([], other_listed.json())
        other_download = self.client.get(
            f"/api/v1/documents/{documents[0]['id']}/download",
            headers={"Authorization": "Bearer other-session"},
        )
        self.assertEqual(404, other_download.status_code)

    def test_pdf_import_becomes_an_editable_word_draft(self):
        headers = {"Authorization": "Bearer test-session"}
        imported = self.client.post(
            "/api/v1/resumes/imports",
            headers=headers,
            files=[("files", ("backend-resume.pdf", self.resume_pdf(), "application/pdf"))],
        )

        self.assertEqual(201, imported.status_code, imported.text)
        source = imported.json()["items"][0]["source"]
        self.assertEqual("application/pdf", source["media_type"])
        editable_word = self.client.get(
            f"/api/v1/resumes/{source['id']}/editable.docx",
            headers=headers,
        )

        self.assertEqual(200, editable_word.status_code, editable_word.text)
        with zipfile.ZipFile(BytesIO(editable_word.content)) as archive:
            document_xml = archive.read("word/document.xml")
        self.assertIn(b"Taylor Example", document_xml)
        self.assertIn(b"Built production APIs", document_xml)

    def test_manual_resume_form_keeps_custom_sections_and_selected_template(self):
        headers = {"Authorization": "Bearer test-session"}
        templates = self.client.get("/api/v1/resume-templates")

        self.assertEqual(200, templates.status_code)
        self.assertEqual(
            ["ats-classic", "ats-modern", "ats-compact"],
            [item["id"] for item in templates.json()],
        )

        created = self.client.post(
            "/api/v1/resumes",
            headers=headers,
            json={
                "display_name": "First resume",
                "target_role": "Platform Engineer",
                "template_id": "ats-modern",
                "full_name": "Taylor Example",
                "headline": "Platform Engineer",
                "contact_line": "taylor@example.com | Kuala Lumpur",
                "summary": "Builds reliable systems.",
                "sections": {
                    "skills": ["Python, PostgreSQL, Docker"],
                },
                "experience_entries": [
                    {
                        "company_name": "Example Systems",
                        "job_title": "Engineer",
                        "employment_type": "Full-time",
                        "location": "Kuala Lumpur, Malaysia",
                        "work_arrangement": "Hybrid",
                        "start_date": "2022-01",
                        "end_date": "",
                        "currently_working_here": True,
                        "responsibilities": "Own reliable backend services.",
                        "achievements": "Built production APIs.",
                    }
                ],
                "education_entries": [
                    {
                        "institution_name": "Universiti Teknologi Malaysia",
                        "qualification": "Bachelor of Computer Science",
                        "field_of_study": "Software Engineering",
                        "education_level": "Bachelor’s Degree",
                        "location": "Johor Bahru, Malaysia",
                        "start_date": "2020-09",
                        "end_date": "2024-06",
                        "currently_studying_here": True,
                        "gpa": "3.72 / 4.00",
                        "honours": "First Class Honours",
                        "relevant_coursework": "Software Architecture, Database Systems",
                        "thesis_title": "Intelligent Document Classification",
                        "thesis_description": "Built a classification pipeline.",
                        "academic_achievements": "Dean’s List",
                        "activities": "Computing Society",
                        "relevant_skills": "Machine learning, research",
                    }
                ],
                "project_entries": [
                    {
                        "project_name": "Monitorscape",
                        "project_type": "Commercial Product",
                        "role": "Backend Developer",
                        "project_url": "https://monitorscape.example",
                        "repository_url": "https://github.com/example/monitorscape",
                        "start_date": "2024-02",
                        "end_date": "2025-08",
                        "currently_working_on_project": True,
                        "problem": "Teams could not see infrastructure failures quickly.",
                        "description": "A production infrastructure monitoring platform.",
                        "audience": "Operations teams and managed-service customers.",
                        "personal_contribution": "Designed the event ingestion API.",
                        "responsibilities": "Backend architecture, deployment, and testing.",
                        "technologies": "Python, FastAPI, PostgreSQL, Docker",
                        "challenge": "Processed noisy events without duplicate alerts.",
                        "deliverables": "Implemented authentication and alert workflows.",
                        "impact": "Reduced incident response time.",
                        "metrics": "Processed 100K events with 99.9% uptime.",
                        "project_status": "Live / Production",
                    }
                ],
                "skill_categories": [
                    {
                        "category": "Framework",
                        "skills": ["Django", "FastAPI"],
                    },
                    {
                        "category": "Programming Language",
                        "skills": ["Python", "Go", "python"],
                    },
                ],
                "custom_sections": [
                    {
                        "title": "Publications",
                        "lines": ["Reliable Systems Review | 2025"],
                    }
                ],
            },
        )

        self.assertEqual(201, created.status_code, created.text)
        source = created.json()
        source_id = source["id"]
        self.assertEqual("application/vnd.axelyn.resume+json", source["media_type"])
        self.assertEqual([], source["unmapped_content"])
        self.assertEqual("", source["draft"]["extracted_text"])
        self.assertEqual("ats-modern", source["draft"]["template_id"])
        self.assertTrue(
            source["draft"]["experience_entries"][0]["currently_working_here"]
        )
        self.assertTrue(
            source["draft"]["education_entries"][0]["currently_studying_here"]
        )
        self.assertEqual("", source["draft"]["education_entries"][0]["end_date"])
        self.assertTrue(
            source["draft"]["project_entries"][0]["currently_working_on_project"]
        )
        self.assertEqual("", source["draft"]["project_entries"][0]["end_date"])
        self.assertEqual(
            ["Python", "Go"], source["draft"]["skill_categories"][1]["skills"]
        )
        self.assertEqual(
            "Publications", source["draft"]["custom_sections"][0]["title"]
        )

        accepted = self.client.post(
            f"/api/v1/resumes/{source_id}/accept",
            headers=headers,
            json={
                **source["draft"],
                "display_name": "First resume",
                "target_role": "Platform Engineer",
                "variant_name": "Platform Engineer — Master",
            },
        )
        self.assertEqual(200, accepted.status_code, accepted.text)

        rendered = self.client.post(
            f"/api/v1/resume-variants/{accepted.json()['id']}/render",
            headers=headers,
        )
        self.assertEqual(201, rendered.status_code, rendered.text)
        self.assertEqual(
            {"ats-modern"},
            {document["template_id"] for document in rendered.json()["documents"]},
        )
        with zipfile.ZipFile(BytesIO(self.document_converter.requests[-1][0])) as archive:
            document_xml = archive.read("word/document.xml")
        self.assertIn(b"PUBLICATIONS", document_xml)
        self.assertIn(b"Reliable Systems Review", document_xml)
        self.assertIn(b"Example Systems", document_xml)
        self.assertIn(b"Own reliable backend services", document_xml)
        self.assertIn(b"Jan 2022", document_xml)
        self.assertIn(b"Present", document_xml)
        self.assertIn("• Built production APIs".encode(), document_xml)
        self.assertIn(b"Universiti Teknologi Malaysia", document_xml)
        self.assertIn(b"Intelligent Document Classification", document_xml)
        self.assertIn("Dean’s List".encode(), document_xml)
        self.assertIn(b"Sep 2020", document_xml)
        self.assertIn(b"Monitorscape", document_xml)
        self.assertIn(b"Designed the event ingestion API", document_xml)
        self.assertIn(b"Python, FastAPI, PostgreSQL, Docker", document_xml)
        self.assertIn(b"Processed 100K events with 99.9% uptime", document_xml)
        self.assertIn(b"Feb 2024", document_xml)
        self.assertIn(b"Framework: Django, FastAPI", document_xml)
        self.assertIn(b"Programming Language: Python, Go", document_xml)

        other_read = self.client.get(
            f"/api/v1/resumes/{source_id}",
            headers={"Authorization": "Bearer other-session"},
        )
        self.assertEqual(404, other_read.status_code)

    def test_resume_import_rejects_unsupported_files_and_requires_auth(self):
        unsupported = self.client.post(
            "/api/v1/resumes/imports",
            headers={"Authorization": "Bearer test-session"},
            files=[("files", ("resume.txt", b"plain text", "text/plain"))],
        )
        unauthenticated = self.client.get("/api/v1/resumes")

        self.assertEqual(201, unsupported.status_code)
        self.assertEqual("rejected", unsupported.json()["items"][0]["status"])
        self.assertEqual(401, unauthenticated.status_code)

    def test_job_match_is_private_and_generates_word_and_pdf(self):
        headers = {"Authorization": "Bearer test-session"}
        imported = self.client.post(
            "/api/v1/resumes/imports",
            headers=headers,
            files=[
                (
                    "files",
                    (
                        "backend-resume.docx",
                        self.resume_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )
        source_id = imported.json()["items"][0]["source"]["id"]
        description = (
            "Python APIs and reliable cloud services. Production Python APIs power reliable "
            "cloud services. Build production Python APIs for reliable cloud platforms."
        )
        matched = self.client.post(
            "/api/v1/job-matches",
            headers=headers,
            data={
                "source_id": source_id,
                "target_role": "Backend Engineer",
                "company": "Example Systems",
                "job_description": description,
            },
        )

        self.assertEqual(201, matched.status_code, matched.text)
        result = matched.json()
        self.assertTrue(result["id"].startswith("jmt_"))
        self.assertEqual("match", result["match_state"])
        self.assertGreaterEqual(result["match_percentage"], 70)
        self.assertTrue(result["can_generate"])

        other_generate = self.client.post(
            f"/api/v1/job-matches/{result['id']}/tailor",
            headers={"Authorization": "Bearer other-session"},
        )
        self.assertEqual(404, other_generate.status_code)

        generated = self.client.post(
            f"/api/v1/job-matches/{result['id']}/tailor",
            headers=headers,
        )
        self.assertEqual(201, generated.status_code, generated.text)
        documents = generated.json()["documents"]
        self.assertEqual(2, len(documents))
        self.assertEqual(
            {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/pdf",
            },
            {document["media_type"] for document in documents},
        )
        for document in documents:
            downloaded = self.client.get(
                f"/api/v1/job-match-documents/{document['id']}/download",
                headers=headers,
            )
            other_download = self.client.get(
                f"/api/v1/job-match-documents/{document['id']}/download",
                headers={"Authorization": "Bearer other-session"},
            )
            self.assertEqual(200, downloaded.status_code)
            self.assertEqual(404, other_download.status_code)

    def test_job_match_accepts_image_ocr_and_blocks_no_match_generation(self):
        headers = {"Authorization": "Bearer test-session"}
        imported = self.client.post(
            "/api/v1/resumes/imports",
            headers=headers,
            files=[
                (
                    "files",
                    (
                        "backend-resume.docx",
                        self.resume_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )
        source_id = imported.json()["items"][0]["source"]["id"]
        image_match = self.client.post(
            "/api/v1/job-matches",
            headers=headers,
            data={"source_id": source_id, "target_role": "Backend Engineer"},
            files=[("files", ("job.png", b"fake image payload", "image/png"))],
        )
        self.assertEqual(201, image_match.status_code, image_match.text)
        self.assertEqual([(b"fake image payload", "job.png")], self.document_converter.ocr_requests)

        no_match = self.client.post(
            "/api/v1/job-matches",
            headers=headers,
            data={
                "source_id": source_id,
                "target_role": "Research Chemist",
                "job_description": (
                    "Lead molecular spectroscopy chromatography synthesis laboratory research. "
                    "Develop polymer formulations, chemical assays, patents, microscopy, and trials."
                ),
            },
        )
        self.assertEqual(201, no_match.status_code, no_match.text)
        self.assertEqual("no_match", no_match.json()["match_state"])
        blocked = self.client.post(
            f"/api/v1/job-matches/{no_match.json()['id']}/tailor",
            headers=headers,
        )
        self.assertEqual(409, blocked.status_code)


if __name__ == "__main__":
    unittest.main()
