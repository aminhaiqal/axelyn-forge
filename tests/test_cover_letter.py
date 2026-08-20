import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from forge.bindings import resolve_bindings
from forge.cover_letter import (
    COVER_LETTER_DRAFT_SCHEMA,
    PARAGRAPH_LAYOUT,
    build_cover_letter_document,
    generate_cover_letter_draft,
)
from forge.docx import inspect_docx, render_docx, validate_docx_archive
from forge.errors import ProviderError
from forge.jsonio import load_json
from forge.usage_store import OpenAIUsageStore
from forge.validation import validate_document

from .fakes import FakeOpenAIClient, FakeOpenAIResponse
from .helpers import (
    COVER_BINDINGS,
    COVER_DATA,
    COVER_SCHEMA,
    COVER_TEMPLATE,
    DATA,
    formatting_signature,
)


def valid_cover_letter_draft():
    evidence = {
        "cover-opening": ["job-description", "experience-axelyn"],
        "cover-body-1": ["experience-axelyn"],
        "cover-body-2": ["project-aria"],
        "cover-body-3": ["experience-axelyn", "project-aria"],
        "cover-body-4": ["job-description"],
        "cover-body-5": ["experience-axelyn"],
        "cover-body-6": ["job-description", "experience-axelyn"],
        "cover-value-proposition": ["experience-axelyn", "project-aria"],
        "cover-closing": ["job-description"],
    }
    return {
        "paragraphs": {
            paragraph_id: {
                "text": (
                    f"Tailored {purpose} paragraph for Texas Instruments that presents "
                    "verified engineering experience with clear motivation and practical value."
                ),
                "supportingEvidence": evidence[paragraph_id],
            }
            for paragraph_id, purpose in PARAGRAPH_LAYOUT
        }
    }


class CoverLetterSchemaAndRenderingTests(unittest.TestCase):
    def test_fixture_schema_bindings_and_template_cover_all_controls(self):
        cover_letter = load_json(COVER_DATA)
        schema = load_json(COVER_SCHEMA)
        bindings = load_json(COVER_BINDINGS)

        validate_document(cover_letter, schema, label="Cover letter")
        values = resolve_bindings(cover_letter, bindings)
        controls = inspect_docx(COVER_TEMPLATE)

        self.assertEqual(18, len(values))
        self.assertEqual({item.tag for item in controls}, set(values))
        self.assertEqual(18, len(controls))

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "cover-letter.docx"
            original = COVER_TEMPLATE.read_bytes()
            before = formatting_signature(COVER_TEMPLATE, "OPENING_PARAGRAPH")
            report = render_docx(COVER_TEMPLATE, output, values, strict=True)

            self.assertEqual(18, report.controls)
            self.assertEqual((), report.unused_values)
            self.assertEqual(before, formatting_signature(output, "OPENING_PARAGRAPH"))
            self.assertEqual(original, COVER_TEMPLATE.read_bytes())
            validate_docx_archive(output)

    def test_assembled_document_uses_protected_identity_and_application_fields(self):
        draft_response = valid_cover_letter_draft()
        client = FakeOpenAIClient(FakeOpenAIResponse(draft_response))
        draft = generate_cover_letter_draft(
            tailored_resume=load_json(DATA),
            job_description="Texas Instruments needs a full-stack engineer.",
            job_title="Full Stack Software Engineer",
            company="Texas Instruments",
            candidate_context="",
            context_selection=None,
            keyword_alignment=None,
            gaps=(),
            allowed_evidence_ids=(
                "job-description",
                "experience-axelyn",
                "project-aria",
            ),
            model="gpt-cover-test",
            client=client,
        )
        base = copy.deepcopy(load_json(COVER_DATA))
        base["document"]["candidate"]["legalName"] = "Do not copy this value"
        assembled = build_cover_letter_document(
            base=base,
            tailored_resume=load_json(DATA),
            draft=draft,
            job_title="Full Stack Software Engineer",
            company="Texas Instruments",
            workflow_id="workflow-cover-test",
            application_date=date(2026, 8, 20),
        )

        validate_document(assembled, load_json(COVER_SCHEMA), label="Cover letter")
        document = assembled["document"]
        self.assertEqual(
            "MUHAMMAD AMIN HAIQAL BIN ROSLEE",
            document["candidate"]["legalName"],
        )
        self.assertEqual("20 August 2026", document["application"]["date"])
        self.assertEqual(
            "Application for Full Stack Software Engineer",
            document["application"]["subject"],
        )
        self.assertEqual(
            "Dear Texas Instruments Hiring Team,",
            document["application"]["salutation"],
        )
        self.assertEqual(
            [paragraph_id for paragraph_id, _ in PARAGRAPH_LAYOUT],
            [item["id"] for item in document["paragraphs"]],
        )
        self.assertEqual("workflow-cover-test", document["metadata"]["workflowId"])


class CoverLetterProviderTests(unittest.TestCase):
    def test_strict_generation_records_cost_request_and_evidence(self):
        client = FakeOpenAIClient(
            FakeOpenAIResponse(
                valid_cover_letter_draft(),
                response_id="resp_cover",
                model="gpt-5.6-terra",
                usage={
                    "input_tokens": 1000,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 500,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 1500,
                },
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OpenAIUsageStore(Path(temp_dir) / "usage.sqlite3")
            store.initialize()
            draft = generate_cover_letter_draft(
                tailored_resume=load_json(DATA),
                job_description="Full-stack role",
                job_title="Full Stack Software Engineer",
                company="Texas Instruments",
                candidate_context="Verified context",
                context_selection={"selectedChunkIds": ["context-1"]},
                keyword_alignment={"mustSurface": []},
                gaps=("No Kafka evidence",),
                allowed_evidence_ids=(
                    "job-description",
                    "experience-axelyn",
                    "project-aria",
                    "context-1",
                ),
                model="gpt-5.6-terra",
                client=client,
                usage_store=store,
                workflow_id="workflow-cover",
            )

            self.assertEqual("resp_cover", draft.response_id)
            self.assertEqual(9, len(draft.paragraphs))
            call = client.responses.calls[0]
            self.assertFalse(call["store"])
            self.assertEqual(COVER_LETTER_DRAFT_SCHEMA, call["text"]["format"]["schema"])
            payload = json.loads(call["input"])
            self.assertIn("No Kafka evidence", payload["materialGaps"])
            self.assertIn("context-1", payload["allowedSupportingEvidenceIds"])
            request = store.list_requests(workflow_id="workflow-cover")[0]
            self.assertEqual("cover_letter_generation", request["request_kind"])

    def test_unknown_evidence_is_rejected(self):
        response = valid_cover_letter_draft()
        response["paragraphs"]["cover-body-2"]["supportingEvidence"] = [
            "invented-evidence"
        ]
        client = FakeOpenAIClient(FakeOpenAIResponse(response))

        with self.assertRaisesRegex(ProviderError, "unknown evidence"):
            generate_cover_letter_draft(
                tailored_resume=load_json(DATA),
                job_description="Role",
                job_title="Engineer",
                company=None,
                candidate_context="",
                context_selection=None,
                keyword_alignment=None,
                gaps=(),
                allowed_evidence_ids=(
                    "job-description",
                    "experience-axelyn",
                    "project-aria",
                ),
                model="gpt-cover-test",
                client=client,
            )

    def test_candidate_claim_slots_require_candidate_evidence(self):
        response = valid_cover_letter_draft()
        response["paragraphs"]["cover-body-1"]["supportingEvidence"] = [
            "job-description"
        ]
        client = FakeOpenAIClient(FakeOpenAIResponse(response))

        with self.assertRaisesRegex(ProviderError, "lacks candidate evidence"):
            generate_cover_letter_draft(
                tailored_resume=load_json(DATA),
                job_description="Role",
                job_title="Engineer",
                company=None,
                candidate_context="",
                context_selection=None,
                keyword_alignment=None,
                gaps=(),
                allowed_evidence_ids=(
                    "job-description",
                    "experience-axelyn",
                    "project-aria",
                ),
                model="gpt-cover-test",
                client=client,
            )


if __name__ == "__main__":
    unittest.main()
