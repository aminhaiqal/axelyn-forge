import json
import unittest
from types import SimpleNamespace

from forge.errors import ProviderError

from axelyn_api.resume_enhancer import (
    ResumeEnhancementUnavailable,
    generate_resume_enhancement,
)


def resume() -> dict[str, object]:
    return {
        "headline": "Platform Engineer",
        "summary": "Builds reliable cloud platforms.",
        "sections": {},
        "experience_entries": [
            {
                "company_name": "Example Systems",
                "job_title": "Senior Engineer",
                "responsibilities": "Designed production Python APIs.",
                "achievements": "Reduced deployment time by 40%.",
            }
        ],
        "project_entries": [],
        "education_entries": [],
        "skill_categories": [{"category": "Cloud", "skills": ["AWS", "Docker"]}],
        "custom_sections": [],
    }


def plan(value: object = "Platform engineer building reliable cloud services.") -> dict[str, object]:
    return {
        "overview": "Strengthened the role positioning.",
        "operations": [
            {
                "target": "summary",
                "value": value,
                "evidence_ids": ["profile_summary", "experience_1_responsibilities"],
            }
        ],
        "gaps": ["Kubernetes remains unsupported."],
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


class ResumeEnhancerTests(unittest.TestCase):
    def test_applies_private_evidence_cited_rewrite(self):
        responses = FakeResponses(plan())
        result = generate_resume_enhancement(
            target_role="Platform Engineer",
            company="Example Systems",
            job_description="Build reliable cloud services and Python APIs.",
            saved_analysis={"match_percentage": 62},
            resume=resume(),
            memory={
                "summary": "Review in progress.",
                "confirmed_facts": [],
                "rejected_claims": [],
                "open_questions": [],
                "decisions": [],
            },
            client=SimpleNamespace(responses=responses),
            model="openai/gpt-test",
        )

        self.assertEqual(
            "Platform engineer building reliable cloud services.",
            result["draft"]["summary"],
        )
        self.assertEqual(["Summary"], result["changed_sections"])
        self.assertEqual(2, len(result["operations"][0]["evidence"]))
        call = responses.calls[0]
        self.assertFalse(call["store"])
        self.assertTrue(call["extra_body"]["provider"]["zdr"])
        self.assertEqual("deny", call["extra_body"]["provider"]["data_collection"])
        schema = call["text"]["format"]["schema"]
        self.assertIn(
            "summary",
            schema["properties"]["operations"]["items"]["properties"]["target"]["enum"],
        )

    def test_rejects_value_type_change(self):
        with self.assertRaisesRegex(ProviderError, "value type"):
            generate_resume_enhancement(
                target_role="Platform Engineer",
                company=None,
                job_description="Build cloud services.",
                saved_analysis={},
                resume=resume(),
                memory={"confirmed_facts": []},
                client=SimpleNamespace(responses=FakeResponses(plan(["invalid"]))),
                model="openai/gpt-test",
            )

    def test_stops_when_no_defensible_rewrite_exists(self):
        empty = {"overview": "No safe rewrite.", "operations": [], "gaps": ["No evidence."]}
        with self.assertRaises(ResumeEnhancementUnavailable):
            generate_resume_enhancement(
                target_role="Platform Engineer",
                company=None,
                job_description="Build cloud services.",
                saved_analysis={},
                resume=resume(),
                memory={"confirmed_facts": []},
                client=SimpleNamespace(responses=FakeResponses(empty)),
                model="openai/gpt-test",
            )

    def test_preserves_bullet_structure_for_imported_content(self):
        imported = resume()
        imported["sections"] = {
            "projects": ["Monitoring platform", "- Built reliable ingestion APIs."],
        }
        payload = {
            "overview": "Clarified one imported project bullet.",
            "operations": [
                {
                    "target": "imported.projects.2",
                    "value": "Built reliable ingestion APIs for public data sources.",
                    "evidence_ids": ["legacy_projects_2"],
                }
            ],
            "gaps": [],
        }
        result = generate_resume_enhancement(
            target_role="Platform Engineer",
            company=None,
            job_description="Build reliable ingestion services.",
            saved_analysis={},
            resume=imported,
            memory={"confirmed_facts": []},
            client=SimpleNamespace(responses=FakeResponses(payload)),
            model="openai/gpt-test",
        )

        self.assertEqual(
            "• Built reliable ingestion APIs for public data sources.",
            result["draft"]["sections"]["projects"][1],
        )


if __name__ == "__main__":
    unittest.main()
