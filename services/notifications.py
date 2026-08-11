"""services/notifications.py — a single place for new code to send
notifications through, with priority tiers and a digest queue for
non-urgent signal. FRIDAY already has several independent raw Pushover
call sites (server.py, core/autonomous_agent.py, core/friday_capabilities.py,
services/suit_lockdown.py, services/checkin_system.py) — this doesn't
replace those (a real refactor of five call sites is its own careful
change, not bundled into this one), it's the canonical path for
everything built from here on, starting with services/scheduler.py.

Reuses core/friday_capabilities.py's friday_caps._pushover_alert() for
the actual Pushover HTTP call rather than re-implementing it, and routes
through services/friday_hud.spawn_widget() for the HUD channel — FRIDAY
has no event bus (JARVIS's core/event_bus.py has no equivalent here), so
"HUD channel" means literally queuing a widget for the next poll, not a
pub/sub broadcast.
"""
from __future__ import annotations
import logging
from datetime import datetime as _dt
from enum import IntEnum

log = logging.getLogger(__name__)


class Priority(IntEnum):
    INFO = 0
    WARNING = 1
    HIGH = 2
    CRITICAL = 3


_PUSHOVER_PRIORITY = {Priority.INFO: -1, Priority.WARNING: 0, Priority.HIGH: 1, Priority.CRITICAL: 2}


def _pushover(title: str, message: str, priority: Priority):
    try:
        from core.friday_capabilities import friday_caps
        friday_caps._pushover_alert(title, message, priority=_PUSHOVER_PRIORITY[priority])
    except Exception as e:
        log.warning("Pushover notify failed: %s", e)


def _hud_notify(title: str, message: str, priority: Priority):
    try:
        from services.friday_hud import spawn_widget
        spawn_widget("text", {"title": title, "message": message, "priority": priority.name})
    except Exception:
        pass


def notify(title: str, message: str, priority: Priority = Priority.INFO, channels: list[str] | None = None):
    """Send a notification to all configured channels.

    channels: subset of ["pushover", "hud"] — defaults to both. Pushover
    only actually fires at priority >= HIGH (matches Pushover's own free-tier
    good manners — you don't want a push notification for every INFO event);
    HUD always queues regardless of priority, since it's local and free.
    """
    if channels is None:
        channels = ["pushover", "hud"]

    log.info("[NOTIFY][%s] %s — %s", priority.name, title, message)

    if "hud" in channels:
        _hud_notify(title, message, priority)

    if priority >= Priority.HIGH and "pushover" in channels:
        _pushover(title, message, priority)


def info(title: str, msg: str):     notify(title, msg, Priority.INFO)
def warning(title: str, msg: str):  notify(title, msg, Priority.WARNING)
def alert(title: str, msg: str):    notify(title, msg, Priority.HIGH)
def critical(title: str, msg: str): notify(title, msg, Priority.CRITICAL)


# ── Digest queue ─────────────────────────────────────────────────────────────
# For signal that's real but not urgent (a multi-day trend, a routine
# summary) — firing a push notification the moment each one's detected
# trains you to ignore notifications. queue_digest() holds items in memory;
# flush_digest() (intended to be called once/day by services/scheduler.py)
# sends everything queued as one batched notification. In-memory only — a
# restart between queue and flush drops pending items, an acceptable trade
# for a personal assistant where nothing here is safety-critical.
_digest_queue: list[dict] = []


def queue_digest(category: str, message: str):
    _digest_queue.append({"category": category, "message": message, "ts": _dt.now().isoformat()})
    log.info("Queued digest notification [%s]: %s", category, message)


def flush_digest(title: str = "FRIDAY Daily Digest"):
    """Send everything queued via queue_digest() as one notification, then
    clear the queue. No-op if empty — no 'nothing happened' pings."""
    global _digest_queue
    if not _digest_queue:
        return
    lines = [f"- [{item['category']}] {item['message']}" for item in _digest_queue]
    body = "\n".join(lines)
    count = len(_digest_queue)
    _digest_queue = []
    notify(f"{title} ({count} item{'s' if count != 1 else ''})", body, Priority.HIGH)
