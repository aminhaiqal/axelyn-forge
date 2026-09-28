import tempfile
import unittest
from pathlib import Path

from forge.errors import ProviderError
from forge.job_source import (
    WEB_JOB_DESCRIPTION_SCHEMA,
    normalize_job_url,
    retrieve_job_description_with_openrouter,
)
from forge.usage_store import OpenRouterUsageStore

from .fakes import FakeOpenAIClient, FakeOpenAIResponse


def found_job():
    return {
        "status": "found",
        "company": "Texas Instruments",
        "jobTitle": "Full Stack Software Engineer",
        "jobDescription": (
            "Design and develop a production full-stack manufacturing dashboard. "
            "Build REST APIs, real-time Kafka pipelines, responsive interfaces, and "
            "containerized deployments. A bachelor's degree and relevant software "
            "engineering experience are required."
        ),
        "error": None,
    }


def web_output():
    return [
        {
            "type": "web_search_call",
            "status": "completed",
            "action": {
                "type": "search",
                "query": "site:careers.ti.com full stack software engineer",
                "sources": [
                    {"type": "url", "url": "https://careers.ti.com/job/123"}
                ],
            },
        },
        {
            "type": "web_search_call",
            "status": "completed",
            "action": {
                "type": "open_page",
                "url": "https://careers.ti.com/job/123",
            },
        },
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": "structured output",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://careers.ti.com/job/123",
                            "title": "Full Stack Software Engineer",
                        }
                    ],
                }
            ],
        },
    ]


def web_usage():
    return {
        "input_tokens": 1000,
        "input_tokens_details": {
            "cached_tokens": 200,
            "cache_write_tokens": 300,
        },
        "output_tokens": 500,
        "output_tokens_details": {"reasoning_tokens": 100},
        "total_tokens": 1500,
    }


class WebJobDescriptionTests(unittest.TestCase):
    def test_normalizes_public_url_and_rejects_unsafe_inputs(self):
        normalized, hostname = normalize_job_url(
            "HTTPS://Careers.TI.com/job/123?source=site#description"
        )
        self.assertEqual(
            "https://careers.ti.com/job/123?source=site",
            normalized,
        )
        self.assertEqual("careers.ti.com", hostname)

        for value in (
            "file:///tmp/job.txt",
            "https://user:password@example.com/job",
            "http://localhost/job",
            "http://127.0.0.1/job",
            "https://example.com:notaport/job",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ProviderError):
                    normalize_job_url(value)

    def test_retrieves_exact_domain_with_structured_output_and_records_tool_cost(self):
        response = FakeOpenAIResponse(
            found_job(),
            response_id="resp_web",
            model="openai/gpt-5.4-nano",
            usage=web_usage(),
            output=web_output(),
        )
        client = FakeOpenAIClient(response)
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OpenRouterUsageStore(Path(temp_dir) / "forge.sqlite3")
            job = retrieve_job_description_with_openrouter(
                url="https://careers.ti.com/job/123#description",
                model="openai/gpt-5.4-nano",
                client=client,
                usage_store=store,
                workflow_id="workflow-web",
            )

            self.assertEqual("Full Stack Software Engineer", job.job_title)
            self.assertIn("REST APIs", job.text)
            self.assertEqual(
                ("https://careers.ti.com/job/123",),
                job.source_urls,
            )

            call = client.responses.calls[0]
            self.assertEqual("required", call["tool_choice"])
            self.assertEqual("openrouter:web_search", call["tools"][0]["type"])
            self.assertEqual(
                ["careers.ti.com"],
                call["tools"][0]["parameters"]["allowed_domains"],
            )
            self.assertEqual(
                "high", call["tools"][0]["parameters"]["search_context_size"]
            )
            self.assertEqual(10, call["tools"][0]["parameters"]["max_total_results"])
            self.assertEqual(WEB_JOB_DESCRIPTION_SCHEMA, call["text"]["format"]["schema"])
            self.assertNotIn("include", call)
            self.assertNotIn("service_tier", call)
            self.assertFalse(call["store"])
            self.assertTrue(call["extra_body"]["provider"]["zdr"])

            row = store.list_requests(workflow_id="workflow-web")[0]
            self.assertEqual("job_description_web_search", row["request_kind"])
            self.assertEqual(1, row["web_search_calls"])
            self.assertEqual(10.0, row["web_search_usd_per_1000"])
            self.assertAlmostEqual(0.01, row["web_search_cost_usd"])
            self.assertAlmostEqual(0.000789, row["token_cost_usd"])
            self.assertAlmostEqual(0.010789, row["estimated_cost_usd"])

    def test_rejects_unavailable_page_or_response_without_web_search(self):
        unavailable = dict(found_job())
        unavailable.update(
            {
                "status": "unavailable",
                "jobTitle": "",
                "jobDescription": "",
                "error": "The posting has expired.",
            }
        )
        with self.assertRaisesRegex(ProviderError, "posting has expired"):
            retrieve_job_description_with_openrouter(
                url="https://careers.ti.com/job/expired",
                client=FakeOpenAIClient(
                    FakeOpenAIResponse(unavailable, output=web_output())
                ),
            )

        with self.assertRaisesRegex(ProviderError, "without using web search"):
            retrieve_job_description_with_openrouter(
                url="https://careers.ti.com/job/123",
                client=FakeOpenAIClient(FakeOpenAIResponse(found_job())),
            )


if __name__ == "__main__":
    unittest.main()
