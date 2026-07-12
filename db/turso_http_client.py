"""db/turso_http_client.py — stateless HTTP client for Turso, built to replace
db/turso_client.py (libsql Python bindings) after that module caused a
production crash loop: `failed to join thread: Resource deadlock avoided`,
a Rust-level panic in libsql's thread handling that a lock, fresh-connection-
per-call, and background-thread isolation all failed to fix (see git history
on db/turso_client.py). Root cause was libsql's own resource management
under this app's threading pattern (sync gunicorn workers + 10+ background
daemon threads), not something fixable by using the bindings more carefully.

This module sidesteps the problem class entirely: every call is one
stateless HTTP POST to Turso's /v2/pipeline endpoint (Hrana-over-HTTP) via
httpx, which is already used successfully elsewhere in this app (Groq,
ElevenLabs, JARVIS). There is no connection object, no session/baton kept
across calls, and therefore nothing to share (or deadlock on) across
threads — each request always ends with an explicit "close" so the server
never holds stream state for us between calls.

Same two generic shapes as the old client (see Stage 1 scan):
  - kv_*   — dict-keyed data. Table shape:
             (key TEXT PRIMARY KEY, data TEXT, updated_at TEXT).
  - list_* — flat lists of records. Table shape:
             (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, updated_at TEXT).

Deliberately not connecting/validating at import time — importable with no
env vars set, same optional-integration convention as the rest of this repo.
Every function raises on failure rather than swallowing errors.
"""
import os
import json
from datetime import datetime

import httpx

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class TursoNotConfigured(RuntimeError):
    pass


class TursoError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.environ.get("TURSO_DATABASE_URL")) and bool(os.environ.get("TURSO_AUTH_TOKEN"))


def _pipeline_url() -> str:
    url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not url or not token:
        raise TursoNotConfigured(
            "TURSO_DATABASE_URL / TURSO_AUTH_TOKEN not set — Turso is not configured."
        )
    http_url = url.replace("libsql://", "https://", 1)
    return f"{http_url}/v2/pipeline"


def _now() -> str:
    return datetime.now().isoformat()


def _encode_arg(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    if isinstance(value, (bytes, bytearray)):
        import base64
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    raise TursoError(f"Unsupported arg type: {type(value)!r}")


def _decode_cell(cell: dict):
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return cell["value"]
    if t == "text":
        return cell["value"]
    if t == "blob":
        import base64
        return base64.b64decode(cell["base64"])
    raise TursoError(f"Unsupported cell type in response: {t!r}")


def _execute(sql: str, args: list | None = None) -> dict:
    """Runs a single SQL statement as a one-shot stateless HTTP pipeline
    call and returns the parsed {"cols": [...], "rows": [[...], ...],
    "last_insert_rowid": int|None} result. No connection/session is held
    before or after this call — safe to call concurrently from any thread."""
    url = _pipeline_url()
    token = os.environ["TURSO_AUTH_TOKEN"]
    body = {
        "baton": None,
        "requests": [
            {
                "type": "execute",
                "stmt": {
                    "sql": sql,
                    "args": [_encode_arg(a) for a in (args or [])],
                },
            },
            {"type": "close"},
        ],
    }
    try:
        resp = httpx.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise TursoError(f"HTTP request to Turso failed: {e}") from e

    if resp.status_code >= 400:
        raise TursoError(f"Turso HTTP {resp.status_code}: {resp.text}")

    payload = resp.json()
    results = payload.get("results", [])
    if not results:
        raise TursoError(f"Empty results in Turso response: {payload}")

    first = results[0]
    if first.get("type") == "error":
        raise TursoError(f"Turso execute error: {first.get('error')}")

    result = first["response"]["result"]
    cols = [c["name"] for c in result.get("cols", [])]
    rows = [[_decode_cell(cell) for cell in row] for row in result.get("rows", [])]
    return {
        "cols": cols,
        "rows": rows,
        "last_insert_rowid": result.get("last_insert_rowid"),
    }


# ── Table setup ────────────────────────────────────────────────────────────

def ensure_kv_table(table: str):
    _execute(
        f"CREATE TABLE IF NOT EXISTS {table} "
        f"(key TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )


def ensure_list_table(table: str):
    _execute(
        f"CREATE TABLE IF NOT EXISTS {table} "
        f"(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )


# ── kv_* — dict-keyed data (habits, people, second_brain, profile) ─────────

def kv_get(table: str, key: str) -> dict | list | None:
    result = _execute(f"SELECT data FROM {table} WHERE key = ?", [key])
    if not result["rows"]:
        return None
    return json.loads(result["rows"][0][0])


def kv_set(table: str, key: str, data: dict | list):
    _execute(
        f"INSERT INTO {table} (key, data, updated_at) VALUES (?, ?, ?) "
        f"ON CONFLICT(key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
        [key, json.dumps(data), _now()],
    )


def kv_all(table: str) -> dict:
    result = _execute(f"SELECT key, data FROM {table}")
    return {key: json.loads(data) for key, data in result["rows"]}


# ── list_* — flat record lists (tasks, bills, journal, workouts, notes) ────

def list_insert(table: str, data: dict) -> int:
    result = _execute(
        f"INSERT INTO {table} (data, updated_at) VALUES (?, ?)",
        [json.dumps(data), _now()],
    )
    return result["last_insert_rowid"]


def list_all(table: str) -> list[dict]:
    result = _execute(f"SELECT id, data FROM {table} ORDER BY id")
    out = []
    for row_id, data in result["rows"]:
        record = json.loads(data)
        record.setdefault("id", row_id)
        out.append(record)
    return out


def list_update(table: str, row_id: int, data: dict):
    _execute(
        f"UPDATE {table} SET data = ?, updated_at = ? WHERE id = ?",
        [json.dumps(data), _now(), row_id],
    )
