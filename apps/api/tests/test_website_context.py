import json
import unittest
from types import SimpleNamespace

from axelyn_api.website_context import (
    WEBSITE_CONTEXT_SCHEMA,
    extract_public_urls,
    retrieve_website_context,
)


def web_output():
    return [
        {
            "type": "openrouter:web_search",
            "action": {
                "type": "open_page",
                "url": "https://pastelocity.com.my/",
                "sources": [
                    {"type": "url", "url": "https://pastelocity.com.my/"}
                ],
            },
        },
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://pastelocity.com.my/",
                        }
                    ],
                }
            ],
        },
    ]


class FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="response-web",
            model="openai/gpt-test",
            output=web_output(),
            output_text="```json\n"
            + json.dumps(
                {
                    "status": "found",
                    "title": "Pastelocity - Handcrafted Caftans & Modest Fashion",
                    "summary": (
                        "A Malaysian modest-fashion store offering handcrafted batik, "
                        "kaftans, blouses, custom orders, shipping, and order tracking."
                    ),
                    "keyFacts": [
                        "Offers kaftans, blouses, and custom orders.",
                        "Provides shipping and order-tracking customer journeys.",
                    ],
                    "error": None,
                }
            )
            + "\n```",
        )


class WebsiteContextTests(unittest.TestCase):
    def test_extracts_unique_public_urls_and_ignores_private_targets(self):
        urls = extract_public_urls(
            "See https://pastelocity.com.my). Also HTTPS://EXAMPLE.COM/work#about "
            "and http://127.0.0.1/private and https://pastelocity.com.my/."
        )

        self.assertEqual(
            ["https://pastelocity.com.my/", "https://example.com/work"],
            urls,
        )

    def test_reads_exact_domain_with_private_structured_web_search(self):
        responses = FakeResponses()
        context = retrieve_website_context(
            url="https://pastelocity.com.my/#story",
            user_message="I built its end-to-end commerce workflows.",
            client=SimpleNamespace(responses=responses),
            model="openai/gpt-test",
        )

        self.assertEqual("Pastelocity", context.site_name)
        self.assertIn("modest-fashion", context.summary)
        self.assertEqual(
            ("https://pastelocity.com.my/",),
            context.source_urls,
        )
        prompt_context = context.as_prompt_dict()
        self.assertEqual("found", prompt_context["status"])
        self.assertEqual("https://pastelocity.com.my/", prompt_context["requestedUrl"])

        call = responses.calls[0]
        self.assertEqual("required", call["tool_choice"])
        self.assertEqual("openrouter:web_search", call["tools"][0]["type"])
        self.assertEqual(
            ["pastelocity.com.my"],
            call["tools"][0]["parameters"]["allowed_domains"],
        )
        self.assertEqual(WEBSITE_CONTEXT_SCHEMA, call["text"]["format"]["schema"])
        self.assertIn("end-to-end commerce workflows", call["input"])
        self.assertFalse(call["store"])
        self.assertTrue(call["extra_body"]["provider"]["zdr"])


if __name__ == "__main__":
    unittest.main()
