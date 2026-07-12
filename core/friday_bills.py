"""core/friday_bills.py — bills data access, shared by server.py's
/friday/bills/add route and core/autonomous_agent.py's _bill_check
monitor. Previously each read memory/friday_bills.json independently
through its own duplicated Path constant; centralized here so the Turso
migration only has one read/write path to get right instead of two that
could silently drift apart.
"""
import json
from pathlib import Path
from datetime import datetime

from db import turso_http_client as turso

BASE_DIR = Path(__file__).resolve().parent.parent
BILLS_FILE = BASE_DIR / "memory" / "friday_bills.json"
BILLS_TABLE = "bills"


def _read_local() -> list:
    if BILLS_FILE.exists():
        try:
            return json.loads(BILLS_FILE.read_text())
        except Exception:
            return []
    return []


def _write_local(bills: list):
    BILLS_FILE.parent.mkdir(parents=True, exist_ok=True)
    BILLS_FILE.write_text(json.dumps(bills, indent=2))


def get_bills() -> list:
    if turso.is_configured():
        rows = None
        try:
            turso.ensure_list_table(BILLS_TABLE)
            rows = turso.list_all(BILLS_TABLE)
        except Exception as e:
            print(f"[Turso] bills read failed, falling back to local JSON: {e}")
        if rows:
            return rows
        if rows is not None:
            local = _read_local()
            for record in local:
                try:
                    turso.list_insert(BILLS_TABLE, record)
                except Exception as e:
                    print(f"[Turso] bills seed failed: {e}")
            return local
    return _read_local()


def add_bill(name: str, amount, due_day) -> dict:
    record = {
        "name": name, "amount": amount, "due_day": due_day,
        "added": datetime.now().isoformat(),
    }

    bills = _read_local()
    bills.append(record)
    _write_local(bills)

    if turso.is_configured():
        try:
            turso.ensure_list_table(BILLS_TABLE)
            turso.list_insert(BILLS_TABLE, record)
        except Exception as e:
            print(f"[Turso] bills write failed, local JSON already has it: {e}")

    return record
