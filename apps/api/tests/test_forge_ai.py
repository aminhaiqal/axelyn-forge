import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from forge.errors import ProviderError

from axelyn_api.forge_ai import generate_forge_ai_response


def resume() -> dict[str, object]:
    return {
        "headline": "Platform Engineer",
        "summary": "Builds reliable cloud platforms.",
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
        "sections": {},
    }


def provider_payload(evidence_id: str = "experience_1_achievements") -> dict[str, object]:
    return {
        "assistant_message": "The resume verifies a measurable deployment result.",
        "citations": [evidence_id],
        "claim_status": "verified",
        "memory": {
            "summary": "Reviewing evidence for a platform engineering role.",
            "confirmed_facts": [
                {
                    "fact": "Reduced deployment time by 40%.",
                    "source": "resume",
                    "evidence_ids": [evidence_id],
                }
            ],
            "rejected_claims": [],
            "open_questions": ["What production scale can be verified?"],
            "decisions": ["Do not add unsupported scale claims."],
        },
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


class RateLimitError(Exception):
    status_code = 429


class FlakyResponses(FakeResponses):
    def __init__(self, payload: dict[str, object], failures: int = 1):
        super().__init__(payload)
        self.failures = failures

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures:
            raise RateLimitError("temporary provider limit")
        return SimpleNamespace(
            output_text=json.dumps(self.payload),
            model="openai/gpt-test",
        )


class ForgeAIProviderTests(unittest.TestCase):
    def test_generates_private_evidence_linked_response_with_bounded_context(self):
        responses = FakeResponses(provider_payload())
        client = SimpleNamespace(responses=responses)
        recent_messages = [
            {"role": "user", "content": f"Message {index}", "citations": []}
            for index in range(20)
        ]

        result = generate_forge_ai_response(
            target_role="Platform Engineer",
            company="Example Systems",
            job_description="Build reliable Python platforms.",
            saved_analysis={"match_percentage": 62},
            resume=resume(),
            memory={
                "summary": "Initial review.",
                "confirmed_facts": [],
                "rejected_claims": [],
                "open_questions": [],
                "decisions": [],
            },
            recent_messages=recent_messages,
            user_message="What evidence is strongest?",
            client=client,
            model="openai/gpt-test",
        )

        self.assertEqual("openai/gpt-test", result["model"])
        self.assertEqual(
            "Senior Engineer at Example Systems — achievements",
            result["citation_details"][0]["label"],
        )
        call = responses.calls[0]
        self.assertFalse(call["store"])
        self.assertTrue(call["extra_body"]["provider"]["zdr"])
        self.assertEqual("deny", call["extra_body"]["provider"]["data_collection"])
        self.assertTrue(call["text"]["format"]["strict"])
        schema = call["text"]["format"]["schema"]
        self.assertIn(
            "experience_1_achievements",
            schema["properties"]["citations"]["items"]["enum"],
        )
        request = json.loads(call["input"])
        self.assertEqual(14, len(request["recentConversation"]))
        self.assertEqual("Message 6", request["recentConversation"][0]["content"])
        self.assertGreater(len(request["verifiedResumeEvidence"]), 2)

    def test_retries_a_transient_provider_failure(self):
        responses = FlakyResponses(provider_payload())
        client = SimpleNamespace(responses=responses)

        with patch("axelyn_api.forge_ai.time.sleep") as sleep:
            result = generate_forge_ai_response(
                target_role="Platform Engineer",
                company=None,
                job_description="Build reliable systems.",
                saved_analysis={},
                resume=resume(),
                memory={
                    "summary": "Initial review.",
                    "confirmed_facts": [],
                    "rejected_claims": [],
                    "open_questions": [],
                    "decisions": [],
                },
                recent_messages=[],
                user_message="Assess the claim.",
                client=client,
                model="openai/gpt-test",
            )

        self.assertEqual("verified", result["claim_status"])
        self.assertEqual(2, len(responses.calls))
        sleep.assert_called_once_with(0.5)

    def test_rejects_claims_that_reference_unknown_evidence(self):
        client = SimpleNamespace(
            responses=FakeResponses(provider_payload("invented_evidence"))
        )

        with self.assertRaisesRegex(ProviderError, "not supplied"):
            generate_forge_ai_response(
                target_role="Platform Engineer",
                company=None,
                job_description="Build reliable systems.",
                saved_analysis={},
                resume=resume(),
                memory={
                    "summary": "Initial review.",
                    "confirmed_facts": [],
                    "rejected_claims": [],
                    "open_questions": [],
                    "decisions": [],
                },
                recent_messages=[],
                user_message="Assess the claim.",
                client=client,
                model="openai/gpt-test",
            )


if __name__ == "__main__":
    unittest.main()
