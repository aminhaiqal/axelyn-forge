"""OpenRouter client construction and privacy-first request options."""

import os
from typing import Any, Dict

from .errors import ProviderError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_APP_URL = "https://forge.axelyn.com"
OPENROUTER_APP_NAME = "Axelyn Forge"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-5.4-mini"
DEFAULT_OPENROUTER_FAST_MODEL = "openai/gpt-5.4-nano"


def create_openrouter_client():
    """Build an OpenAI-compatible client that only talks to OpenRouter."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ProviderError(
            "OPENROUTER_API_KEY is required for AI-assisted Forge commands"
        )

    try:
        from openai import OpenAI

        return OpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": os.environ.get(
                    "OPENROUTER_HTTP_REFERER", OPENROUTER_APP_URL
                ),
                "X-OpenRouter-Title": os.environ.get(
                    "OPENROUTER_APP_NAME", OPENROUTER_APP_NAME
                ),
            },
        )
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(
            "Could not initialize the OpenRouter client; install the project dependencies"
        ) from exc


def openrouter_request_options() -> Dict[str, Any]:
    """Return routing rules suitable for private resume and cover-letter data."""
    return {
        "provider": {
            "zdr": True,
            "data_collection": "deny",
            "require_parameters": True,
        }
    }
