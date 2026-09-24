import tempfile
import unittest
from pathlib import Path

from forge.errors import ProviderError
from forge.jsonio import load_json
from forge.openai_provider import generate_tailoring_plan
from forge.usage_store import OpenAIUsageStore

from .fakes import FakeOpenAIClient, FakeOpenAIResponse
from .helpers import DATA


def response_usage(*, input_tokens=1000, cached_tokens=200, cache_write_tokens=300):
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {
            "cached_tokens": cached_tokens,
            "cache_write_tokens": cache_write_tokens,
        },
        "output_tokens": 500,
        "output_tokens_details": {"reasoning_tokens": 100},
        "total_tokens": input_tokens + 500,
    }


class OpenAIUsageStoreTests(unittest.TestCase):
    def test_empty_initialized_ledger_has_zero_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OpenAIUsageStore(Path(temp_dir) / "forge.sqlite3")
            store.initialize()

            summary = store.summary()

            self.assertEqual(0, summary["requests"])
            self.assertEqual(0, summary["completed"])
            self.assertEqual(0, summary["unpriced_requests"])
            self.assertEqual(0.0, summary["estimated_cost_usd"])

    def test_records_token_breakdown_rate_snapshot_and_component_costs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "forge.sqlite3"
            store = OpenAIUsageStore(database)
            request_id = store.start_request(
                workflow_id="workflow-1",
                request_kind="main_tailoring",
                requested_model="gpt-5.6-terra",
            )
            response = FakeOpenAIResponse(
                {},
                model="gpt-5.6-terra",
                usage=response_usage(),
            )

            store.complete_request(request_id, response)

            row = store.list_requests(workflow_id="workflow-1")[0]
            self.assertEqual("completed", row["status"])
            self.assertEqual("estimated_public_list_price", row["cost_status"])
            self.assertEqual(500, row["ordinary_input_tokens"])
            self.assertEqual(200, row["cached_input_tokens"])
            self.assertEqual(300, row["cache_write_tokens"])
            self.assertEqual(100, row["reasoning_tokens"])
            self.assertEqual("short", row["pricing_context_band"])
            self.assertEqual(2.0, row["input_usd_per_million"])
            self.assertEqual(0.2, row["cached_input_usd_per_million"])
            self.assertEqual(2.5, row["cache_write_usd_per_million"])
            self.assertEqual(12.0, row["output_usd_per_million"])
            self.assertAlmostEqual(0.00779, row["estimated_cost_usd"])

    def test_applies_long_context_rates_to_the_full_request(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OpenAIUsageStore(Path(temp_dir) / "forge.sqlite3")
            request_id = store.start_request(
                workflow_id="workflow-long",
                request_kind="context_selection",
                requested_model="gpt-5.6-luna",
            )
            response = FakeOpenAIResponse(
                {},
                model="gpt-5.6-luna",
                usage=response_usage(
                    input_tokens=272_001,
                    cached_tokens=0,
                    cache_write_tokens=0,
                ),
            )
            store.complete_request(request_id, response)

            row = store.list_requests(workflow_id="workflow-long")[0]
            self.assertEqual("long", row["pricing_context_band"])
            self.assertEqual(0.4, row["input_usd_per_million"])
            self.assertEqual(1.8, row["output_usd_per_million"])

    def test_failed_provider_call_is_retained_with_unknown_cost(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "forge.sqlite3"
            store = OpenAIUsageStore(database)
            client = FakeOpenAIClient(RuntimeError("temporary provider failure"))

            with self.assertRaisesRegex(ProviderError, "temporary provider failure"):
                generate_tailoring_plan(
                    resume=load_json(DATA),
                    job_description="JD",
                    model="gpt-5.6-terra",
                    client=client,
                    usage_store=store,
                    workflow_id="workflow-failed",
                )

            row = store.list_requests(workflow_id="workflow-failed")[0]
            self.assertEqual("failed", row["status"])
            self.assertEqual("RuntimeError", row["error_type"])
            self.assertIn("temporary provider failure", row["error_message"])
            self.assertIsNone(row["estimated_cost_usd"])

    def test_unknown_model_keeps_usage_without_guessing_cost(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OpenAIUsageStore(Path(temp_dir) / "forge.sqlite3")
            request_id = store.start_request(
                workflow_id="workflow-custom",
                request_kind="main_tailoring",
                requested_model="custom-model",
            )
            store.complete_request(
                request_id,
                FakeOpenAIResponse(
                    {},
                    model="custom-model",
                    usage=response_usage(),
                ),
            )

            row = store.list_requests(workflow_id="workflow-custom")[0]
            self.assertEqual(1500, row["total_tokens"])
            self.assertEqual("unpriced_model", row["cost_status"])
            self.assertIsNone(row["estimated_cost_usd"])


if __name__ == "__main__":
    unittest.main()
