import tempfile
import unittest
import json
import zipfile
from datetime import date
from pathlib import Path

from forge.docx import inspect_docx, validate_docx_archive
from forge.context_store import sync_context_database
from forge.errors import TailoringError
from forge.jsonio import load_json
from forge.tailoring import safe_filename_component, tailor_resume_with_openai
from forge.validation import validate_resume

from .fakes import FakeOpenAIClient, FakeOpenAIResponse
from .helpers import (
    BINDINGS,
    COVER_BINDINGS,
    COVER_DATA,
    COVER_SCHEMA,
    COVER_TEMPLATE,
    DATA,
    SCHEMA,
    TEMPLATE,
)
from .test_cover_letter import valid_cover_letter_draft
from .test_job_source import found_job, web_output, web_usage
from .test_openai_provider import valid_plan


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"


def fake_pdf_converter(source, output):
    validate_docx_archive(source)
    destination = Path(output)
    destination.write_bytes(VALID_PDF)
    return destination


class OpenAITailoringWorkflowTests(unittest.TestCase):
    def test_safe_filename_component(self):
        self.assertEqual(
            "Full_Stack_Software_Engineer",
            safe_filename_component("Full Stack Software Engineer"),
        )
        self.assertEqual("AI_Platform", safe_filename_component("AI / Platform"))

    def test_mocked_openai_workflow_emits_docx_and_pdf_artifacts(self):
        client = FakeOpenAIClient(FakeOpenAIResponse(valid_plan()))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            jd = root / "jd.txt"
            jd.write_text("Texas Instruments full-stack role", encoding="utf-8")
            result = tailor_resume_with_openai(
                template=TEMPLATE,
                data=DATA,
                schema=SCHEMA,
                bindings=BINDINGS,
                job_description=jd,
                output_dir=root / "output",
                usage_database=root / "usage.sqlite3",
                model="gpt-5-mini-test",
                include_pdf=True,
                pdf_converter=fake_pdf_converter,
                client=client,
            )

            base = "Amin_Haiqal_Resume_Full_Stack_Software_Engineer"
            self.assertEqual(f"{base}.operations.json", result.operations_output.name)
            self.assertEqual(f"{base}.json", result.data_output.name)
            self.assertEqual(f"{base}.docx", result.docx_output.name)
            self.assertEqual(f"{base}.pdf", result.pdf_output.name)
            self.assertEqual(VALID_PDF, result.pdf_output.read_bytes())
            self.assertIsNone(result.keyword_alignment_output)
            self.assertIsNone(result.keyword_coverage)
            self.assertEqual(3, result.applied_operations)
            self.assertEqual(root / "usage.sqlite3", result.usage_database)
            self.assertEqual(1, result.usage_summary["requests"])

            tailored = load_json(result.data_output)
            validate_resume(tailored, load_json(SCHEMA))
            operations = load_json(result.operations_output)
            self.assertEqual("openai", operations["provider"]["name"])
            self.assertEqual("resp_test", operations["provider"]["responseId"])
            self.assertEqual(result.workflow_id, operations["provider"]["workflowId"])
            self.assertEqual(
                str(root / "usage.sqlite3"),
                operations["provider"]["usageDatabase"],
            )
            validate_docx_archive(result.docx_output)
            controls = {item.tag: item.current_text for item in inspect_docx(result.docx_output)}
            self.assertEqual(
                "Full Stack Software Engineer | React, TypeScript & Python",
                controls["profile.headline"],
            )

    def test_cover_letter_reuses_tailored_resume_and_emits_docx_and_pdf(self):
        client = FakeOpenAIClient(
            [
                FakeOpenAIResponse(valid_plan(), response_id="resp_tailoring"),
                FakeOpenAIResponse(
                    valid_cover_letter_draft(),
                    response_id="resp_cover_letter",
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            jd = root / "jd.txt"
            jd.write_text("Texas Instruments full-stack role", encoding="utf-8")
            cover_template_before = COVER_TEMPLATE.read_bytes()
            result = tailor_resume_with_openai(
                template=TEMPLATE,
                data=DATA,
                schema=SCHEMA,
                bindings=BINDINGS,
                job_description=jd,
                output_dir=root / "output",
                usage_database=root / "usage.sqlite3",
                model="gpt-resume-test",
                include_pdf=True,
                include_cover_letter=True,
                cover_letter_template=COVER_TEMPLATE,
                cover_letter_data=COVER_DATA,
                cover_letter_schema=COVER_SCHEMA,
                cover_letter_bindings=COVER_BINDINGS,
                cover_letter_model="gpt-cover-test",
                cover_letter_date=date(2026, 8, 20),
                pdf_converter=fake_pdf_converter,
                client=client,
            )

            cover_base = (
                "Amin_Haiqal_Cover_Letter_Texas_Instruments_"
                "Full_Stack_Software_Engineer"
            )
            self.assertEqual(2, len(client.responses.calls))
            self.assertEqual("gpt-cover-test", client.responses.calls[1]["model"])
            cover_payload = json.loads(client.responses.calls[1]["input"])
            self.assertEqual(
                "Full Stack Software Engineer | React, TypeScript & Python",
                cover_payload["tailoredResume"]["document"]["profile"]["headline"],
            )
            self.assertEqual(f"{cover_base}.json", result.cover_letter_data_output.name)
            self.assertEqual(f"{cover_base}.docx", result.cover_letter_docx_output.name)
            self.assertEqual(f"{cover_base}.pdf", result.cover_letter_pdf_output.name)
            self.assertEqual(VALID_PDF, result.cover_letter_pdf_output.read_bytes())
            self.assertEqual("gpt-cover-test", result.cover_letter_model)
            self.assertEqual(18, result.cover_letter_render_report.controls)
            self.assertIn(
                "docProps/core.xml",
                result.cover_letter_render_report.changed_parts,
            )
            self.assertEqual(2, result.usage_summary["requests"])
            self.assertEqual(cover_template_before, COVER_TEMPLATE.read_bytes())

            cover_data = load_json(result.cover_letter_data_output)
            validate_resume(cover_data, load_json(COVER_SCHEMA))
            self.assertEqual(
                result.workflow_id,
                cover_data["document"]["metadata"]["workflowId"],
            )
            cover_controls = {
                item.tag: item.current_text
                for item in inspect_docx(result.cover_letter_docx_output)
            }
            self.assertEqual("Texas Instruments", cover_controls["COMPANY_NAME"])
            self.assertEqual(
                "Application for Full Stack Software Engineer",
                cover_controls["APPLICATION_SUBJECT"],
            )
            self.assertEqual("20 August 2026", cover_controls["DATE"])
            with zipfile.ZipFile(result.cover_letter_docx_output) as archive:
                core_properties = archive.read("docProps/core.xml").decode("utf-8")
            self.assertIn(
                "Amin Haiqal - Texas Instruments Cover Letter",
                core_properties,
            )
            self.assertIn(
                "Application for Full Stack Software Engineer - Texas Instruments",
                core_properties,
            )
            self.assertNotIn("Smart Manufacturing", core_properties)

    def test_disabling_cover_letter_skips_its_openai_request(self):
        client = FakeOpenAIClient(FakeOpenAIResponse(valid_plan()))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            jd = root / "jd.txt"
            jd.write_text("Full-stack role", encoding="utf-8")
            result = tailor_resume_with_openai(
                template=TEMPLATE,
                data=DATA,
                schema=SCHEMA,
                bindings=BINDINGS,
                job_description=jd,
                output_dir=root / "output",
                usage_database=root / "usage.sqlite3",
                include_cover_letter=False,
                client=client,
            )

            self.assertEqual(1, len(client.responses.calls))
            self.assertIsNone(result.cover_letter_data_output)
            self.assertIsNone(result.cover_letter_docx_output)
            self.assertIsNone(result.cover_letter_pdf_output)

    def test_missing_cover_letter_asset_fails_before_openai(self):
        client = FakeOpenAIClient(FakeOpenAIResponse(valid_plan()))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            jd = root / "jd.txt"
            jd.write_text("Full-stack role", encoding="utf-8")

            with self.assertRaisesRegex(TailoringError, "template does not exist"):
                tailor_resume_with_openai(
                    template=TEMPLATE,
                    data=DATA,
                    schema=SCHEMA,
                    bindings=BINDINGS,
                    job_description=jd,
                    output_dir=root / "output",
                    include_cover_letter=True,
                    cover_letter_template=root / "missing.docx",
                    cover_letter_data=COVER_DATA,
                    cover_letter_schema=COVER_SCHEMA,
                    cover_letter_bindings=COVER_BINDINGS,
                    client=client,
                )

            self.assertEqual([], client.responses.calls)
            self.assertFalse((root / "output").exists())

    def test_context_directory_is_selected_before_main_tailoring_call(self):
        selection_response = {
            "company": "Texas Instruments",
            "jobTitle": "Full Stack Software Engineer",
            "roleSignals": ["Full-stack production systems"],
            "jobKeywords": [
                {
                    "phrase": "Python",
                    "priority": "required",
                    "category": "technology",
                },
                {
                    "phrase": "REST APIs",
                    "priority": "required",
                    "category": "technology",
                },
                {
                    "phrase": "Kafka",
                    "priority": "preferred",
                    "category": "technology",
                },
            ],
            "selectedChunkIds": ["candidate-md--candidate-backend"],
            "gaps": ["No Kafka evidence"],
        }
        client = FakeOpenAIClient(
            [
                FakeOpenAIResponse(
                    selection_response,
                    response_id="resp_selection",
                    model="gpt-5.6-luna",
                    usage={
                        "input_tokens": 1000,
                        "input_tokens_details": {
                            "cached_tokens": 200,
                            "cache_write_tokens": 300,
                        },
                        "output_tokens": 500,
                        "output_tokens_details": {"reasoning_tokens": 100},
                        "total_tokens": 1500,
                    },
                ),
                FakeOpenAIResponse(
                    valid_plan(),
                    response_id="resp_tailoring",
                    model="gpt-5.6-terra",
                    usage={
                        "input_tokens": 2000,
                        "input_tokens_details": {
                            "cached_tokens": 0,
                            "cache_write_tokens": 0,
                        },
                        "output_tokens": 1000,
                        "output_tokens_details": {"reasoning_tokens": 250},
                        "total_tokens": 3000,
                    },
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            jd = root / "jd.txt"
            jd.write_text("Texas Instruments full-stack role", encoding="utf-8")
            context = root / "context"
            context.mkdir()
            (context / "candidate.md").write_text(
                "# Candidate\nCore details.\n\n## Backend\nVerified React and Python API evidence.",
                encoding="utf-8",
            )
            (context / "unrelated.md").write_text(
                "# Unrelated\nEvidence that should not reach the main call.",
                encoding="utf-8",
            )

            result = tailor_resume_with_openai(
                template=TEMPLATE,
                data=DATA,
                schema=SCHEMA,
                bindings=BINDINGS,
                job_description=jd,
                candidate_context=context,
                context_database=root / "context.sqlite3",
                output_dir=root / "output",
                model="gpt-main-test",
                context_selection_model="gpt-context-test",
                client=client,
            )

            self.assertEqual(2, len(client.responses.calls))
            self.assertEqual(root / "context.sqlite3", result.context_database)
            self.assertEqual(root / "context.sqlite3", result.usage_database)
            self.assertTrue(result.context_database.is_file())
            self.assertEqual("gpt-context-test", client.responses.calls[0]["model"])
            self.assertEqual("gpt-main-test", client.responses.calls[1]["model"])
            main_payload = json.loads(client.responses.calls[1]["input"])
            selected_context = main_payload["selectedVerifiedCandidateContext"]
            self.assertIn("Verified React and Python API evidence.", selected_context)
            self.assertNotIn("Evidence that should not reach", selected_context)
            self.assertEqual(
                ["Python", "REST APIs"],
                [
                    item["phrase"]
                    for item in main_payload["keywordAlignment"]["mustSurface"]
                ],
            )
            self.assertEqual(
                ["Kafka"],
                [
                    item["phrase"]
                    for item in main_payload["keywordAlignment"]["unsupported"]
                ],
            )

            self.assertIsNotNone(result.context_selection_output)
            selection_audit = load_json(result.context_selection_output)
            self.assertEqual("resp_selection", selection_audit["provider"]["responseId"])
            self.assertEqual(result.workflow_id, selection_audit["provider"]["workflowId"])
            self.assertEqual(str(root / "context.sqlite3"), selection_audit["contextDatabase"])
            self.assertEqual(
                ["candidate-md--candidate-backend"],
                selection_audit["selectedChunkIds"],
            )
            self.assertEqual("Python", selection_audit["jobKeywords"][0]["phrase"])
            self.assertIsNotNone(result.keyword_alignment_output)
            alignment_audit = load_json(result.keyword_alignment_output)
            self.assertEqual(result.workflow_id, alignment_audit["provider"]["workflowId"])
            self.assertEqual(2, alignment_audit["coverage"]["targetedKeywords"])
            self.assertEqual(2, alignment_audit["coverage"]["surfacedAfter"])
            self.assertEqual(100.0, alignment_audit["coverage"]["percentage"])
            self.assertEqual(alignment_audit["coverage"], result.keyword_coverage)
            operation_audit = load_json(result.operations_output)
            self.assertEqual(
                ["candidate-md--candidate-backend"],
                operation_audit["contextSelection"]["selectedChunkIds"],
            )
            self.assertEqual(
                ["Python", "REST APIs"],
                operation_audit["keywordAlignment"]["mustSurface"],
            )
            self.assertEqual(2, result.usage_summary["requests"])
            self.assertEqual(2, result.usage_summary["priced_requests"])
            self.assertEqual(0, result.usage_summary["failed"])
            self.assertAlmostEqual(0.016779, result.usage_summary["estimated_cost_usd"])

    def test_existing_context_database_can_drive_selection_without_markdown_input(self):
        selection_response = {
            "company": "Texas Instruments",
            "jobTitle": "Full Stack Software Engineer",
            "roleSignals": ["Production software"],
            "jobKeywords": [
                {
                    "phrase": "Python",
                    "priority": "required",
                    "category": "technology",
                }
            ],
            "selectedChunkIds": ["candidate-md--candidate"],
            "gaps": [],
        }
        client = FakeOpenAIClient(
            [
                FakeOpenAIResponse(selection_response, response_id="resp_db_selection"),
                FakeOpenAIResponse(valid_plan(), response_id="resp_db_tailoring"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = root / "context"
            context.mkdir()
            (context / "candidate.md").write_text(
                "# Candidate\nPersisted verified evidence.",
                encoding="utf-8",
            )
            database = root / "context.sqlite3"
            sync_context_database(context, database)
            jd = root / "jd.txt"
            jd.write_text("Production software role", encoding="utf-8")

            result = tailor_resume_with_openai(
                template=TEMPLATE,
                data=DATA,
                schema=SCHEMA,
                bindings=BINDINGS,
                job_description=jd,
                context_database=database,
                output_dir=root / "output",
                client=client,
            )

            self.assertEqual(database, result.context_database)
            self.assertEqual(2, len(client.responses.calls))
            main_payload = json.loads(client.responses.calls[1]["input"])
            self.assertIn(
                "Persisted verified evidence.",
                main_payload["selectedVerifiedCandidateContext"],
            )

    def test_job_url_runs_web_ingestion_before_selection_and_tailoring(self):
        selection_response = {
            "company": "Texas Instruments",
            "jobTitle": "Full Stack Software Engineer",
            "roleSignals": ["Full-stack factory software"],
            "jobKeywords": [
                {
                    "phrase": "Docker",
                    "priority": "required",
                    "category": "technology",
                },
                {
                    "phrase": "Kafka",
                    "priority": "preferred",
                    "category": "technology",
                },
            ],
            "selectedChunkIds": ["candidate-md--candidate"],
            "gaps": ["No SECS/GEM evidence"],
        }
        client = FakeOpenAIClient(
            [
                FakeOpenAIResponse(
                    found_job(),
                    response_id="resp_web",
                    model="gpt-5.6-luna",
                    usage=web_usage(),
                    output=web_output(),
                ),
                FakeOpenAIResponse(
                    selection_response,
                    response_id="resp_selection",
                    model="gpt-5.6-luna",
                    usage=web_usage(),
                ),
                FakeOpenAIResponse(
                    valid_plan(),
                    response_id="resp_tailoring",
                    model="gpt-5.6-terra",
                    usage=web_usage(),
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = root / "context"
            context.mkdir()
            (context / "candidate.md").write_text(
                "# Candidate\nVerified Python and API delivery evidence.",
                encoding="utf-8",
            )
            database = root / "forge.sqlite3"

            result = tailor_resume_with_openai(
                template=TEMPLATE,
                data=DATA,
                schema=SCHEMA,
                bindings=BINDINGS,
                job_description_url="https://careers.ti.com/job/123",
                candidate_context=context,
                context_database=database,
                output_dir=root / "output",
                model="gpt-5.6-terra",
                context_selection_model="gpt-5.6-luna",
                web_search_model="gpt-5.6-luna",
                client=client,
            )

            self.assertEqual(3, len(client.responses.calls))
            self.assertEqual("web_search", client.responses.calls[0]["tools"][0]["type"])
            selector_payload = json.loads(client.responses.calls[1]["input"])
            self.assertIn("Source URL: https://careers.ti.com/job/123", selector_payload["jobDescription"])
            main_payload = json.loads(client.responses.calls[2]["input"])
            self.assertIn("containerized deployments", main_payload["jobDescription"])

            self.assertIsNotNone(result.job_source_output)
            job_source = load_json(result.job_source_output)
            self.assertEqual("url", job_source["source"]["type"])
            self.assertEqual(result.workflow_id, job_source["provider"]["workflowId"])
            self.assertEqual("resp_web", job_source["provider"]["responseId"])
            operations = load_json(result.operations_output)
            self.assertEqual("resp_web", operations["jobSource"]["responseId"])
            self.assertEqual(3, result.usage_summary["requests"])
            self.assertEqual(1, result.usage_summary["web_search_calls"])
            self.assertAlmostEqual(0.01, result.usage_summary["web_search_cost_usd"])


if __name__ == "__main__":
    unittest.main()
