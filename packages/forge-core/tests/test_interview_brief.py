import json
import unittest

from forge.errors import ProviderError
from forge.interview_brief import (
    InterviewBriefInputError,
    build_interview_evidence_catalog,
    generate_interview_brief,
)

from .fakes import FakeOpenAIClient, FakeOpenAIResponse


def resume():
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


def brief(evidence_id="experience_1_achievements"):
    return {
        "role_summary": "A platform role focused on reliable services.",
        "positioning": "Lead with production API and deployment experience.",
        "coverage": [
            {
                "requirement": "Reliable delivery",
                "assessment": "strong",
                "rationale": "The resume records a measurable deployment improvement.",
                "evidenceIds": [evidence_id],
            }
        ],
        "questions": [
            {
                "question": f"Question {index}",
                "interviewer_intent": "Understand the candidate's approach.",
                "answer_plan": "Describe the context, action, and verified result.",
                "evidenceIds": [evidence_id],
            }
            for index in range(1, 4)
        ],
        "questions_to_ask": ["How is success measured?", "What is the current architecture?", "What should improve first?"],
        "preparation_actions": ["Review the deployment example."],
        "facts_to_confirm": [],
    }


class InterviewBriefTests(unittest.TestCase):
    def test_catalog_builds_addressable_verified_evidence(self):
        catalog = build_interview_evidence_catalog(resume())
        identifiers = {item["id"] for item in catalog}

        self.assertIn("profile_summary", identifiers)
        self.assertIn("experience_1_responsibilities", identifiers)
        self.assertIn("experience_1_achievements", identifiers)
        self.assertIn("skills_1", identifiers)

    def test_generates_private_structured_brief_and_expands_evidence(self):
        client = FakeOpenAIClient(
            FakeOpenAIResponse(brief(), model="openai/gpt-test")
        )

        result = generate_interview_brief(
            application={
                "company_name": "Example Systems",
                "job_title": "Platform Engineer",
                "status": "interview",
            },
            resume=resume(),
            job_description="Build reliable Python services.",
            model="openai/gpt-test",
            client=client,
        )

        self.assertEqual("openai/gpt-test", result["model"])
        self.assertEqual(
            ["Senior Engineer at Example Systems — achievements"],
            result["coverage"][0]["evidence"],
        )
        self.assertNotIn("evidenceIds", result["coverage"][0])
        call = client.responses.calls[0]
        self.assertFalse(call["store"])
        self.assertNotIn("verbosity", call["text"])
        self.assertEqual(
            {
                "provider": {
                    "zdr": True,
                    "data_collection": "deny",
                    "require_parameters": True,
                }
            },
            call["extra_body"],
        )
        request = json.loads(call["input"])
        self.assertEqual("Example Systems", request["application"]["company"])
        self.assertGreater(len(request["verifiedResumeEvidence"]), 2)

    def test_rejects_unknown_evidence_reference(self):
        client = FakeOpenAIClient(FakeOpenAIResponse(brief("invented_fact")))

        with self.assertRaisesRegex(ProviderError, "invalid interview brief"):
            generate_interview_brief(
                application={"company_name": "Example", "job_title": "Engineer"},
                resume=resume(),
                client=client,
            )

    def test_rejects_duplicate_evidence_reference(self):
        duplicate = brief()
        duplicate["coverage"][0]["evidenceIds"] *= 2
        client = FakeOpenAIClient(FakeOpenAIResponse(duplicate))

        with self.assertRaisesRegex(ProviderError, "duplicate interview-brief"):
            generate_interview_brief(
                application={"company_name": "Example", "job_title": "Engineer"},
                resume=resume(),
                client=client,
            )

    def test_rejects_supported_coverage_without_evidence(self):
        unsupported = brief()
        unsupported["coverage"][0]["evidenceIds"] = []
        client = FakeOpenAIClient(FakeOpenAIResponse(unsupported))

        with self.assertRaisesRegex(ProviderError, "unsupported interview-brief"):
            generate_interview_brief(
                application={"company_name": "Example", "job_title": "Engineer"},
                resume=resume(),
                client=client,
            )

    def test_requires_meaningful_resume_evidence(self):
        with self.assertRaisesRegex(InterviewBriefInputError, "attached resume needs"):
            generate_interview_brief(
                application={"company_name": "Example", "job_title": "Engineer"},
                resume={},
                client=FakeOpenAIClient(FakeOpenAIResponse(brief())),
            )


if __name__ == "__main__":
    unittest.main()
