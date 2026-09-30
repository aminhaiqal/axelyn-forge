import base64
import copy
import json
import sqlite3
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from axelyn_api.config import Settings
from axelyn_api.main import create_app
from axelyn_api.resume_import import draft_payload


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"


class FakeDocumentConverter:
    def __init__(self):
        self.requests: list[tuple[bytes, str]] = []
        self.pdf_requests: list[tuple[bytes, str]] = []
        self.ocr_requests: list[tuple[bytes, str]] = []
        self.normalized_docx = b""

    def docx_to_pdf(self, payload: bytes, filename: str) -> bytes:
        self.requests.append((payload, filename))
        return VALID_PDF

    def pdf_to_docx(self, payload: bytes, filename: str) -> bytes:
        self.pdf_requests.append((payload, filename))
        return self.normalized_docx

    def image_to_text(self, payload: bytes, filename: str) -> str:
        self.ocr_requests.append((payload, filename))
        return (
            "Python APIs and reliable cloud services. Production Python APIs power reliable "
            "cloud services. Build production Python APIs for reliable cloud platforms."
        )


class FakeInterviewBriefGenerator:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "role_summary": "A platform role focused on reliable services.",
            "positioning": "Lead with production API and delivery experience.",
            "coverage": [
                {
                    "requirement": "Reliable delivery",
                    "assessment": "strong",
                    "rationale": "The attached resume supports this area.",
                    "evidence": ["Senior Engineer — achievements"],
                }
            ],
            "questions": [
                {
                    "question": f"Interview question {index}",
                    "interviewer_intent": "Understand the candidate's approach.",
                    "answer_plan": "Explain the context, action, and result.",
                    "evidence": ["Senior Engineer — achievements"],
                }
                for index in range(1, 4)
            ],
            "questions_to_ask": [
                "How is success measured?",
                "What is the current architecture?",
                "What should improve first?",
            ],
            "preparation_actions": ["Review the delivery example."],
            "facts_to_confirm": [],
            "model": "openai/gpt-test",
        }


class FakeResumeDraftGenerator:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        draft = draft_payload(**kwargs)
        if kwargs["display_name"] == "ai-resume":
            draft["summary"] = "AI-structured source summary."
        return draft


class FakeForgeAIGenerator:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        memory = dict(kwargs["memory"])
        memory["summary"] = "The candidate supplied a concrete deployment example for review."
        memory["confirmed_facts"] = [
            {
                "fact": kwargs["user_message"],
                "source": "user",
                "evidence_ids": [],
            }
        ]
        memory["open_questions"] = [
            "What measurable outcome can you defend for this work?"
        ]
        return {
            "assistant_message": (
                "I recorded that as user-confirmed evidence. It is useful context, but a "
                "source document or a defensible project record would make it stronger."
            ),
            "citations": [],
            "citation_details": [],
            "claim_status": "user_confirmed",
            "memory": memory,
            "model": "openai/gpt-test",
        }


class FakeResumeEnhancementGenerator:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        draft = copy.deepcopy(kwargs["resume"])
        before = str(draft.get("summary") or "")
        after = "Platform engineer building reliable Python APIs and cloud services."
        draft["summary"] = after
        return {
            "draft": draft,
            "overview": "Strengthened the summary around verified platform evidence.",
            "gaps": ["Kubernetes scale remains unsupported."],
            "changed_sections": ["Summary"],
            "operations": [
                {
                    "target": "summary",
                    "section": "Summary",
                    "before": before,
                    "after": after,
                    "evidence": [
                        {
                            "id": "profile_summary",
                            "label": "Profile summary",
                            "source": "resume",
                        }
                    ],
                }
            ],
            "model": "openai/gpt-test",
        }


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
    def resume_docx(experience_line: str = "Built production APIs.") -> bytes:
        content_types = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
          <Default Extension="xml" ContentType="application/xml"/>
        </Types>"""
        document = f"""<?xml version="1.0" encoding="UTF-8"?>
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
            <w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>{experience_line}</w:t></w:r></w:p>
          </w:body>
        </w:document>""".encode()
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, payload in (
                ("[Content_Types].xml", content_types),
                ("word/document.xml", document),
            ):
                member = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                member.compress_type = zipfile.ZIP_STORED
                archive.writestr(member, payload)
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
        self.document_converter.normalized_docx = self.resume_docx()
        self.interview_brief_generator = FakeInterviewBriefGenerator()
        self.resume_draft_generator = FakeResumeDraftGenerator()
        self.forge_ai_generator = FakeForgeAIGenerator()
        self.resume_enhancement_generator = FakeResumeEnhancementGenerator()
        app = create_app(
            Settings(
                environment="test",
                database_path=self.database,
                storage_path=self.storage,
                cors_origins=(),
            ),
            authenticate_user=self.authenticate_user,
            document_converter=self.document_converter,
            interview_brief_generator=self.interview_brief_generator,
            resume_draft_generator=self.resume_draft_generator,
            forge_ai_generator=self.forge_ai_generator,
            resume_enhancement_generator=self.resume_enhancement_generator,
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

    def test_private_resume_import_is_immutable_and_exposes_finished_documents(self):
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

        self.assertEqual(201, imported.status_code, imported.text)
        item = imported.json()["items"][0]
        self.assertEqual("stored", item["status"])
        source_id = item["source"]["id"]
        self.assertEqual("ready", item["source"]["status"])
        self.assertIsNone(self.resume_draft_generator.calls[0]["target_role"])

        artifacts_response = self.client.get(
            "/api/v1/resume-source-artifacts", headers=headers
        )
        other_artifacts = self.client.get(
            "/api/v1/resume-source-artifacts",
            headers={"Authorization": "Bearer other-session"},
        )
        self.assertEqual(200, artifacts_response.status_code)
        self.assertEqual([], other_artifacts.json())
        artifacts = {
            artifact["kind"]: artifact for artifact in artifacts_response.json()
        }
        self.assertEqual({"resume_docx", "resume_pdf"}, set(artifacts))
        downloaded_artifacts = {}
        for kind, artifact in artifacts.items():
            download = self.client.get(
                f"/api/v1/resume-source-artifacts/{artifact['id']}/download",
                headers=headers,
            )
            other_download = self.client.get(
                f"/api/v1/resume-source-artifacts/{artifact['id']}/download",
                headers={"Authorization": "Bearer other-session"},
            )
            self.assertEqual(200, download.status_code)
            self.assertEqual(404, other_download.status_code)
            self.assertEqual("private, no-store", download.headers["cache-control"])
            downloaded_artifacts[kind] = download.content
        self.assertTrue(downloaded_artifacts["resume_docx"].startswith(b"PK"))
        self.assertEqual(VALID_PDF, downloaded_artifacts["resume_pdf"])
        self.assertEqual("backend-resume.docx", artifacts["resume_docx"]["filename"])
        self.assertEqual("backend-resume.pdf", artifacts["resume_pdf"]["filename"])
        with zipfile.ZipFile(BytesIO(downloaded_artifacts["resume_docx"])) as archive:
            template_xml = archive.read("word/document.xml")
        self.assertIn(b"<w:sdt>", template_xml)
        self.assertIn(b'w:val="resume.full_name"', template_xml)
        self.assertIn(b'w:val="rendered_sections.experience.0"', template_xml)

        internal_rows = self.client.app.state.resume_store.list_source_artifacts(
            "user_test_123", source_id
        )
        internal_artifacts = {row["kind"]: row for row in internal_rows}
        self.assertEqual(
            {
                "source_docx",
                "resume_docx",
                "resume_pdf",
                "resume_json",
                "resume_schema",
            },
            set(internal_artifacts),
        )
        object_store = self.client.app.state.object_store
        self.assertEqual(
            self.resume_docx(),
            object_store.get(internal_artifacts["source_docx"]["object_key"]),
        )
        resume_json = json.loads(
            object_store.get(internal_artifacts["resume_json"]["object_key"])
        )
        resume_schema = json.loads(
            object_store.get(internal_artifacts["resume_schema"]["object_key"])
        )
        Draft202012Validator.check_schema(resume_schema)
        Draft202012Validator(resume_schema).validate(resume_json)
        self.assertEqual("Taylor Example", resume_json["resume"]["full_name"])
        self.assertEqual(
            "Taylor Example",
            resume_json["template_values"]["resume.full_name"],
        )
        for kind in ("source_docx", "resume_json", "resume_schema"):
            hidden = self.client.get(
                f"/api/v1/resume-source-artifacts/{internal_artifacts[kind]['id']}/download",
                headers=headers,
            )
            self.assertEqual(404, hidden.status_code)

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

        source_row = self.client.app.state.resume_store.get_source(
            "user_test_123", source_id
        )
        self.assertIsNotNone(source_row)
        stored_draft = json.loads(object_store.get(source_row["draft_object_key"]))
        editable_payload = {
            **stored_draft,
            "display_name": "Backend resume",
            "target_role": None,
            "full_name": "Taylor Example",
            "email_address": "taylor@example.com",
            "phone_number": "+60 12-345 6789",
            "location": "Kuala Lumpur, Malaysia",
        }
        saved = self.client.put(
            f"/api/v1/resumes/{source_id}/draft",
            headers=headers,
            json=editable_payload,
        )
        accepted = self.client.post(
            f"/api/v1/resumes/{source_id}/accept",
            headers=headers,
            json={
                **editable_payload,
                "variant_name": "Backend Engineer - Master",
            },
        )
        photo = self.client.put(
            f"/api/v1/resumes/{source_id}/profile-photo",
            headers=headers,
            files={"photo": ("photo.png", b"not-needed", "image/png")},
        )
        detail = self.client.get(f"/api/v1/resumes/{source_id}", headers=headers)
        editable_word = self.client.get(
            f"/api/v1/resumes/{source_id}/editable.docx", headers=headers
        )
        for response in (saved, accepted, photo, detail, editable_word):
            self.assertEqual(409, response.status_code, response.text)
            self.assertIn("Delete this resume", response.json()["detail"])
        self.assertEqual(1, len(self.document_converter.requests))
        self.assertTrue(self.document_converter.requests[0][0].startswith(b"PK"))

        deleted = self.client.delete(f"/api/v1/resumes/{source_id}", headers=headers)
        self.assertEqual(204, deleted.status_code)
        self.assertEqual(
            [],
            self.client.get(
                "/api/v1/resume-source-artifacts", headers=headers
            ).json(),
        )
        for artifact in internal_artifacts.values():
            missing = self.client.get(
                f"/api/v1/resume-source-artifacts/{artifact['id']}/download",
                headers=headers,
            )
            self.assertEqual(404, missing.status_code)

    def test_import_builds_artifacts_from_the_ai_structured_draft(self):
        headers = {"Authorization": "Bearer test-session"}
        imported = self.client.post(
            "/api/v1/resumes/imports",
            headers=headers,
            files=[
                (
                    "files",
                    (
                        "ai-resume.docx",
                        self.resume_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(201, imported.status_code, imported.text)
        source_id = imported.json()["items"][0]["source"]["id"]
        source_row = self.client.app.state.resume_store.get_source(
            "user_test_123", source_id
        )
        self.assertIsNotNone(source_row)
        draft = json.loads(
            self.client.app.state.object_store.get(source_row["draft_object_key"])
        )
        self.assertEqual(
            "AI-structured source summary.",
            draft["summary"],
        )

    def test_pdf_import_creates_finished_word_and_pdf_files(self):
        headers = {"Authorization": "Bearer test-session"}
        imported = self.client.post(
            "/api/v1/resumes/imports",
            headers=headers,
            files=[("files", ("backend-resume.pdf", self.resume_pdf(), "application/pdf"))],
        )

        self.assertEqual(201, imported.status_code, imported.text)
        source = imported.json()["items"][0]["source"]
        self.assertEqual("application/pdf", source["media_type"])
        self.assertEqual("ready", source["status"])
        self.assertEqual(
            [(self.resume_pdf(), "backend-resume.pdf")],
            self.document_converter.pdf_requests,
        )
        artifacts = self.client.get(
            "/api/v1/resume-source-artifacts", headers=headers
        ).json()
        self.assertEqual(
            {"resume_docx", "resume_pdf"},
            {artifact["kind"] for artifact in artifacts},
        )
        finished_word = next(item for item in artifacts if item["kind"] == "resume_docx")
        finished_pdf = next(item for item in artifacts if item["kind"] == "resume_pdf")
        word_download = self.client.get(
            f"/api/v1/resume-source-artifacts/{finished_word['id']}/download",
            headers=headers,
        )
        pdf_download = self.client.get(
            f"/api/v1/resume-source-artifacts/{finished_pdf['id']}/download",
            headers=headers,
        )
        self.assertEqual(VALID_PDF, pdf_download.content)
        with zipfile.ZipFile(BytesIO(word_download.content)) as archive:
            document_xml = archive.read("word/document.xml")
        self.assertIn(b"Taylor Example", document_xml)
        self.assertIn(b"Built production APIs", document_xml)
        self.assertEqual(1, len(self.document_converter.requests))

    def test_pdf_import_preserves_long_resume_section_lines(self):
        headers = {"Authorization": "Bearer test-session"}
        long_line = "Designed reliable production systems with documented tradeoffs. " * 50
        self.assertGreater(len(long_line), 2_000)
        self.document_converter.normalized_docx = self.resume_docx(long_line)

        imported = self.client.post(
            "/api/v1/resumes/imports",
            headers=headers,
            files=[("files", ("long-resume.pdf", self.resume_pdf(), "application/pdf"))],
        )

        self.assertEqual(201, imported.status_code, imported.text)
        source_id = imported.json()["items"][0]["source"]["id"]
        source_row = self.client.app.state.resume_store.get_source(
            "user_test_123", source_id
        )
        self.assertIsNotNone(source_row)
        draft = json.loads(
            self.client.app.state.object_store.get(source_row["draft_object_key"])
        )
        experience = draft["sections"]["experience"]
        self.assertIn(long_line.strip(), experience[-1])

    def test_manual_resume_form_keeps_custom_sections_and_uses_standard_template(self):
        headers = {"Authorization": "Bearer test-session"}
        templates = self.client.get("/api/v1/resume-templates")

        self.assertEqual(200, templates.status_code)
        self.assertEqual(
            ["ats-classic"],
            [item["id"] for item in templates.json()],
        )

        created = self.client.post(
            "/api/v1/resumes",
            headers=headers,
            json={
                "display_name": "First resume",
                "target_role": "Platform Engineer",
                "template_id": "ats-classic",
                "full_name": "Taylor Example",
                "headline": "Platform Engineer",
                "email_address": "taylor@example.com",
                "phone_number": "+60 12-345 6789",
                "location": "Kuala Lumpur, Malaysia",
                "linkedin_url": "https://linkedin.com/in/taylor-example",
                "portfolio_url": "https://taylor.example",
                "github_url": "https://github.com/taylor-example",
                "other_professional_link": "https://kaggle.com/taylor-example",
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
                        "category": "Backend Framework",
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
        self.assertEqual("ats-classic", source["draft"]["template_id"])
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
            "Backend Framework",
            source["draft"]["skill_categories"][0]["category"],
        )
        self.assertEqual(
            "Publications", source["draft"]["custom_sections"][0]["title"]
        )

        photo_payload = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            "+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        uploaded_photo = self.client.put(
            f"/api/v1/resumes/{source_id}/profile-photo",
            headers=headers,
            files={"photo": ("taylor.png", photo_payload, "image/png")},
        )
        self.assertEqual(200, uploaded_photo.status_code, uploaded_photo.text)
        source = uploaded_photo.json()
        self.assertEqual("taylor.png", source["draft"]["profile_photo_filename"])
        self.assertEqual("image/png", source["draft"]["profile_photo_media_type"])
        downloaded_photo = self.client.get(
            f"/api/v1/resumes/{source_id}/profile-photo", headers=headers
        )
        other_photo = self.client.get(
            f"/api/v1/resumes/{source_id}/profile-photo",
            headers={"Authorization": "Bearer other-session"},
        )
        self.assertEqual(photo_payload, downloaded_photo.content)
        self.assertEqual("private, no-store", downloaded_photo.headers["cache-control"])
        self.assertEqual(404, other_photo.status_code)

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
            {"ats-classic"},
            {document["template_id"] for document in rendered.json()["documents"]},
        )
        with zipfile.ZipFile(BytesIO(self.document_converter.requests[-1][0])) as archive:
            document_xml = archive.read("word/document.xml")
        self.assertIn(b"PUBLICATIONS", document_xml)
        self.assertIn(b"Reliable Systems Review", document_xml)
        self.assertIn(b"taylor@example.com", document_xml)
        self.assertIn(b"Kuala Lumpur, Malaysia", document_xml)
        self.assertIn(b"https://github.com/taylor-example", document_xml)
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

        removed_photo = self.client.delete(
            f"/api/v1/resumes/{source_id}/profile-photo", headers=headers
        )
        missing_photo = self.client.get(
            f"/api/v1/resumes/{source_id}/profile-photo", headers=headers
        )
        self.assertEqual(204, removed_photo.status_code)
        self.assertEqual(404, missing_photo.status_code)

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

    def test_job_tracker_is_private_and_preserves_resume_attachment_snapshot(self):
        headers = {"Authorization": "Bearer test-session"}
        other_headers = {"Authorization": "Bearer other-session"}
        created_resume = self.client.post(
            "/api/v1/resumes",
            headers=headers,
            json={
                "display_name": "Platform resume",
                "target_role": "Platform Engineer",
                "full_name": "Taylor Example",
                "headline": "Platform Engineer",
                "email_address": "taylor@example.com",
                "phone_number": "+60 12-345 6789",
                "location": "Kuala Lumpur, Malaysia",
                "summary": "Builds reliable cloud platforms.",
            },
        )
        self.assertEqual(201, created_resume.status_code, created_resume.text)
        source = created_resume.json()
        accepted = self.client.post(
            f"/api/v1/resumes/{source['id']}/accept",
            headers=headers,
            json={
                **source["draft"],
                "display_name": "Platform resume",
                "target_role": "Platform Engineer",
                "variant_name": "Platform Engineer — Master",
            },
        )
        self.assertEqual(200, accepted.status_code, accepted.text)
        variant = accepted.json()

        created = self.client.post(
            "/api/v1/job-applications",
            headers=headers,
            json={
                "company_name": "Example Systems",
                "job_title": "Senior Platform Engineer",
                "job_url": "https://example.com/jobs/platform",
                "location": "Kuala Lumpur, Malaysia",
                "work_arrangement": "Hybrid",
                "employment_type": "Full-time",
                "status": "applied",
                "applied_on": "2026-09-28",
                "next_action_on": "2026-10-05",
                "notes": "Referred by the infrastructure team.",
                "resume_source_id": source["id"],
                "resume_variant_id": variant["id"],
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        application = created.json()
        self.assertTrue(application["id"].startswith("job_"))
        self.assertEqual("Platform Engineer — Master", application["resume_name"])
        self.assertEqual("Platform Engineer", application["resume_target_role"])
        with sqlite3.connect(self.database) as connection:
            snapshot_key = connection.execute(
                "SELECT resume_snapshot_object_key FROM job_applications WHERE id = ?",
                (application["id"],),
            ).fetchone()[0]
        snapshot_path = self.storage / snapshot_key
        self.assertTrue(snapshot_path.is_file())
        self.assertEqual([], self.client.get(
            "/api/v1/job-applications", headers=other_headers
        ).json())

        generated_brief = self.client.post(
            f"/api/v1/job-applications/{application['id']}/interview-brief",
            headers=headers,
            json={
                "job_description": "Build reliable Python platforms.",
                "focus": "Technical interview",
            },
        )
        self.assertEqual(200, generated_brief.status_code, generated_brief.text)
        brief = generated_brief.json()
        self.assertTrue(brief["id"].startswith("brief_"))
        self.assertEqual(application["id"], brief["application_id"])
        self.assertEqual("openai/gpt-test", brief["model"])
        self.assertEqual(3, len(brief["questions"]))
        generator_call = self.interview_brief_generator.calls[-1]
        self.assertEqual("Senior Platform Engineer", generator_call["application"]["job_title"])
        self.assertEqual("Taylor Example", generator_call["resume"]["full_name"])
        self.assertEqual("Technical interview", generator_call["focus"])
        with sqlite3.connect(self.database) as connection:
            brief_key = connection.execute(
                """
                SELECT object_key FROM job_application_interview_briefs
                WHERE application_id = ?
                """,
                (application["id"],),
            ).fetchone()[0]
        brief_path = self.storage / brief_key
        self.assertTrue(brief_path.is_file())
        self.assertEqual(
            404,
            self.client.get(
                f"/api/v1/job-applications/{application['id']}/interview-brief",
                headers=other_headers,
            ).status_code,
        )
        loaded_brief = self.client.get(
            f"/api/v1/job-applications/{application['id']}/interview-brief",
            headers=headers,
        )
        self.assertEqual(brief, loaded_brief.json())

        other_update = self.client.put(
            f"/api/v1/job-applications/{application['id']}",
            headers=other_headers,
            json={
                "company_name": "Changed",
                "job_title": "Changed",
                "status": "rejected",
            },
        )
        other_delete = self.client.delete(
            f"/api/v1/job-applications/{application['id']}",
            headers=other_headers,
        )
        self.assertEqual(404, other_update.status_code)
        self.assertEqual(404, other_delete.status_code)

        updated = self.client.put(
            f"/api/v1/job-applications/{application['id']}",
            headers=headers,
            json={
                "company_name": application["company_name"],
                "job_title": application["job_title"],
                "job_url": application["job_url"],
                "location": application["location"],
                "work_arrangement": application["work_arrangement"],
                "employment_type": application["employment_type"],
                "status": "interview",
                "applied_on": application["applied_on"],
                "next_action_on": "2026-10-08",
                "notes": "Technical interview booked.",
            },
        )
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual("interview", updated.json()["status"])
        self.assertEqual(variant["id"], updated.json()["resume_variant_id"])

        removed_source = self.client.delete(
            f"/api/v1/resumes/{source['id']}", headers=headers
        )
        self.assertEqual(204, removed_source.status_code)
        preserved = self.client.get(
            "/api/v1/job-applications", headers=headers
        ).json()[0]
        self.assertIsNone(preserved["resume_source_id"])
        self.assertIsNone(preserved["resume_variant_id"])
        self.assertEqual("Platform Engineer — Master", preserved["resume_name"])
        self.assertTrue(snapshot_path.is_file())

        deleted = self.client.delete(
            f"/api/v1/job-applications/{application['id']}", headers=headers
        )
        self.assertEqual(204, deleted.status_code)
        self.assertFalse(snapshot_path.exists())
        self.assertFalse(brief_path.exists())
        self.assertEqual([], self.client.get(
            "/api/v1/job-applications", headers=headers
        ).json())

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

        history = self.client.get("/api/v1/job-matches", headers=headers)
        other_history = self.client.get(
            "/api/v1/job-matches",
            headers={"Authorization": "Bearer other-session"},
        )
        detail = self.client.get(
            f"/api/v1/job-matches/{result['id']}", headers=headers
        )
        other_detail = self.client.get(
            f"/api/v1/job-matches/{result['id']}",
            headers={"Authorization": "Bearer other-session"},
        )
        self.assertEqual(200, history.status_code, history.text)
        self.assertEqual([], other_history.json())
        self.assertEqual(1, len(history.json()))
        self.assertEqual("Backend Engineer", history.json()[0]["target_role"])
        self.assertEqual("Example Systems", history.json()[0]["company"])
        self.assertEqual("backend-resume", history.json()[0]["resume_name"])
        self.assertEqual("Match", history.json()[0]["match_label"])
        self.assertFalse(history.json()[0]["has_documents"])
        self.assertEqual(200, detail.status_code, detail.text)
        self.assertEqual(result["reasons"], detail.json()["reasons"])
        self.assertEqual([], detail.json()["documents"])
        self.assertEqual(404, other_detail.status_code)

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
        updated_history = self.client.get(
            "/api/v1/job-matches", headers=headers
        ).json()
        reopened = self.client.get(
            f"/api/v1/job-matches/{result['id']}", headers=headers
        ).json()
        self.assertTrue(updated_history[0]["has_documents"])
        self.assertEqual(2, len(reopened["documents"]))
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

    def test_forge_ai_keeps_private_full_history_and_compressed_memory(self):
        headers = {"Authorization": "Bearer test-session"}
        other_headers = {"Authorization": "Bearer other-session"}
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
        matched = self.client.post(
            "/api/v1/job-matches",
            headers=headers,
            data={
                "source_id": source_id,
                "target_role": "Platform Engineer",
                "company": "Example Systems",
                "job_description": (
                    "Build Python APIs and Kubernetes services for reliable cloud platforms. "
                    "Own production operations, observability, and delivery outcomes."
                ),
            },
        )
        self.assertEqual(201, matched.status_code, matched.text)
        match_id = matched.json()["id"]

        self.assertEqual(
            [], self.client.get("/api/v1/forge-ai/threads", headers=headers).json()
        )
        private_create = self.client.post(
            "/api/v1/forge-ai/threads",
            headers=other_headers,
            json={"match_id": match_id},
        )
        self.assertEqual(404, private_create.status_code)

        created = self.client.post(
            "/api/v1/forge-ai/threads",
            headers=headers,
            json={"match_id": match_id},
        )
        self.assertEqual(201, created.status_code, created.text)
        thread = created.json()
        self.assertTrue(thread["id"].startswith("fai_"))
        self.assertEqual(match_id, thread["match_id"])
        self.assertEqual(1, thread["memory_version"])
        self.assertEqual(1, len(thread["messages"]))
        self.assertEqual("assistant", thread["messages"][0]["role"])

        reopened = self.client.post(
            "/api/v1/forge-ai/threads",
            headers=headers,
            json={"match_id": match_id},
        )
        self.assertEqual(1, len(reopened.json()["messages"]))
        self.assertEqual(
            404,
            self.client.get(
                f"/api/v1/forge-ai/threads/{thread['id']}", headers=other_headers
            ).status_code,
        )

        detailed_fact = (
            "I personally deployed the service to Kubernetes, added production observability, "
            "and owned the release incident review. "
            + "The supporting project record contains exact implementation detail. " * 90
        ).strip()
        reply = self.client.post(
            f"/api/v1/forge-ai/threads/{thread['id']}/messages",
            headers=headers,
            json={"content": detailed_fact},
        )
        self.assertEqual(201, reply.status_code, reply.text)
        updated = reply.json()
        self.assertEqual(2, updated["memory_version"])
        self.assertEqual(3, len(updated["messages"]))
        self.assertEqual(detailed_fact, updated["messages"][1]["content"])
        self.assertEqual("user_confirmed", updated["messages"][2]["claim_status"])
        self.assertEqual(detailed_fact, updated["memory"]["confirmed_facts"][0]["fact"])
        self.assertEqual("user", updated["memory"]["confirmed_facts"][0]["source"])
        self.assertEqual(detailed_fact, self.forge_ai_generator.calls[-1]["user_message"])

        listed = self.client.get(
            "/api/v1/forge-ai/threads", headers=headers
        ).json()
        self.assertEqual(1, len(listed))
        self.assertEqual(3, listed[0]["message_count"])
        self.assertEqual(updated["current_score"], listed[0]["current_score"])
        self.assertEqual(
            404,
            self.client.post(
                f"/api/v1/forge-ai/threads/{thread['id']}/messages",
                headers=other_headers,
                json={"content": "Try to access another user's evidence case."},
            ).status_code,
        )

        with sqlite3.connect(self.database) as connection:
            stored = connection.execute(
                "SELECT content FROM forge_ai_messages WHERE thread_id = ? AND role = 'user'",
                (thread["id"],),
            ).fetchone()[0]
        self.assertEqual(detailed_fact, stored)

        private_enhance = self.client.post(
            f"/api/v1/forge-ai/threads/{thread['id']}/enhance",
            headers=other_headers,
        )
        self.assertEqual(404, private_enhance.status_code)
        enhanced = self.client.post(
            f"/api/v1/forge-ai/threads/{thread['id']}/enhance",
            headers=headers,
        )
        self.assertEqual(201, enhanced.status_code, enhanced.text)
        enhancement = enhanced.json()
        self.assertEqual("Summary", enhancement["changed_sections"][0])
        self.assertEqual(1, len(enhancement["operations"]))
        self.assertEqual(2, len(enhancement["documents"]))
        self.assertEqual("openai/gpt-test", enhancement["model"])
        self.assertEqual(
            detailed_fact,
            self.resume_enhancement_generator.calls[-1]["memory"]["confirmed_facts"][0]["fact"],
        )
        for document in enhancement["documents"]:
            self.assertIn("forge-enhanced-resume", document["filename"])
            downloaded = self.client.get(
                f"/api/v1/job-match-documents/{document['id']}/download",
                headers=headers,
            )
            private_download = self.client.get(
                f"/api/v1/job-match-documents/{document['id']}/download",
                headers=other_headers,
            )
            self.assertEqual(200, downloaded.status_code)
            self.assertEqual(404, private_download.status_code)
        reloaded_thread = self.client.get(
            f"/api/v1/forge-ai/threads/{thread['id']}", headers=headers
        ).json()
        self.assertEqual(2, len(reloaded_thread["documents"]))
        self.assertEqual(4, len(reloaded_thread["messages"]))
        self.assertIn("Applied changes", reloaded_thread["messages"][-1]["content"])
        self.assertEqual(
            "Profile summary",
            reloaded_thread["messages"][-1]["citations"][0]["label"],
        )

        with sqlite3.connect(self.database) as connection:
            draft_key = connection.execute(
                "SELECT draft_object_key FROM resume_sources WHERE id = ?",
                (source_id,),
            ).fetchone()[0]
        original_draft = json.loads((self.storage / draft_key).read_text())
        self.assertNotEqual(
            "Platform engineer building reliable Python APIs and cloud services.",
            original_draft["summary"],
        )


if __name__ == "__main__":
    unittest.main()
