"""services/friday_emergency.py — FRIDAY's emergency alert system (honest edition).

What it does: starts a CANCELABLE countdown, then texts your emergency contacts
your situation and a map link, and tells YOU exactly which sends were accepted.

What it deliberately does NOT do:
  * It never dials 911. Software can't reliably do that (Twilio doesn't support
    911 on standard numbers) and a false auto-dial is a real offence. The user
    interface always offers a one-tap tel:911 link instead, and every reply says
    plainly that FRIDAY can't call 911 for you.
  * It never claims more than it knows. Twilio "accepted" means the carrier took
    the message, not that anyone read it, and the summary says exactly that.
    (The capability this replaces spoke "Emergency services contacted" and
    returned contacted=True while only buzzing the user's own phone.)

Safeguards against false alarms: countdown (5-60s, default 15) with cancel and
send-now; one live alert at a time; max 3 real alerts/hour; drill mode that
sends nothing. Config is env-only so it works even if Turso is down:
  EMERGENCY_CONTACTS="Mom=+15551234567,Sam=+15557654321"
  EMERGENCY_USER_NAME, EMERGENCY_MEDICAL_NOTE (optional, goes in the SMS),
  EMERGENCY_COUNTDOWN_SECONDS, EMERGENCY_CALL_FIRST=true (also phone the first contact).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

log = logging.getLogger(__name__)

COUNTDOWN_DEFAULT = 15
COUNTDOWN_MIN = 5
COUNTDOWN_MAX = 60
MAX_LIVE_PER_HOUR = 3
MAX_KEPT = 50
# Restart safety. An alert lives in memory and a threading.Timer, so a restart/OOM
# mid-countdown used to make it VANISH silently. Alerts are now also saved to
# Turso and recovered on boot:
RECOVERY_MARGIN = 20      # s past the deadline before a recovered alert fires, so a still-alive old
                          # instance (zero-downtime deploy overlap) gets to send it first
RECOVERY_GRACE = 600      # s: an alert overdue by more than this is NOT sent (stale); the user is told
RETRY_DELAY = 2.0         # s before the single automatic retry of a failed text
ALERT_TABLE = "emergency_alerts"
CALL_911 = "tel:911"
CALL_911_NOTE = "I can't call 911 for you. If this may be life-threatening, call 911 yourself now."

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
_SENT_STATES = {"sending", "sent", "partial", "failed", "not_configured"}


def _clean(text, n: int) -> str:
    return _CTRL.sub(" ", "" if text is None else str(text)).strip()[:n]


def mask(number: str) -> str:
    return f"…{number[-4:]}" if number else ""


def parse_contacts(raw: str) -> tuple[list[dict], list[str]]:
    """'Mom=+15551234567, Sam=+15557654321' -> ([{name, number}], [problems])."""
    contacts, problems, seen = [], [], set()
    for part in re.split(r"[;,\n]+", raw or ""):
        part = part.strip()
        if not part:
            continue
        name, sep, number = part.partition("=")
        if not sep:
            name, number = "", part
        number = re.sub(r"[\s().\-]", "", number.strip())
        if not _E164.match(number):
            problems.append(f"ignored '{_clean(name or part, 12)}': use +15551234567 format")
            continue
        if number in seen:
            continue
        seen.add(number)
        contacts.append({"name": _clean(name, 40) or mask(number), "number": number})
    return contacts, problems


def _default_send_sms(number: str, text: str) -> dict:
    try:
        from services.friday_phone import friday_phone
        return friday_phone.send_sms(number, text)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}


def _default_send_call(number: str, text: str) -> dict:
    try:
        from services import friday_phone as fp
        if not fp._twilio_configured():
            return {"error": "Twilio not configured"}
        from twilio.rest import Client
        say = _xml_escape(text)
        twiml = (f'<Response><Say voice="Polly.Joanna" rate="90%">{say}</Say><Pause length="1"/>'
                 f'<Say voice="Polly.Joanna" rate="90%">{say}</Say></Response>')
        call = Client(fp.TWILIO_SID, fp.TWILIO_TOKEN).calls.create(twiml=twiml, from_=fp.TWILIO_FROM, to=number)
        return {"ok": True, "sid": call.sid}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}


def _default_notify(title: str, body: str) -> None:
    try:
        from services.notifications import critical
        critical(title, body)
    except Exception:
        pass


class _NullStore:
    """No durability (tests, or Turso not configured)."""
    def save(self, rec: dict) -> None: ...
    def load_all(self) -> list[dict]: return []
    def get_state(self, alert_id: str): return None


class TursoStore:
    """Durable copy of alerts in Turso. Every method may raise; the manager treats
    persistence as best-effort and NEVER lets it delay or block an alert."""
    def __init__(self):
        self._ensured = False

    def _db(self):
        from db import turso_http_client as t
        if not t.is_configured():
            return None
        if not self._ensured:
            t._execute(f"CREATE TABLE IF NOT EXISTS {ALERT_TABLE} "
                       f"(id TEXT PRIMARY KEY, state TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)")
            self._ensured = True
        return t

    def save(self, rec: dict) -> None:
        t = self._db()
        if t:
            t._execute(f"INSERT OR REPLACE INTO {ALERT_TABLE} (id, state, data, updated_at) VALUES (?, ?, ?, ?)",
                       [rec["id"], rec["state"], json.dumps(rec), datetime.now(timezone.utc).isoformat()])

    def load_all(self) -> list[dict]:
        t = self._db()
        if not t:
            return []
        rows = t._execute(f"SELECT data FROM {ALERT_TABLE} ORDER BY updated_at DESC LIMIT 20")["rows"]
        return [json.loads(r[0]) for r in rows]

    def get_state(self, alert_id: str):
        t = self._db()
        if not t:
            return None
        rows = t._execute(f"SELECT state FROM {ALERT_TABLE} WHERE id = ?", [alert_id])["rows"]
        return rows[0][0] if rows else None


class EmergencyManager:
    def __init__(self, send_sms=None, send_call=None, notify=None, timer_factory=threading.Timer,
                 clock=time.time, contacts_provider=None, store=None, persist_async=True,
                 sleep=time.sleep, retry_delay=RETRY_DELAY):
        self._store = store if store is not None else TursoStore()
        self._persist_async = persist_async
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="emergency-persist") if persist_async else None
        self._sleep = sleep
        self._retry_delay = retry_delay
        self._send_sms = send_sms or _default_send_sms
        self._send_call = send_call or _default_send_call
        self._notify = notify or _default_notify
        self._timer_factory = timer_factory
        self._clock = clock
        self._contacts_provider = contacts_provider
        self._lock = threading.RLock()
        self._alerts: dict[str, dict] = {}
        self._order: list[str] = []

    # ── config ────────────────────────────────────────────────────────────
    def contacts(self) -> list[dict]:
        if self._contacts_provider:
            return self._contacts_provider()
        return parse_contacts(os.getenv("EMERGENCY_CONTACTS", ""))[0]

    def readiness(self) -> dict:
        contacts, problems = parse_contacts(os.getenv("EMERGENCY_CONTACTS", ""))
        try:
            from services import friday_phone as fp
            twilio = fp._twilio_configured()
        except Exception:
            twilio = False
        try:
            from core import access_auth
            auth = access_auth.is_configured()
        except Exception:
            auth = False
        issues = list(problems)
        if not contacts:
            issues.append("EMERGENCY_CONTACTS is empty - alerts would reach NOBODY.")
        if not twilio:
            issues.append("Twilio is not configured (TWILIO_ACCOUNT_SID / AUTH_TOKEN / PHONE) - no texts can be sent.")
        if not auth:
            issues.append("FRIDAY_ACCESS_TOKEN is not set - emergency routes stay disabled until it is.")
        warnings = []
        try:
            from db import turso_http_client as _t
            if not _t.is_configured():
                warnings.append("Turso is not configured: an alert in progress is LOST if the server restarts.")
        except Exception:
            warnings.append("Turso unavailable: an alert in progress is LOST if the server restarts.")
        return {"ready": not issues, "warnings": warnings,
                "contacts": [{"name": c["name"], "number": mask(c["number"])} for c in contacts],
                "twilio": twilio, "auth": auth, "countdown_seconds": self._default_countdown(),
                "call_first": os.getenv("EMERGENCY_CALL_FIRST", "").lower() in ("1", "true", "yes"),
                "issues": issues, "call_911": CALL_911, "note": CALL_911_NOTE}

    @staticmethod
    def _default_countdown() -> int:
        try:
            return max(COUNTDOWN_MIN, min(COUNTDOWN_MAX, int(os.getenv("EMERGENCY_COUNTDOWN_SECONDS", COUNTDOWN_DEFAULT))))
        except ValueError:
            return COUNTDOWN_DEFAULT

    # ── message ───────────────────────────────────────────────────────────
    def build_message(self, a: dict) -> str:
        who = _clean(os.getenv("EMERGENCY_USER_NAME", ""), 40) or "your contact"
        loc = (f"Location: {a['location_url']}" + (f" (+/-{int(a['accuracy'])} m)" if a.get("accuracy") else "")
               if a.get("location_url") else "Location: unavailable")
        med = _clean(os.getenv("EMERGENCY_MEDICAL_NOTE", ""), 200)
        when = self._when(a["created"])
        body = (f"EMERGENCY ALERT from {who}: {a['reason'] or 'no details given'}. {loc}. "
                f"{('Medical note: ' + med + '. ') if med else ''}"
                f"Sent automatically by FRIDAY at {when}. Try to reach them now; if you can't and it may be "
                f"life-threatening, call 911.")
        return ("[DRILL - NOT A REAL EMERGENCY] " + body) if a["drill"] else body

    @staticmethod
    def _when(ts: float) -> str:
        """Local time for the people reading the text ("2:32 PM EDT"); UTC if no zone is set."""
        tz = os.getenv("EMERGENCY_TIMEZONE", "").strip()
        if tz:
            try:
                from zoneinfo import ZoneInfo
                return datetime.fromtimestamp(ts, ZoneInfo(tz)).strftime("%I:%M %p %Z").lstrip("0")
            except Exception:
                pass
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M UTC")

    # ── lifecycle ─────────────────────────────────────────────────────────
    def trigger(self, reason: str = "", lat=None, lon=None, accuracy=None, drill: bool = False,
                countdown=None, source: str = "app") -> dict:
        with self._lock:
            live = self._latest_pending()
            if live:                                          # one live alert at a time
                return {**self._public(live), "existing": True}
            if not drill and self._recent_live_count() >= MAX_LIVE_PER_HOUR:
                return {"ok": False, "state": "rate_limited", "call_911": CALL_911, "note": CALL_911_NOTE,
                        "summary": f"{MAX_LIVE_PER_HOUR} alerts already went out in the last hour; not sending another "
                                   f"automatically. Call someone or 911 directly."}
            seconds = self._default_countdown() if countdown is None else max(COUNTDOWN_MIN, min(COUNTDOWN_MAX, int(countdown)))
            url = (f"https://www.google.com/maps?q={float(lat):.5f},{float(lon):.5f}"
                   if lat is not None and lon is not None else "")
            a = {"id": uuid.uuid4().hex[:10], "state": "pending", "drill": bool(drill), "reason": _clean(reason, 200),
                 "location_url": url, "accuracy": accuracy, "source": _clean(source, 20), "created": self._clock(),
                 "deadline": self._clock() + seconds, "results": [], "summary": ""}
            timer = self._timer_factory(seconds, self._fire, args=(a["id"],))
            timer.daemon = True
            a["_timer"] = timer
            self._alerts[a["id"]] = a
            self._order.append(a["id"])
            self._trim()
            timer.start()
            self._persist(a)
            log.warning("Emergency alert %s armed (%ss, drill=%s, source=%s)", a["id"], seconds, a["drill"], a["source"])
            return self._public(a)

    def cancel(self, alert_id: str | None = None) -> dict:
        with self._lock:
            a = self._alerts.get(alert_id) if alert_id else self._latest_pending()
            if a is None:
                return {"ok": False, "state": "none", "summary": "There's no pending alert to cancel."}
            if a["state"] != "pending":
                return {**self._public(a), "ok": False,
                        "summary": f"Too late to cancel: that alert is already '{a['state']}'. {a['summary']}"}
            t = a.pop("_timer", None)
            if t:
                t.cancel()
            a["state"] = "cancelled"
            a["summary"] = "Cancelled before sending. Nobody was notified."
            self._persist(a)
            return self._public(a)

    def update_location(self, alert_id: str | None, lat, lon, accuracy=None) -> dict:
        """Attach/refresh the location of a PENDING alert, so the countdown can start the instant the
        button is held and the position (often slow to acquire) is added before it sends."""
        with self._lock:
            a = self._alerts.get(alert_id) if alert_id else self._latest_pending()
            if a is None or a["state"] != "pending":
                return {"ok": False, "state": "none", "summary": "No pending alert to update."}
            a["location_url"] = f"https://www.google.com/maps?q={float(lat):.5f},{float(lon):.5f}"
            a["accuracy"] = accuracy
            self._persist(a)
            return self._public(a)

    def send_now(self, alert_id: str | None = None) -> dict:
        a = self._begin_send(alert_id)
        if a is None:
            return {"ok": False, "state": "none", "summary": "There's no pending alert to send."}
        self._dispatch(a)
        return self.get(a["id"])

    def get(self, alert_id: str) -> dict | None:
        with self._lock:
            a = self._alerts.get(alert_id)
            return self._public(a) if a else None

    def latest(self) -> dict | None:
        with self._lock:
            return self._public(self._alerts[self._order[-1]]) if self._order else None

    # ── internals ─────────────────────────────────────────────────────────
    def _latest_pending(self):
        for aid in reversed(self._order):
            if self._alerts[aid]["state"] == "pending":
                return self._alerts[aid]
        return None

    def _recent_live_count(self) -> int:
        cutoff = self._clock() - 3600
        return sum(1 for a in self._alerts.values()
                   if not a["drill"] and a["created"] >= cutoff and a["state"] in _SENT_STATES)

    def _trim(self):
        while len(self._order) > MAX_KEPT:
            old = self._order.pop(0)
            if self._alerts.get(old, {}).get("state") != "pending":
                self._alerts.pop(old, None)

    def _begin_send(self, alert_id):
        with self._lock:
            a = self._alerts.get(alert_id) if alert_id else self._latest_pending()
            if a is None or a["state"] != "pending":
                return None
            t = a.pop("_timer", None)
            if t:
                t.cancel()
            a["state"] = "sending"
            self._persist(a)
            return a

    def _fire(self, alert_id: str):
        # The timer is the one path that can fire an alert the user has since cancelled elsewhere
        # (another gunicorn worker, or the pre-restart instance during a deploy overlap). Only a
        # POSITIVE non-pending read vetoes the send; if the store is down we send anyway - for an
        # emergency, "might have been cancelled" is the safer error than "silently didn't send".
        try:
            persisted = self._store.get_state(alert_id)
        except Exception:
            persisted = None
        if persisted and persisted != "pending":
            with self._lock:
                a = self._alerts.get(alert_id)
                if a and a["state"] == "pending":
                    a.pop("_timer", None)
                    a["state"] = persisted
                    a["summary"] = f"Already '{persisted}' (handled by another instance); not sending again."
            log.warning("Emergency alert %s not fired: persisted state is '%s'", alert_id, persisted)
            return
        a = self._begin_send(alert_id)
        if a:
            self._dispatch(a)

    def _dispatch(self, a: dict):
        contacts = self.contacts()
        msg = self.build_message(a)
        results, state = [], "sent"
        if a["drill"]:
            state, summary = "drill", f"Drill complete. NOTHING was sent. A real alert would text {len(contacts)} contact(s): {msg}"
        elif not contacts:
            state, summary = "not_configured", "No emergency contacts are configured, so NOBODY was notified. Call 911 or someone you trust now."
        else:
            for c in contacts:
                res, retried = {}, False
                for attempt in (1, 2):                     # one automatic retry: a transient Twilio blip shouldn't cost a contact
                    try:
                        res = self._send_sms(c["number"], msg) or {}
                    except Exception as e:
                        res = {"error": f"{type(e).__name__}: {e}"}
                    if res.get("ok") or attempt == 2:
                        break
                    retried = True
                    self._sleep(self._retry_delay)
                detail = _clean(res.get("error") or ("accepted by carrier network" + (" (after retry)" if retried else "")), 120)
                results.append({"name": c["name"], "number": c["number"], "kind": "sms", "ok": bool(res.get("ok")),
                                "detail": detail})
            if os.getenv("EMERGENCY_CALL_FIRST", "").lower() in ("1", "true", "yes"):
                spoken = (f"This is an automated emergency alert from {_clean(os.getenv('EMERGENCY_USER_NAME', ''), 40) or 'your contact'}'s "
                          f"assistant. {a['reason'] or 'No details given'}. A text with their location was also sent. "
                          f"Please try to reach them now.")
                try:
                    res = self._send_call(contacts[0]["number"], spoken) or {}
                except Exception as e:
                    res = {"error": f"{type(e).__name__}: {e}"}
                results.append({"name": contacts[0]["name"], "number": contacts[0]["number"], "kind": "call",
                                "ok": bool(res.get("ok")), "detail": _clean(res.get("error") or "call placed", 120)})
            ok = [r for r in results if r["kind"] == "sms" and r["ok"]]
            bad = [r for r in results if r["kind"] == "sms" and not r["ok"]]
            if len(ok) == len(contacts):
                state = "sent"
                summary = (f"Alert texts were accepted by the carrier for {len(ok)} of {len(contacts)} contact(s) "
                           f"({', '.join(r['name'] for r in ok)}). I can't confirm anyone has read them.")
            elif ok:
                state = "partial"
                summary = (f"Only {len(ok)} of {len(contacts)} texts went out ({', '.join(r['name'] for r in ok)}). "
                           f"FAILED: {', '.join(r['name'] + ' (' + r['detail'] + ')' for r in bad)}. Try them directly.")
            else:
                state = "failed"
                summary = f"I could NOT text any emergency contact ({bad[0]['detail']}). Call 911 or someone directly now."
        with self._lock:
            a["results"], a["state"], a["summary"] = results, state, summary
            self._persist(a)
        if not a["drill"]:
            self._notify("FRIDAY emergency alert", summary)
        log.warning("Emergency alert %s finished: %s", a["id"], state)

    # ── durability ────────────────────────────────────────────────────────
    @staticmethod
    def _snapshot(a: dict) -> dict:
        return {k: v for k, v in a.items() if k != "_timer"}

    def _persist(self, a: dict) -> None:
        """Best-effort and OFF the alert path: serialised on one background thread, writing the latest
        snapshot at execution time (so out-of-order writes can't resurrect an old state)."""
        aid = a["id"]

        def _write():
            try:
                with self._lock:
                    live = self._alerts.get(aid)
                    rec = self._snapshot(live) if live else None
                if rec:
                    self._store.save(rec)
            except Exception:
                log.warning("Emergency persist failed for %s", aid, exc_info=True)

        if self._executor:
            self._executor.submit(_write)
        else:
            _write()

    def recover(self) -> list[dict]:
        """Call once at boot. Rebuilds alerts from the store so a restart mid-countdown can't make an
        alert vanish:
          pending, not yet due    -> re-armed
          pending, overdue        -> sent after RECOVERY_MARGIN (unless an older instance already did),
                                     or reported EXPIRED if staler than RECOVERY_GRACE (never sent late)
          sending at crash time   -> 'interrupted': contacts MAY have been texted, the user is told
          finished                -> adopted (keeps the hourly rate limit honest)"""
        try:
            rows = self._store.load_all()
        except Exception:
            log.warning("Emergency recovery: store unavailable", exc_info=True)
            return []
        now, actions = self._clock(), []
        for rec in rows:
            try:
                aid = rec["id"]
                with self._lock:
                    if aid in self._alerts:
                        continue
                    a = {**rec, "results": rec.get("results") or [], "summary": rec.get("summary") or ""}
                    self._alerts[aid] = a
                    self._order.append(aid)
                    state = a["state"]
                    if state not in ("pending", "sending"):
                        actions.append({"id": aid, "action": "adopted"})
                        continue
                    if state == "sending":
                        a["state"] = "interrupted"
                        a["summary"] = ("The server restarted while this alert was being sent. Some contacts MAY have been "
                                        "texted and some may not. Contact them directly, and call 911 if it may be life-threatening.")
                        self._persist(a)
                        notify = not a["drill"]
                        actions.append({"id": aid, "action": "interrupted"})
                    else:
                        overdue = now - a["deadline"]
                        notify = False
                        if a["drill"] and overdue >= 0:
                            a["state"], a["summary"] = "drill", "Drill complete. NOTHING was sent."
                            self._persist(a)
                            actions.append({"id": aid, "action": "drill_closed"})
                        elif overdue > RECOVERY_GRACE:
                            a["state"] = "expired"
                            a["summary"] = (f"An SOS from {int(overdue // 60)} min ago was interrupted by a server restart and was "
                                            f"NOT sent. If you still need help, call 911 or your contacts now.")
                            self._persist(a)
                            notify = not a["drill"]
                            actions.append({"id": aid, "action": "expired"})
                        else:
                            delay = max(0.0, a["deadline"] + RECOVERY_MARGIN - now)
                            timer = self._timer_factory(delay, self._fire, args=(aid,))
                            timer.daemon = True
                            a["_timer"] = timer
                            timer.start()
                            actions.append({"id": aid, "action": "rearmed", "delay": round(delay, 1)})
                if notify:
                    self._notify("FRIDAY emergency alert", a["summary"])
            except Exception:
                log.warning("Emergency recovery skipped a bad record", exc_info=True)
        if actions:
            log.warning("Emergency recovery: %s", actions)
        return actions

    def _public(self, a: dict) -> dict:
        left = max(0, int(round(a["deadline"] - self._clock()))) if a["state"] == "pending" else 0
        return {"ok": True, "id": a["id"], "state": a["state"], "drill": a["drill"], "seconds_left": left,
                "reason": a["reason"], "location_url": a["location_url"], "summary": a["summary"],
                "results": [{"name": r["name"], "number": mask(r["number"]), "kind": r["kind"], "ok": r["ok"],
                             "detail": r["detail"]} for r in a["results"]],
                "call_911": CALL_911, "note": CALL_911_NOTE}


emergency = EmergencyManager()
