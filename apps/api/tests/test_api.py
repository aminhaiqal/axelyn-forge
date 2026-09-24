import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from axelyn_api.config import Settings
from axelyn_api.main import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "forge.sqlite3"
        app = create_app(
            Settings(
                environment="test",
                database_path=self.database,
                cors_origins=(),
            )
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

    def test_forge_brief_aligns_evidence_and_is_persisted(self):
        response = self.client.post(
            "/api/v1/forge-briefs",
            json={
                "target_role": "Senior backend engineer",
                "company": "Example Systems",
                "job_description": (
                    "Build Python APIs and distributed systems for a cloud platform. "
                    "Own service reliability, PostgreSQL performance, observability, "
                    "and collaboration across product and infrastructure teams."
                ),
                "career_evidence": (
                    "Built Python APIs for an internal cloud platform used by five teams. "
                    "Improved PostgreSQL query performance and added service observability. "
                    "Partnered with product managers to deliver reliable backend services."
                ),
                "outputs": ["resume", "cover-letter"],
                "consent": True,
            },
        )

        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertTrue(body["id"].startswith("frg_"))
        self.assertEqual("ready", body["status"])
        self.assertGreater(body["coverage_score"], 0)
        self.assertIn("python", body["matched_keywords"])
        self.assertIn("reliable", body["matched_keywords"])
        self.assertTrue(body["evidence_highlights"])

        with sqlite3.connect(self.database) as connection:
            row = connection.execute(
                "SELECT target_role, status FROM forge_briefs WHERE id = ?",
                (body["id"],),
            ).fetchone()
        self.assertEqual(("Senior backend engineer", "ready"), row)

    def test_forge_brief_requires_substantive_source_material(self):
        response = self.client.post(
            "/api/v1/forge-briefs",
            json={
                "target_role": "Engineer",
                "job_description": "Too short",
                "career_evidence": "Also too short",
                "outputs": ["resume"],
                "consent": True,
            },
        )

        self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()
