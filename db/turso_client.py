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

Callers own the write-through cache decision (update in-memory cache,
then call this module, then let the cache be the fast path for reads) —
this module only owns talking to Turso itself. Every function here raises
on failure rather than swallowing errors, so a caller's fallback-to-JSON
logic (Stage 4) can actually detect that Turso failed instead of silently
no-op'ing.

No cached connection — every call opens a fresh libsql connection and
closes it when done. This app runs 10+ background daemon threads
(core/autonomous_agent.py's monitors) alongside the Flask request
thread; a single shared connection object, first created lazily on
whichever thread happened to call in first, hit a real Rust-level panic
in production ("failed to join thread: Resource deadlock avoided")
inside libsql's internal tokio runtime once a second thread touched it —
a classic signature of an async runtime being used from an OS thread
it doesn't have affinity for. Wrapping calls in a threading.Lock (tried
first) serialized *concurrent* access but didn't stop the *same*
connection object being reused *sequentially* across different threads
over time, and the timeouts continued (just without the panic message).
Opening a new connection per call sidesteps the cross-thread reuse
entirely — confirmed fast enough for this app's scale (~1s per fresh
connect+query in testing) and verified under concurrent load before
shipping. The lock is kept too: cheap, already proven safe, and adds
protection against separate concerns (e.g. many simultaneous fresh
connections during a burst) even though it's no longer the primary fix.
"""
import os
import json
import threading
from datetime import datetime

_lock = threading.Lock()


class TursoNotConfigured(RuntimeError):
    pass


def _connect():
    url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not url or not token:
        raise TursoNotConfigured(
            "TURSO_DATABASE_URL / TURSO_AUTH_TOKEN not set — Turso is not configured."
        )

    import libsql
    return libsql.connect(database=url, auth_token=token)


def is_configured() -> bool:
    return bool(os.environ.get("TURSO_DATABASE_URL")) and bool(os.environ.get("TURSO_AUTH_TOKEN"))


def _now() -> str:
    return datetime.now().isoformat()


# ── Table setup ────────────────────────────────────────────────────────────

def ensure_kv_table(table: str):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} "
                f"(key TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.commit()
        finally:
            conn.close()


def ensure_list_table(table: str):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} "
                f"(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.commit()
        finally:
            conn.close()


# ── kv_* — dict-keyed data (habits, people, second_brain, profile) ─────────

def kv_get(table: str, key: str) -> dict | list | None:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(f"SELECT data FROM {table} WHERE key = ?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            conn.close()


def kv_set(table: str, key: str, data: dict | list):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"INSERT INTO {table} (key, data, updated_at) VALUES (?, ?, ?) "
                f"ON CONFLICT(key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                (key, json.dumps(data), _now()),
            )
            conn.commit()
        finally:
            conn.close()


def kv_all(table: str) -> dict:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(f"SELECT key, data FROM {table}").fetchall()
            return {key: json.loads(data) for key, data in rows}
        finally:
            conn.close()


# ── list_* — flat record lists (tasks, bills, journal, workouts, notes) ────

def list_insert(table: str, data: dict) -> int:
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                f"INSERT INTO {table} (data, updated_at) VALUES (?, ?)",
                (json.dumps(data), _now()),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def list_all(table: str) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(f"SELECT id, data FROM {table} ORDER BY id").fetchall()
            out = []
            for row_id, data in rows:
                record = json.loads(data)
                record.setdefault("id", row_id)
                out.append(record)
            return out
        finally:
            conn.close()


def list_update(table: str, row_id: int, data: dict):
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE {table} SET data = ?, updated_at = ? WHERE id = ?",
                (json.dumps(data), _now(), row_id),
            )
            conn.commit()
        finally:
            conn.close()


def list_trim(table: str, keep: int):
    """Delete all but the `keep` most-recent rows (highest id) from a
    list_* table — the Turso-side equivalent of the old JSON files'
    `data[-N:]` cap, since list_insert has no size limit of its own."""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"DELETE FROM {table} WHERE id NOT IN "
                f"(SELECT id FROM {table} ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
            conn.commit()
        finally:
            conn.close()
