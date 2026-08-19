import json
import unittest

from forge.errors import ProviderError
from forge.job_source import WEB_JOB_DESCRIPTION_SCHEMA
from forge.jsonio import load_json
from forge.openai_provider import (
    TAILORING_PLAN_SCHEMA,
    build_editable_targets,
    generate_tailoring_plan,
)

from .fakes import FakeOpenAIClient, FakeOpenAIResponse
from .helpers import DATA


def valid_plan():
    return {
        "company": "Texas Instruments",
        "jobTitle": "Full Stack Software Engineer",
        "gaps": ["No documented Kafka or SECS/GEM experience"],
        "operations": [
            {
                "operation": "rewrite",
                "target": "document.profile.headline",
                "field": None,
                "value": "Full Stack Software Engineer | React, TypeScript & Python",
            },
            {
                "operation": "rewrite",
                "target": "summary-1",
                "field": None,
                "value": "Truthful targeted summary.",
            },
            {
                "operation": "rewrite",
                "target": "skills-programming",
                "field": "items",
                "value": ["TypeScript", "Python", "Go", "SQL"],
            },
        ],
    }


class OpenAIProviderTests(unittest.TestCase):
    def setUp(self):
        self.resume = load_json(DATA)

    def test_editable_catalog_excludes_protected_facts(self):
        targets = build_editable_targets(self.resume)
        keys = {(item["target"], item["field"]) for item in targets}

        self.assertIn(("document.profile.headline", None), keys)
        self.assertIn(("summary-1", None), keys)
        self.assertIn(("skills-programming", "items"), keys)
        self.assertIn(("experience-axelyn", "technologies"), keys)
        self.assertNotIn(("document.profile.fullName", None), keys)
        self.assertNotIn(("experience-axelyn", "role"), keys)
        self.assertNotIn(("education-utm", "qualification"), keys)

    def test_uses_responses_api_with_strict_schema_and_no_storage(self):
        client = FakeOpenAIClient(FakeOpenAIResponse(valid_plan()))

        plan = generate_tailoring_plan(
            resume=self.resume,
            job_description="A supplied full-stack job description",
            candidate_context="Verified candidate context",
            model="gpt-5-mini-test",
            client=client,
        )

        self.assertEqual("Full Stack Software Engineer", plan.job_title)
        self.assertEqual("resp_test", plan.response_id)
        call = client.responses.calls[0]
        self.assertEqual("gpt-5-mini-test", call["model"])
        self.assertEqual("default", call["service_tier"])
        self.assertFalse(call["store"])
        self.assertTrue(call["text"]["format"]["strict"])
        self.assertEqual(TAILORING_PLAN_SCHEMA, call["text"]["format"]["schema"])
        payload = json.loads(call["input"])
        self.assertEqual("A supplied full-stack job description", payload["jobDescription"])
        self.assertEqual(
            "Verified candidate context",
            payload["selectedVerifiedCandidateContext"],
        )

    def test_strict_schema_enum_and_const_nodes_declare_their_types(self):
        def assert_discriminator_types(value, path):
            if isinstance(value, dict):
                if "const" in value or "enum" in value:
                    self.assertIn("type", value, path)
                for key, child in value.items():
                    assert_discriminator_types(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    assert_discriminator_types(child, f"{path}[{index}]")

        for name, schema in (
            ("resume_tailoring_plan", TAILORING_PLAN_SCHEMA),
            ("web_job_description", WEB_JOB_DESCRIPTION_SCHEMA),
        ):
            with self.subTest(schema=name):
                assert_discriminator_types(schema, name)

    def test_rejects_attempt_to_rewrite_protected_field(self):
        plan = valid_plan()
        plan["operations"][0]["target"] = "document.profile.fullName"
        client = FakeOpenAIClient(FakeOpenAIResponse(plan))

        with self.assertRaisesRegex(ProviderError, "protected or unknown"):
            generate_tailoring_plan(
                resume=self.resume,
                job_description="JD",
                client=client,
            )

    def test_rejects_duplicate_target_operations(self):
        plan = valid_plan()
        plan["operations"].append(dict(plan["operations"][1]))
        client = FakeOpenAIClient(FakeOpenAIResponse(plan))

        with self.assertRaisesRegex(ProviderError, "duplicate operations"):
            generate_tailoring_plan(
                resume=self.resume,
                job_description="JD",
                client=client,
            )

    def test_rejects_empty_or_non_json_response(self):
        empty = FakeOpenAIClient(FakeOpenAIResponse(output_text="", status="incomplete"))
        with self.assertRaisesRegex(ProviderError, "no tailoring plan"):
            generate_tailoring_plan(resume=self.resume, job_description="JD", client=empty)

        malformed = FakeOpenAIClient(FakeOpenAIResponse(output_text="not JSON"))
        with self.assertRaisesRegex(ProviderError, "invalid JSON"):
            generate_tailoring_plan(resume=self.resume, job_description="JD", client=malformed)


if __name__ == "__main__":
    unittest.main()
