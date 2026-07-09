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


# Approximate published per-output-token rates (USD per token, i.e.
# price-per-million-tokens / 1,000,000) — for a rough running total, not a
# billing-accurate ledger. Matched by substring against the model id, so it
# still works if the exact dated model string changes. Falls back to 0 (not
# a fabricated guess) for anything that doesn't match a known family.
_OUTPUT_RATE_PER_TOKEN = {
    "haiku": 5.00 / 1_000_000,
    "sonnet": 15.00 / 1_000_000,
    "opus": 75.00 / 1_000_000,
}


def _estimate_cost(model: str, output_tokens: int) -> float:
    for family, rate in _OUTPUT_RATE_PER_TOKEN.items():
        if family in (model or "").lower():
            return round(output_tokens * rate, 6)
    return 0.0


def _load() -> dict:
    try:
        with open(BUDGET_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}

    if data.get("date") != _today():
        data = {"date": _today(), "calls": 0, "output_tokens": 0, "cost_usd": 0.0}

    data.setdefault("cost_usd", 0.0)
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


def record_call(output_tokens: int, model: str = ""):
    """Call this AFTER a successful API call to log what it cost. `model`
    is optional — omitting it just skips the cost estimate for that call
    (cost_usd stays accurate for everything else, never guesses)."""
    data = _load()
    data["calls"] = data.get("calls", 0) + 1
    data["output_tokens"] = data.get("output_tokens", 0) + max(0, output_tokens)
    data["cost_usd"] = round(data.get("cost_usd", 0.0) + _estimate_cost(model, max(0, output_tokens)), 6)
    _save(data)


def status() -> dict:
    data = _load()
    return {
        "date": data.get("date"),
        "calls": data.get("calls", 0),
        "calls_limit": MAX_DAILY_CALLS,
        "output_tokens": data.get("output_tokens", 0),
        "output_tokens_limit": MAX_DAILY_OUTPUT_TOKENS,
        "cost_usd": data.get("cost_usd", 0.0),
    }
