import os
import unittest
from unittest.mock import patch

from forge.errors import ProviderError
from forge.openrouter_client import (
    OPENROUTER_BASE_URL,
    create_openrouter_client,
    openrouter_request_options,
)


class OpenRouterClientTests(unittest.TestCase):
    def test_requires_openrouter_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ProviderError, "OPENROUTER_API_KEY"):
                create_openrouter_client()

    def test_configures_openrouter_endpoint_and_app_attribution(self):
        environment = {
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_HTTP_REFERER": "https://forge.example.test",
            "OPENROUTER_APP_NAME": "Forge Test",
        }
        with patch.dict(os.environ, environment, clear=True):
            with patch("openai.OpenAI") as client_class:
                create_openrouter_client()

        client_class.assert_called_once_with(
            api_key="test-key",
            base_url=OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": "https://forge.example.test",
                "X-OpenRouter-Title": "Forge Test",
            },
        )

    def test_private_routing_options_are_applied_per_request(self):
        self.assertEqual(
            {
                "provider": {
                    "zdr": True,
                    "data_collection": "deny",
                    "require_parameters": True,
                }
            },
            openrouter_request_options(),
        )


if __name__ == "__main__":
    unittest.main()
