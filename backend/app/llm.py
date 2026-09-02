"""LLM provider access, behind one small interface.

ADR 009 and 019: the provider is kept swappable on purpose. Everything above
this file speaks to `LLMProvider`, so moving from Gemini free tier to a
no-training tier, or to a different vendor entirely, changes this file and
nothing else.

Deliberately not using a vendor SDK. One HTTPS POST with a JSON body is the
whole integration, and an SDK would add a dependency, its own release cadence,
and a layer to debug through when a response isn't what we expected.
"""

import json
import os
from pathlib import Path
from typing import Protocol

import httpx
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

# Override in .env to try a different model without touching code. Model names
# change; check https://aistudio.google.com for what's current.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(RuntimeError):
    """The provider could not be reached, or returned something unusable.

    Distinct from "the model looked at the input and said no" — that's a
    valid answer and comes back as data, not an exception.
    """


class LLMProvider(Protocol):
    """The only thing the rest of the app is allowed to depend on."""

    def extract_json(self, instructions: str, text: str, schema: dict) -> dict:
        """Return the model's answer as a dict matching `schema`."""
        ...


class GeminiProvider:
    """Gemini via the REST API, constrained to JSON output."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model = model or GEMINI_MODEL
        if not self.api_key:
            raise LLMError(f"GEMINI_API_KEY not set. Expected it in {ENV_PATH}")

    def extract_json(self, instructions: str, text: str, schema: dict) -> dict:
        payload = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                # Constrained decoding: the model is forced to emit JSON
                # matching the schema. This is what makes the output parseable
                # every time instead of most of the time — no stray prose, no
                # markdown fences to strip.
                "responseMimeType": "application/json",
                "responseSchema": schema,
                # Extraction is not a creative task. The same message should
                # produce the same answer every time it's parsed.
                "temperature": 0,
            },
        }

        url = _ENDPOINT.format(model=self.model)
        try:
            response = httpx.post(
                url,
                params={"key": self.api_key},
                json=payload,
                timeout=30.0,
            )
        except httpx.HTTPError as e:
            raise LLMError(f"could not reach Gemini: {e}") from e

        if response.status_code != 200:
            # Body first, not just the status: Gemini explains quota and
            # bad-model errors in the payload, and "429" alone tells you
            # nothing about which limit you hit.
            raise LLMError(f"Gemini returned {response.status_code}: {response.text[:300]}")

        try:
            body = response.json()
            raw = body["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw)
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"unexpected Gemini response shape: {e}") from e


def default_provider() -> LLMProvider:
    """The provider the app uses. One line to change for the whole codebase."""
    return GeminiProvider()
