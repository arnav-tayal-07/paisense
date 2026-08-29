"""Database access. One connection per request, opened and closed by a context manager.

Deliberately no connection pool: Supabase's session pooler is already pooling on
its side, and psycopg_pool would be another dependency for no gain at personal
scale. If Phase 5 shows connection setup is slow, revisit here and nowhere else.
"""

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Point at backend/.env explicitly rather than relying on the current working
# directory — otherwise the app only starts if you happen to launch it from
# the right folder, which is a confusing failure at 11pm.
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Fail loudly at import time. A missing URL should not surface later as a
    # confusing connection error on the first request.
    raise RuntimeError(f"DATABASE_URL not set. Expected it in {ENV_PATH}")


@contextmanager
def get_conn():
    """Yield a database connection, committing on success and closing always.

    row_factory=dict_row makes queries return dicts ({"id": 1, ...}) instead of
    tuples ((1, ...)), so results can be returned straight from a route as JSON.
    """
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        yield conn
