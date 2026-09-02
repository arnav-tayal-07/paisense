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

# Free-tier quota is per model — the 429 names it as
# "GenerateRequestsPerDayPerProjectPerModel" — so each entry below has its own
# independent daily allowance. Exhausting one falls through to the next, which
# multiplies the effective daily budget instead of stopping at the first wall.
#
# Ordered cheapest-and-largest-quota first. flash-lite is the default not for
# quality reasons but for quota: gemini-3.6-flash allows twenty requests PER
# DAY, and the lite models pass every extraction case identically. See ADR 022.
#
# Verified against the live API on 2026-08-30; 2.5-series models 404 on this
# key. Re-probe with scripts/probe_models.py if the chain starts failing.
DEFAULT_MODEL_CHAIN = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
]


def _model_chain() -> list[str]:
    """Models to try in order.

    GEMINI_MODEL pins a single model (useful for testing one specifically).
    GEMINI_MODELS overrides the whole chain as a comma-separated list.
    """
    pinned = os.getenv("GEMINI_MODEL")
    if pinned:
        return [pinned.strip()]
    configured = os.getenv("GEMINI_MODELS")
    if configured:
        return [m.strip() for m in configured.split(",") if m.strip()]
    return list(DEFAULT_MODEL_CHAIN)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(RuntimeError):
    """The provider could not be reached, or returned something unusable.

    Distinct from "the model looked at the input and said no" — that's a
    valid answer and comes back as data, not an exception.
    """


class QuotaExceeded(LLMError):
    """Out of requests for now. Retryable, unlike a malformed response.

    Worth its own type because the fix is different: waiting, or a different
    model, rather than changing anything about the message. raw_sms means
    these can all be replayed once quota returns.
    """


class ModelUnavailable(LLMError):
    """This particular model can't answer — missing, overloaded, or hanging.

    Like QuotaExceeded, it means "try the next model" rather than "give up".
    A malformed request, by contrast, would fail the same way on every model.
    """


class LLMProvider(Protocol):
    """The only thing the rest of the app is allowed to depend on."""

    def extract_json(self, instructions: str, text: str, schema: dict) -> dict:
        """Return the model's answer as a dict matching `schema`."""
        ...


class GeminiProvider:
    """Gemini via the REST API, constrained to JSON output.

    Tries each model in the chain until one answers. Only a quota or
    availability problem moves to the next — a malformed request would fail
    identically on every model, so retrying it four more times just burns
    four more models' quota for the same error.
    """

    def __init__(self, api_key: str | None = None, models: list[str] | None = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.models = models or _model_chain()
        # Remembers which model last worked, so a healthy fallback isn't
        # re-tested against an exhausted primary on every single message.
        self._preferred = 0
        if not self.api_key:
            raise LLMError(f"GEMINI_API_KEY not set. Expected it in {ENV_PATH}")

    def extract_json(self, instructions: str, text: str, schema: dict) -> dict:
        # Start from whichever model last succeeded, then wrap around so the
        # primary is still retried — daily quotas reset, and we want to drift
        # back to the preferred model rather than stay on a fallback forever.
        order = self.models[self._preferred :] + self.models[: self._preferred]
        problems = []

        for model in order:
            try:
                result = self._call(model, instructions, text, schema)
            except (QuotaExceeded, ModelUnavailable) as e:
                problems.append(f"{model}: {e}")
                continue

            self._preferred = self.models.index(model)
            return result

        # ASCII only: this string is stored in raw_sms.parse_error and read
        # back in consoles that aren't UTF-8.
        raise QuotaExceeded("every model in the chain is unavailable: " + "; ".join(problems))

    def _call(self, model: str, instructions: str, text: str, schema: dict) -> dict:
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

        url = _ENDPOINT.format(model=model)
        try:
            response = httpx.post(
                url,
                params={"key": self.api_key},
                json=payload,
                timeout=30.0,
            )
        except httpx.HTTPError as e:
            # Treated as unavailable rather than fatal: a model that hangs is
            # no more use than one that's out of quota, and the next one in
            # the chain may well answer. Observed for real — an exhausted
            # model stalled for 30s before it started returning clean 429s.
            raise ModelUnavailable(f"{model} did not respond: {e}") from e

        if response.status_code == 429:
            # Dig out which limit was hit. "429" alone tells you nothing —
            # a per-minute limit clears in seconds, a per-day limit doesn't.
            detail = f"model={model}"
            try:
                for d in response.json()["error"].get("details", []):
                    for v in d.get("violations", []):
                        detail += f" quota={v.get('quotaId')} limit={v.get('quotaValue')}"
                    if d.get("@type", "").endswith("RetryInfo"):
                        detail += f" retry_after={d.get('retryDelay')}"
            except (KeyError, ValueError):
                detail += f" {response.text[:200]}"
            raise QuotaExceeded(f"quota exceeded ({detail})")

        if response.status_code in (404, 503):
            # 404: not available on this key. 503: temporarily overloaded.
            # Both mean "try the next model", not "give up".
            raise ModelUnavailable(f"{model} returned {response.status_code}")

        if response.status_code != 200:
            # Anything else is a real error — a malformed request or a bad
            # schema would fail identically on every model, so failing fast
            # beats burning four more models' quota to learn the same thing.
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
