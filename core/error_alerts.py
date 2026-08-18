"""core/error_alerts.py — surfaces uncaught exceptions instead of them
disappearing into Render's logs where nobody's watching. Before this,
the only way to learn something crashed server-side was to notice FRIDAY
acting wrong and go dig through logs after the fact.

Deduped per (route, exception type) within a window — a route that's
persistently broken and getting hit every few seconds shouldn't fire a
notification every single time; one alert per recurring failure is
enough to know something needs attention.
"""
import time
import traceback

_DEDUPE_WINDOW_SECONDS = 900  # 15 minutes
_last_alerted: dict[str, float] = {}


def report(route: str, exc: Exception):
    key = f"{route}:{type(exc).__name__}"
    now = time.time()
    if now - _last_alerted.get(key, 0) < _DEDUPE_WINDOW_SECONDS:
        return
    _last_alerted[key] = now

    tb = traceback.format_exc()
    try:
        from services.notifications import critical
        critical(
            "FRIDAY — Unhandled Error",
            f"{route}: {type(exc).__name__}: {exc}\n\n{tb[-800:]}",
        )
    except Exception:
        pass
