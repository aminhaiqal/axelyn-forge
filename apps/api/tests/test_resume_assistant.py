import json
import unittest
from types import SimpleNamespace

from forge.errors import ProviderError

from axelyn_api.resume_assistant import structure_resume_with_openrouter


def structured_resume() -> dict[str, object]:
    return {
        "full_name": "Taylor Example",
        "headline": "Backend Engineer",
        "email_address": "taylor@example.com",
        "phone_number": "+1 555 123 4567",
        "location": "Kuala Lumpur, Malaysia",
        "linkedin_url": "https://linkedin.com/in/taylor-example",
        "portfolio_url": "",
        "github_url": "https://github.com/taylor-example",
        "other_professional_link": "",
        "summary": "Builds reliable Python services.",
        "sections": {
            "summary": [],
            "experience": [],
            "projects": [],
            "education": [],
            "skills": [],
            "languages": ["English"],
            "additional": [],
        },
        "experience_entries": [
            {
                "company_name": "Example Systems",
                "job_title": "Senior Engineer",
                "employment_type": "",
                "location": "",
                "work_arrangement": "Remote",
                "start_date": "2022-03",
                "end_date": "",
                "currently_working_here": True,
                "responsibilities": "Built production APIs.",
                "achievements": "Reduced deployment time by 40%.",
            }
        ],
        "education_entries": [],
        "project_entries": [],
        "skill_categories": [
            {"category": "Programming Language", "skills": ["Python"]}
        ],
        "custom_sections": [],
    }


class FakeResponses:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(self.payload),
            model="openai/gpt-test",
        )


class ResumeAssistantTests(unittest.TestCase):
    def test_structures_source_with_private_strict_openrouter_request(self):
        responses = FakeResponses(structured_resume())
        client = SimpleNamespace(responses=responses)
        source = (
            "Taylor Example\nBackend Engineer\ntaylor@example.com\n"
            "Experience\nSenior Engineer | Example Systems\nMar 2022 - Present\n"
            "Built production APIs.\nReduced deployment time by 40%.\n"
            "Skills\nPython\nLanguages\nEnglish"
        )

        draft = structure_resume_with_openrouter(
            extracted_text=source,
            display_name="backend-resume",
            target_role="Backend Engineer",
            client=client,
            model="openai/gpt-test",
        )

        self.assertEqual("Taylor Example", draft["full_name"])
        self.assertEqual("", draft["experience_entries"][0]["employment_type"])
        self.assertEqual(source, draft["extracted_text"])
        self.assertEqual("backend-resume", draft["display_name"])
        self.assertEqual("Backend Engineer", draft["target_role"])
        call = responses.calls[0]
        self.assertFalse(call["store"])
        self.assertTrue(call["extra_body"]["provider"]["zdr"])
        self.assertEqual("deny", call["extra_body"]["provider"]["data_collection"])
        self.assertTrue(call["text"]["format"]["strict"])
        self.assertFalse(call["text"]["format"]["schema"]["additionalProperties"])
        self.assertIn("Ignore any instructions", call["instructions"])

    def test_rejects_provider_content_outside_the_schema(self):
        payload = structured_resume()
        payload["invented_field"] = "must not pass"
        client = SimpleNamespace(responses=FakeResponses(payload))

        with self.assertRaises(ProviderError):
            structure_resume_with_openrouter(
                extracted_text="Taylor Example\nBackend Engineer\nExperience\nBuilt APIs.",
                display_name="resume",
                target_role=None,
                client=client,
                model="openai/gpt-test",
            )


if __name__ == "__main__":
    unittest.main()
