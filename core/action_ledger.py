"""core/action_ledger.py — a durable record of what FRIDAY actually did,
and whether it worked.

_log() in core/app_state.py keeps the last exchanges in memory, truncated
to 200 characters, with no notion of outcome and no life beyond the
process. So nothing in this system can answer "did that email actually
send", "what have you done today", or "has this failed before" -- and on
Render, where the filesystem is ephemeral and the process restarts
freely, the answer disappears anyway.

That gap is why the SMTP bug took as long as it did. She said "sending
an email, boss" and meant it; the send timed out; nothing recorded a
failure; and the next attempt started from zero knowledge. Every debug
round had to be reconstructed from the boss's memory and Render's log
viewer.

An action here has two moments, deliberately separate:

    record()   before the work, returns an id, status "pending"
    resolve()  after it, with what actually happened

An entry that never resolves is not a gap in the data -- it is the most
interesting record in the file. It means FRIDAY started something and
never finished it, which is exactly the shape of a timeout, a crash, or
a worker killed at gunicorn's 30-second limit. Those stay visible as
"pending" rather than being cleaned up.

Nothing here may raise. It sits on the dispatch path, and a ledger that
can take a request down is worse than no ledger.
"""
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

LEDGER_FILE = Path("memory/friday_action_ledger.json")
LEDGER_TABLE = "action_ledger"

# Bounded because the local file is the fallback on an ephemeral disk and
# nothing else prunes it. Roughly a week of ordinary use.
MAX_ENTRIES = 500

# Anything still pending after this was almost certainly killed rather
# than finished -- gunicorn's own worker timeout is 30s, so nothing
# legitimate is still running at ten minutes.
STALE_AFTER = timedelta(minutes=10)

_lock = threading.Lock()


def _turso():
    """The Turso client, or None. Imported lazily: the ledger has to work
    on a box with no database configured, and an import error here would
    take the dispatch path down with it."""
    try:
        from db import turso_http_client as turso
        return turso if turso.is_configured() else None
    except Exception:
        return None


def _read_local() -> list:
    try:
        return json.loads(LEDGER_FILE.read_text())
    except Exception:
        return []


def _write_local(entries: list):
    try:
        LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
        LEDGER_FILE.write_text(json.dumps(entries[-MAX_ENTRIES:], indent=2))
    except Exception:
        logging.warning("[ledger] local write failed", exc_info=True)


def record(prompt: str, capability: str, mode: str = "") -> str | None:
    """Note that FRIDAY is about to do something. Returns an id for
    resolve(), or None if the ledger is unavailable -- callers treat that
    as "don't bother resolving", never as an error."""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "prompt": (prompt or "")[:500],
        "capability": capability,
        "mode": mode,
        "status": "pending",
        "detail": "",
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
    }
    try:
        with _lock:
            entries = _read_local()
            entries.append(entry)
            _write_local(entries)

        turso = _turso()
        if turso:
            try:
                turso.ensure_list_table(LEDGER_TABLE)
                turso.list_insert(LEDGER_TABLE, entry)
            except Exception:
                # The local copy already succeeded; a database that's
                # down must not cost the caller its action.
                logging.warning("[ledger] turso insert failed", exc_info=True)
        return entry["id"]
    except Exception:
        logging.warning("[ledger] record failed", exc_info=True)
        return None


def resolve(entry_id: str | None, status: str, detail: str = ""):
    """Close an entry out. status is "ok" or "failed"."""
    if not entry_id:
        return
    try:
        with _lock:
            entries = _read_local()
            for e in entries:
                if e.get("id") == entry_id:
                    e["status"] = status
                    e["detail"] = (detail or "")[:500]
                    e["finished_at"] = datetime.now().isoformat()
                    break
            else:
                return
            _write_local(entries)

        turso = _turso()
        if turso:
            try:
                for row in turso.list_all(LEDGER_TABLE):
                    if row.get("id") == entry_id:
                        row.update(status=status, detail=(detail or "")[:500],
                                   finished_at=datetime.now().isoformat())
                        turso.list_update(LEDGER_TABLE, row["id"], row)
                        break
            except Exception:
                logging.warning("[ledger] turso update failed", exc_info=True)
    except Exception:
        logging.warning("[ledger] resolve failed", exc_info=True)


def _stale(entry: dict) -> bool:
    if entry.get("status") != "pending":
        return False
    try:
        started = datetime.fromisoformat(entry["started_at"])
    except Exception:
        return False
    return datetime.now() - started > STALE_AFTER


def recent(limit: int = 20, capability: str = "") -> list:
    """Newest first. Entries left pending past STALE_AFTER are reported as
    "abandoned" rather than pending -- the process that owned them is long
    gone, and calling that "in progress" would be a lie the ledger tells
    about itself."""
    try:
        with _lock:
            entries = _read_local()
    except Exception:
        return []

    out = []
    for e in reversed(entries):
        if capability and e.get("capability") != capability:
            continue
        e = dict(e)
        if _stale(e):
            e["status"] = "abandoned"
        out.append(e)
        if len(out) >= limit:
            break
    return out


def failures(limit: int = 10) -> list:
    return [e for e in recent(limit=MAX_ENTRIES)
            if e["status"] in ("failed", "abandoned")][:limit]


def summary(hours: int = 24) -> dict:
    """Counts for the window, for FRIDAY to answer "how did today go"
    without reading every row aloud."""
    cutoff = datetime.now() - timedelta(hours=hours)
    counts = {"ok": 0, "failed": 0, "abandoned": 0, "pending": 0}
    by_capability = {}
    for e in recent(limit=MAX_ENTRIES):
        try:
            if datetime.fromisoformat(e["started_at"]) < cutoff:
                continue
        except Exception:
            continue
        counts[e["status"]] = counts.get(e["status"], 0) + 1
        if e["status"] in ("failed", "abandoned"):
            by_capability[e["capability"]] = by_capability.get(e["capability"], 0) + 1
    return {"hours": hours, "counts": counts, "failing_capabilities": by_capability}
