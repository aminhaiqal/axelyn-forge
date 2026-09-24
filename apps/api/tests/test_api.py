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


if __name__ == "__main__":
    unittest.main()
