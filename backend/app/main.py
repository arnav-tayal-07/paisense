"""PaiSense API entry point.

Run from the backend/ folder:
    .venv\\Scripts\\uvicorn.exe app.main:app --reload

Interactive docs once it's up: http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI

from .db import get_conn

app = FastAPI(title="PaiSense API")


@app.get("/health")
def health():
    """Proves two things at once: the server is up, and the database answers.

    Worth having before any real route — when a transactions endpoint breaks
    later, this tells you instantly whether it's your SQL or the connection.
    """
    with get_conn() as conn:
        row = conn.execute("select 1 as ok").fetchone()
    return {"status": "ok", "db_connected": row["ok"] == 1}


# --- Phase 2 routes go below. These are yours to write. ---
#
# POST /transactions  — insert one row, return it
# GET  /transactions  — list recent rows, newest first
