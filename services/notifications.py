"""services/notifications.py — the single place FRIDAY sends
notifications through, with priority tiers and a digest queue for
non-urgent signal. Every formerly-independent raw Pushover call site
(server.py, core/autonomous_agent.py, core/friday_capabilities.py,
core/config_validator.py, core/scatter.py, services/suit_lockdown.py,
services/checkin_system.py, services/friday_health.py,
services/hulkbuster.py) now routes through here — only priority >= HIGH
actually reaches Pushover/email/SMS, so routine nudges (weekly review,
news, hydration reminders) surface on the HUD without buzzing the phone,
while genuinely urgent things (battery critical, lockdown, HulkBuster,
MAYDAY, health emergencies) reach the boss directly instead of waiting
for Pushover's app or the HUD tab to be open — which is the whole point
of core/autonomous_agent.py deciding to speak up unprompted in the first
place: it doesn't help if nothing carries that past the machine it's
running on.

Reuses core/friday_capabilities.py's friday_caps._pushover_alert() for
the actual Pushover HTTP call rather than re-implementing it, and routes
through services/friday_hud.spawn_widget() for the HUD channel — FRIDAY
has no event bus (JARVIS's core/event_bus.py has no equivalent here), so
"HUD channel" means literally queuing a widget for the next poll, not a
pub/sub broadcast. Email/SMS reuse services/friday_gmail.py and
services/friday_phone.py the same way — both already no-op cleanly when
unconfigured, so email/sms need no extra "is this set up" gating here.
"""
from __future__ import annotations
import logging
import os
from datetime import datetime as _dt
from enum import IntEnum

log = logging.getLogger(__name__)

FRIDAY_NAME = os.getenv("FRIDAY_NAME", "FRIDAY")


class Priority(IntEnum):
    INFO = 0
    WARNING = 1
    HIGH = 2
    CRITICAL = 3


_PUSHOVER_PRIORITY = {Priority.INFO: -1, Priority.WARNING: 0, Priority.HIGH: 1, Priority.CRITICAL: 2}


def _pushover(title: str, message: str, priority: Priority, retry: int | None = None, expire: int | None = None):
    try:
        from core.friday_capabilities import friday_caps
        friday_caps._pushover_alert(
            title, message, priority=_PUSHOVER_PRIORITY[priority], retry=retry, expire=expire,
        )
    except Exception as e:
        log.warning("Pushover notify failed: %s", e)


def _hud_notify(title: str, message: str, priority: Priority):
    try:
        from services.friday_hud import spawn_widget
        spawn_widget("text", {"title": title, "message": message, "priority": priority.name})
    except Exception:
        pass


def _email(title: str, message: str):
    # Self-addressed — same convention as scatter.py's EmailDraftNode:
    # EMAIL_ADDRESS is the boss's own mailbox, used for both reading
    # (IMAP) and sending (SMTP), so an alert email is FRIDAY mailing the
    # boss's own inbox, not a third-party address.
    try:
        from services.friday_gmail import friday_gmail, GMAIL_USER
        if not GMAIL_USER:
            return
        friday_gmail.send_email(to=GMAIL_USER, subject=f"{FRIDAY_NAME}: {title}", body=message)
    except Exception as e:
        log.warning("Email notify failed: %s", e)


def _sms(title: str, message: str):
    try:
        from services.friday_phone import friday_phone
        to_number = os.environ.get("MY_PHONE_NUMBER", "")
        if not to_number:
            return
        friday_phone.send_sms(to_number, f"{title}: {message}"[:1500])
    except Exception as e:
        log.warning("SMS notify failed: %s", e)


def notify(title: str, message: str, priority: Priority = Priority.INFO, channels: list[str] | None = None,
           retry: int | None = None, expire: int | None = None):
    """Send a notification to all configured channels.

    channels: subset of ["pushover", "hud", "email", "sms"] — defaults to
    all four. Pushover/email/SMS only actually fire at priority >= HIGH
    (matches Pushover's own free-tier good manners — you don't want a
    text for every INFO event); HUD always queues regardless of priority,
    since it's local and free. Email/SMS silently no-op if EMAIL_ADDRESS
    or MY_PHONE_NUMBER/Twilio aren't configured — same "does nothing until
    set up" convention as everywhere else optional in this repo.

    retry/expire only apply at CRITICAL (Pushover's own emergency-priority
    retry-until-acked mechanism) — passed through to
    friday_caps._pushover_alert(), which supplies its own defaults
    (60s/1800s) when not given.
    """
    if channels is None:
        channels = ["pushover", "hud", "email", "sms"]

    log.info("[NOTIFY][%s] %s — %s", priority.name, title, message)

    if "hud" in channels:
        _hud_notify(title, message, priority)

    if priority >= Priority.HIGH:
        if "pushover" in channels:
            _pushover(title, message, priority, retry, expire)
        if "email" in channels:
            _email(title, message)
        if "sms" in channels:
            _sms(title, message)


def info(title: str, msg: str):     notify(title, msg, Priority.INFO)
def warning(title: str, msg: str):  notify(title, msg, Priority.WARNING)
def alert(title: str, msg: str):    notify(title, msg, Priority.HIGH)
def critical(title: str, msg: str, retry: int | None = None, expire: int | None = None):
    notify(title, msg, Priority.CRITICAL, retry=retry, expire=expire)


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
