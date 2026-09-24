import json
import unittest

from jsonschema import Draft202012Validator

from forge.context_selection import (
    CONTEXT_SELECTION_SCHEMA,
    parse_markdown_context,
    select_context_with_openai,
)
from forge.errors import ProviderError

from .fakes import FakeOpenAIClient, FakeOpenAIResponse


def selection_plan(selected_ids):
    return {
        "company": "Texas Instruments",
        "jobTitle": "Full Stack Software Engineer",
        "roleSignals": ["Full-stack delivery", "Production data systems"],
        "jobKeywords": [
            {
                "phrase": "Python",
                "priority": "required",
                "category": "technology",
            },
            {
                "phrase": "Kafka",
                "priority": "preferred",
                "category": "technology",
            },
        ],
        "selectedChunkIds": selected_ids,
        "gaps": ["No direct Kafka evidence"],
    }


class ContextSelectionTests(unittest.TestCase):
    def setUp(self):
        self.chunks = parse_markdown_context(
            "# Candidate\nCore evidence.\n\n## Backend\nPython API evidence.\n\n"
            "## Other\nUnrelated evidence.",
            source="candidate.md",
        )

    def test_markdown_chunks_have_source_aware_stable_ids(self):
        self.assertEqual(3, len(self.chunks))
        self.assertEqual("candidate.md", self.chunks[0].source)
        self.assertEqual("candidate-md--candidate", self.chunks[0].chunk_id)
        self.assertEqual(
            "candidate-md--candidate-backend",
            self.chunks[1].chunk_id,
        )

    def test_selector_returns_verbatim_chunks_in_ranked_order(self):
        selected_ids = [self.chunks[1].chunk_id, self.chunks[0].chunk_id]
        client = FakeOpenAIClient(FakeOpenAIResponse(selection_plan(selected_ids)))

        selection = select_context_with_openai(
            job_description="Backend-heavy factory platform role",
            chunks=self.chunks,
            model="gpt-context-test",
            client=client,
        )

        self.assertEqual(selected_ids, [chunk.chunk_id for chunk in selection.selected_chunks])
        self.assertIn("Python API evidence.", selection.selected_context_text())
        self.assertEqual(
            ["Python", "Kafka"],
            [keyword.phrase for keyword in selection.job_keywords],
        )
        call = client.responses.calls[0]
        self.assertEqual("gpt-context-test", call["model"])
        self.assertEqual("default", call["service_tier"])
        self.assertFalse(call["store"])
        response_schema = call["text"]["format"]["schema"]
        self.assertEqual(
            [chunk.chunk_id for chunk in self.chunks],
            response_schema["properties"]["selectedChunkIds"]["items"]["enum"],
        )
        self.assertEqual(
            100,
            response_schema["properties"]["jobKeywords"]["items"]["properties"][
                "phrase"
            ]["maxLength"],
        )
        payload = json.loads(call["input"])
        self.assertEqual(3, len(payload["candidateContextChunks"]))

    def test_request_schema_rejects_unknown_ids_and_overly_long_keywords(self):
        client = FakeOpenAIClient(
            FakeOpenAIResponse(selection_plan([self.chunks[0].chunk_id]))
        )
        select_context_with_openai(
            job_description="JD",
            chunks=self.chunks,
            client=client,
        )
        schema = client.responses.calls[0]["text"]["format"]["schema"]

        unknown_id = selection_plan(["invented-id"])
        unknown_errors = list(Draft202012Validator(schema).iter_errors(unknown_id))
        self.assertTrue(
            any("is not one of" in error.message for error in unknown_errors),
            unknown_errors,
        )

        long_keyword = selection_plan([self.chunks[0].chunk_id])
        long_keyword["jobKeywords"][0]["phrase"] = "x" * 101
        keyword_errors = list(Draft202012Validator(schema).iter_errors(long_keyword))
        self.assertTrue(
            any("is too long" in error.message for error in keyword_errors),
            keyword_errors,
        )

        self.assertNotIn(
            "enum",
            CONTEXT_SELECTION_SCHEMA["properties"]["selectedChunkIds"]["items"],
        )

    def test_selector_rejects_duplicate_job_keywords(self):
        plan = selection_plan([self.chunks[0].chunk_id])
        plan["jobKeywords"].append(
            {
                "phrase": "python",
                "priority": "preferred",
                "category": "technology",
            }
        )
        client = FakeOpenAIClient(FakeOpenAIResponse(plan))

        with self.assertRaisesRegex(ProviderError, "duplicate job keyword"):
            select_context_with_openai(
                job_description="JD",
                chunks=self.chunks,
                client=client,
            )

    def test_selector_rejects_unknown_or_duplicate_ids(self):
        unknown = FakeOpenAIClient(FakeOpenAIResponse(selection_plan(["invented-id"])))
        with self.assertRaisesRegex(ProviderError, "unknown context chunk"):
            select_context_with_openai(
                job_description="JD",
                chunks=self.chunks,
                client=unknown,
            )

        duplicate_id = self.chunks[0].chunk_id
        duplicate = FakeOpenAIClient(
            FakeOpenAIResponse(selection_plan([duplicate_id, duplicate_id]))
        )
        with self.assertRaisesRegex(ProviderError, "duplicate chunk IDs"):
            select_context_with_openai(
                job_description="JD",
                chunks=self.chunks,
                client=duplicate,
            )


if __name__ == "__main__":
    unittest.main()
