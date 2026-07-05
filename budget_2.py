"""
Local spend guard for the FRIDAY assistant.

This is a best-effort safety net, NOT a hard guarantee. On Cloud Run with
more than one instance (or after a cold start), this file resets per
instance, so the cap isn't perfectly global across all traffic.

For a real, unbreakable ceiling, set a monthly spend limit on your API key
in the Anthropic Console: console.anthropic.com -> Settings -> Workspaces
-> Limits. Use both together: the Console limit protects your wallet no
matter what, and this file stops a single chatty instance from wasting
calls on retries/loops during normal operation.
"""
import json
import os
import datetime

BUDGET_FILE = os.environ.get("BUDGET_FILE", "budget.json")

# Tune these in your environment (Cloud Run: --set-env-vars). Defaults are
# generous for one person talking to their own assistant.
MAX_DAILY_CALLS = int(os.environ.get("FRIDAY_MAX_DAILY_CALLS", "150"))
MAX_DAILY_OUTPUT_TOKENS = int(os.environ.get("FRIDAY_MAX_DAILY_OUTPUT_TOKENS", "30000"))


def _today() -> str:
    return datetime.date.today().isoformat()


def _load() -> dict:
    try:
        with open(BUDGET_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}

    if data.get("date") != _today():
        data = {"date": _today(), "calls": 0, "output_tokens": 0}

    return data


def _save(data: dict):
    try:
        with open(BUDGET_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def can_call() -> bool:
    """Check this BEFORE making an API call."""
    data = _load()
    return (
        data.get("calls", 0) < MAX_DAILY_CALLS
        and data.get("output_tokens", 0) < MAX_DAILY_OUTPUT_TOKENS
    )


def record_call(output_tokens: int):
    """Call this AFTER a successful API call to log what it cost."""
    data = _load()
    data["calls"] = data.get("calls", 0) + 1
    data["output_tokens"] = data.get("output_tokens", 0) + max(0, output_tokens)
    _save(data)


def status() -> dict:
    data = _load()
    return {
        "date": data.get("date"),
        "calls": data.get("calls", 0),
        "calls_limit": MAX_DAILY_CALLS,
        "output_tokens": data.get("output_tokens", 0),
        "output_tokens_limit": MAX_DAILY_OUTPUT_TOKENS,
    }
