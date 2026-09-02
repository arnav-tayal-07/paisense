"""A lock on the door.

NOT user authentication. One shared key that says "this request came from my
phone", which is the correct amount of security for a single-user app whose
API URL is published in a public repo.

When PaiSense becomes multi-user this file gets replaced by real per-user
auth. Until then the alternative isn't "simpler" — it's "anyone who reads the
README can delete your transactions".
"""

import hmac
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Request
from fastapi.responses import JSONResponse

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

API_KEY = os.getenv("PAISENSE_API_KEY")

# Open on purpose:
#   /health  - the keepalive pings it, and it reveals nothing but "yes, alive"
#   /docs    - describes the API shape, not the data. Handy while developing.
_OPEN_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


async def require_api_key(request: Request, call_next):
    """Reject anything without the shared key, except the open paths above."""
    if request.url.path in _OPEN_PATHS:
        return await call_next(request)

    if not API_KEY:
        # Fail closed. An unset key must not silently mean "allow everyone" —
        # that turns a missing environment variable into an open database.
        return JSONResponse(
            status_code=503,
            content={"detail": "PAISENSE_API_KEY is not configured on the server"},
        )

    supplied = request.headers.get("x-api-key", "")

    # compare_digest rather than ==: a plain comparison returns as soon as it
    # finds a differing character, so how long it takes leaks how much of the
    # key was right. Overkill here, and it costs one import.
    if not hmac.compare_digest(supplied, API_KEY):
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing X-API-Key"})

    return await call_next(request)
