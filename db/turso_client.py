"""db/turso_client.py — thin Turso (libSQL) client for FRIDAY's memory
data layer. Render's web service has no persistent disk (confirmed via
render.yaml having no `disk:` block), so local memory/*.json files get
wiped on every deploy/restart. This module is the replacement source of
truth; the JSON files it replaces are being migrated one at a time.

Two generic shapes cover every file being migrated (see the Stage 1 scan):
  - kv_*   — dict-keyed data (habits by name, people by name, second_brain
             by content hash, profile as a single fixed key). Table shape:
             (key TEXT PRIMARY KEY, data TEXT, updated_at TEXT).
  - list_* — flat lists of records (tasks, bills, journal, workouts,
             notes). Table shape:
             (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, updated_at TEXT).

Deliberately not connecting at import time — this module has to be
importable (and the rest of the app has to keep working) even before
TURSO_DATABASE_URL/TURSO_AUTH_TOKEN are set, same as every other
optional-integration module in this repo (see the try/except import
pattern in server.py). Connection is lazy, made on first real call.

Callers own the write-through cache decision (update in-memory cache,
then call this module, then let the cache be the fast path for reads) —
this module only owns talking to Turso itself. Every function here raises
on failure rather than swallowing errors, so a caller's fallback-to-JSON
logic (Stage 4) can actually detect that Turso failed instead of silently
no-op'ing.
"""
import os
import json
from datetime import datetime

_conn = None


class TursoNotConfigured(RuntimeError):
    pass


def _connect():
    global _conn
    if _conn is not None:
        return _conn

    url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not url or not token:
        raise TursoNotConfigured(
            "TURSO_DATABASE_URL / TURSO_AUTH_TOKEN not set — Turso is not configured."
        )

    import libsql
    _conn = libsql.connect(database=url, auth_token=token)
    return _conn


def is_configured() -> bool:
    return bool(os.environ.get("TURSO_DATABASE_URL")) and bool(os.environ.get("TURSO_AUTH_TOKEN"))


def _now() -> str:
    return datetime.now().isoformat()


# ── Table setup ────────────────────────────────────────────────────────────

def ensure_kv_table(table: str):
    conn = _connect()
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {table} "
        f"(key TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.commit()


def ensure_list_table(table: str):
    conn = _connect()
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {table} "
        f"(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.commit()


# ── kv_* — dict-keyed data (habits, people, second_brain, profile) ─────────

def kv_get(table: str, key: str) -> dict | list | None:
    conn = _connect()
    row = conn.execute(f"SELECT data FROM {table} WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def kv_set(table: str, key: str, data: dict | list):
    conn = _connect()
    conn.execute(
        f"INSERT INTO {table} (key, data, updated_at) VALUES (?, ?, ?) "
        f"ON CONFLICT(key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
        (key, json.dumps(data), _now()),
    )
    conn.commit()


def kv_all(table: str) -> dict:
    conn = _connect()
    rows = conn.execute(f"SELECT key, data FROM {table}").fetchall()
    return {key: json.loads(data) for key, data in rows}


# ── list_* — flat record lists (tasks, bills, journal, workouts, notes) ────

def list_insert(table: str, data: dict) -> int:
    conn = _connect()
    cur = conn.execute(
        f"INSERT INTO {table} (data, updated_at) VALUES (?, ?)",
        (json.dumps(data), _now()),
    )
    conn.commit()
    return cur.lastrowid


def list_all(table: str) -> list[dict]:
    conn = _connect()
    rows = conn.execute(f"SELECT id, data FROM {table} ORDER BY id").fetchall()
    out = []
    for row_id, data in rows:
        record = json.loads(data)
        record.setdefault("id", row_id)
        out.append(record)
    return out


def list_update(table: str, row_id: int, data: dict):
    conn = _connect()
    conn.execute(
        f"UPDATE {table} SET data = ?, updated_at = ? WHERE id = ?",
        (json.dumps(data), _now(), row_id),
    )
    conn.commit()
