"""services/friday_apple_calendar.py — Apple (iCloud) Calendar over CalDAV.

The boss uses Apple Calendar, not Google. iCloud exposes calendars over
CalDAV at caldav.icloud.com, authenticated with an Apple ID plus an
**app-specific password** (appleid.apple.com -> Sign-In & Security ->
App-Specific Passwords) -- the same kind of credential services/
friday_gmail.py already uses for IMAP, not a full OAuth browser flow. So
there is no /auth redirect + callback here: config is entirely env-var
based, and "connected" just means the credential is present.

Crucially this runs over HTTPS (port 443), unlike the SMTP saga in
services/friday_gmail.py's docstring: Render's outbound network blocks
raw mail ports but not 443, so CalDAV doesn't hit the failure that forced
email onto the Gmail API.

This is a hand-rolled CalDAV client (raw httpx + hand-built/parsed
iCalendar), not the `caldav`/`icalendar` libraries -- neither ships in
requirements.txt, and this is the same "avoid a heavy dependency for what
is ultimately a few authenticated HTTPS requests" tradeoff core/tools/
web.py already makes with its regex HTML stripping. The wire-format
helpers (_build_vevent, _parse_vevents, _parse_multistatus, the discovery
extractors) are pure and unit-tested; the network methods just compose
them.

Interface matches services/friday_calendar.py (FridayCalendar) exactly --
is_configured / is_connected / get_today / get_upcoming / create_event /
event_exists -- so it's a drop-in backend, selected in
services/friday_calendar.py.

Setup:
  1. appleid.apple.com -> App-Specific Passwords -> generate one for FRIDAY.
  2. Set env vars: APPLE_ID (your Apple ID email), APPLE_APP_PASSWORD
     (the generated password, form "abcd-efgh-ijkl-mnop"), and optionally
     APPLE_CALENDAR_NAME to target a specific calendar by name (default:
     the first calendar that accepts events).
"""
import os
import re
import time
import uuid
import html
import httpx
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta, timezone

from db import turso_http_client as turso

APPLE_ID = os.getenv("APPLE_ID", "").strip()
APPLE_APP_PASSWORD = os.getenv("APPLE_APP_PASSWORD", "").strip()
# Optional: pick a calendar by display name. Empty -> first usable one.
APPLE_CALENDAR_NAME = os.getenv("APPLE_CALENDAR_NAME", "").strip()

CALDAV_ROOT = "https://caldav.icloud.com"
# Discovery (principal -> calendar-home -> calendar URL) is stable for an
# account, so it's cached in Turso rather than re-walked on every call.
DISCOVERY_TABLE = "apple_calendar_discovery"
DISCOVERY_KEY = "urls"

_UA = "FRIDAY/2.0 (CalDAV)"
_TIMEOUT = 10

# CalDAV / WebDAV / iCalendar XML namespaces.
_NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}


# ── pure iCalendar + CalDAV-XML helpers (unit-tested, no network) ──────────

def _ical_escape(text: str) -> str:
    """Escape a value for an iCalendar text field per RFC 5545 §3.3.11:
    backslash, semicolon, comma, and newline all have meaning."""
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _is_date_only(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", (value or "").strip()))


def _ical_time(iso: str) -> tuple[str, str]:
    """Return (param, value) for a DTSTART/DTEND line from an ISO string.

    All-day (bare YYYY-MM-DD) -> (";VALUE=DATE", "20260901").
    Timed with an explicit offset/Z -> UTC, ("", "20260901T150000Z").
    Timed but naive (no tz, e.g. "2026-09-01T15:00:00", which is what
    _cmd_calendar_add produces for "3pm") -> floating local time,
    ("", "20260901T150000") -- iCloud shows it at that wall-clock time in
    the calendar's own zone, which is what "3pm" was meant to say.
    """
    v = (iso or "").strip()
    if _is_date_only(v):
        return ";VALUE=DATE", v.replace("-", "")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        # Fall back to a best-effort strip so a slightly-off string still
        # produces *something* rather than raising into the caller.
        return "", re.sub(r"[-:]", "", v).split(".")[0]
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
        return "", dt.strftime("%Y%m%dT%H%M%SZ")
    return "", dt.strftime("%Y%m%dT%H%M%S")


def _exclusive_end(end_iso: str) -> str:
    """All-day DTEND is exclusive in iCalendar just like Google's model:
    a single all-day event on the 1st needs DTEND of the 2nd. Callers pass
    the inclusive last day (how people say dates); this shifts it."""
    last_day = datetime.strptime(end_iso.strip(), "%Y-%m-%d").date()
    return (last_day + timedelta(days=1)).isoformat()


def _build_vevent(uid: str, title: str, start_iso: str, end_iso: str,
                  description: str = "") -> str:
    """Build a complete VCALENDAR wrapping one VEVENT, ready to PUT."""
    start_param, start_val = _ical_time(start_iso)
    if _is_date_only(start_iso) and _is_date_only(end_iso):
        end_param, end_val = _ical_time(_exclusive_end(end_iso))
    else:
        end_param, end_val = _ical_time(end_iso)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//FRIDAY//Apple Calendar//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART{start_param}:{start_val}",
        f"DTEND{end_param}:{end_val}",
        f"SUMMARY:{_ical_escape(title)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_ical_escape(description)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    # RFC 5545 requires CRLF line endings.
    return "\r\n".join(lines) + "\r\n"


def _unfold_ical(text: str) -> list[str]:
    """iCalendar folds long lines by starting continuations with a space
    or tab. Rejoin them before parsing property names."""
    out: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _ical_unescape(text: str) -> str:
    return (
        (text or "")
        .replace("\\n", "\n").replace("\\N", "\n")
        .replace("\\,", ",").replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _parse_vevents(ics_text: str) -> list[dict]:
    """Pull the fields FRIDAY surfaces out of every VEVENT in an ics blob:
    id (UID), title (SUMMARY), start (DTSTART, normalized back to ISO-ish),
    location, attendees. Property lines can carry params after a ';' before
    the ':', e.g. DTSTART;VALUE=DATE:20260901 -- split on the first ':'
    and read the name before any ';'."""
    events: list[dict] = []
    current: dict | None = None
    for line in _unfold_ical(ics_text):
        if line == "BEGIN:VEVENT":
            current = {"id": "", "title": "(no title)", "start": "",
                       "location": "", "attendees": []}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        name_part, value = line.split(":", 1)
        name = name_part.split(";", 1)[0].upper()
        if name == "UID":
            current["id"] = value
        elif name == "SUMMARY":
            current["title"] = _ical_unescape(value) or "(no title)"
        elif name == "DTSTART":
            current["start"] = _ical_to_iso(value)
        elif name == "LOCATION":
            current["location"] = _ical_unescape(value)
        elif name == "ATTENDEE":
            current["attendees"].append(value)
    return events


def _ical_to_iso(value: str) -> str:
    """Normalize an iCalendar DTSTART value back toward ISO for display.
    20260901 -> 2026-09-01; 20260901T150000Z -> 2026-09-01T15:00:00Z.
    Anything unexpected is returned as-is rather than dropped."""
    v = (value or "").strip()
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", v)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)", v)
    if m:
        y, mo, d, h, mi, s, z = m.groups()
        return f"{y}-{mo}-{d}T{h}:{mi}:{s}{z}"
    return v


def _parse_multistatus(xml_text: str) -> list[tuple[str, str]]:
    """Parse a CalDAV 207 Multistatus into [(href, calendar_data)] pairs,
    keeping only responses that actually carried calendar-data (a REPORT
    can include the collection itself with none)."""
    out: list[tuple[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for resp in root.findall("d:response", _NS):
        href_el = resp.find("d:href", _NS)
        href = href_el.text if href_el is not None else ""
        data_el = resp.find(".//c:calendar-data", _NS)
        if data_el is not None and (data_el.text or "").strip():
            out.append((href or "", html.unescape(data_el.text)))
    return out


def _extract_href(xml_text: str, *path: str) -> str:
    """Return the first <d:href> under the given element path in a
    Multistatus prop response (e.g. current-user-principal,
    calendar-home-set). Empty string if absent/unparseable."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    for resp in root.findall("d:response", _NS):
        el = resp
        ok = True
        for step in path:
            el = el.find(step, _NS) if el is not None else None
            if el is None:
                ok = False
                break
        if ok and el is not None:
            href = el.find("d:href", _NS)
            if href is not None and href.text:
                return href.text.strip()
    return ""


def _pick_calendar(xml_text: str, preferred_name: str = "") -> str:
    """From a Depth-1 listing of the calendar-home, pick the href of a
    collection that supports VEVENT. Prefers one whose displayname matches
    preferred_name (case-insensitive); otherwise the first VEVENT-capable
    calendar. Skips non-calendar collections (inbox/outbox/notifications)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    fallback = ""
    for resp in root.findall("d:response", _NS):
        href_el = resp.find("d:href", _NS)
        if href_el is None or not href_el.text:
            continue
        href = href_el.text.strip()
        # Must be a calendar collection.
        rtype = resp.find(".//d:resourcetype", _NS)
        is_cal = rtype is not None and rtype.find("c:calendar", _NS) is not None
        if not is_cal:
            continue
        # Must support VEVENT (some iCloud calendars are VTODO-only).
        comps = resp.findall(".//c:supported-calendar-component-set/c:comp", _NS)
        if comps and not any(c.get("name") == "VEVENT" for c in comps):
            continue
        name_el = resp.find(".//d:displayname", _NS)
        name = (name_el.text or "").strip() if name_el is not None else ""
        if preferred_name and name.lower() == preferred_name.lower():
            return href
        if not fallback:
            fallback = href
    return fallback


# ── the backend ───────────────────────────────────────────────────────────

class FridayAppleCalendar:

    def is_configured(self) -> bool:
        return bool(APPLE_ID and APPLE_APP_PASSWORD)

    def is_connected(self) -> bool:
        """Unlike the Google backend there's no separate consent step:
        an app-specific password either works or it doesn't, and a bad one
        surfaces as an error on the actual call (same as Gmail IMAP). So
        "connected" is just "credential present" -- matching how the rest
        of the app reads is_connected() as the go/no-go gate."""
        return self.is_configured()

    def _client(self) -> httpx.Client:
        return httpx.Client(
            auth=(APPLE_ID, APPLE_APP_PASSWORD),
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT,
            follow_redirects=True,  # iCloud redirects to a partition host
        )

    def _propfind(self, client: httpx.Client, url: str, body: str, depth: str = "0"):
        return client.request(
            "PROPFIND", url,
            content=body.encode("utf-8"),
            headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
        )

    # -- discovery (cached) --

    def _cached_discovery(self) -> dict:
        if turso.is_configured():
            try:
                turso.ensure_kv_table(DISCOVERY_TABLE)
                row = turso.kv_get(DISCOVERY_TABLE, DISCOVERY_KEY)
                if row and row.get("calendar_url"):
                    return row
            except Exception as e:
                print(f"[Apple Calendar] discovery cache read failed: {e}")
        return {}

    def _save_discovery(self, data: dict):
        if turso.is_configured():
            try:
                turso.ensure_kv_table(DISCOVERY_TABLE)
                turso.kv_set(DISCOVERY_TABLE, DISCOVERY_KEY, data)
            except Exception as e:
                print(f"[Apple Calendar] discovery cache write failed: {e}")

    def _resolve(self, href: str, base: httpx.URL) -> str:
        """A CalDAV href is usually an absolute path on the (possibly
        redirected) partition host; join it against the response's own URL
        so the partition host is preserved."""
        return str(base.join(href))

    def _discover_calendar_url(self, force: bool = False) -> str:
        if not force:
            cached = self._cached_discovery()
            if cached.get("calendar_url"):
                return cached["calendar_url"]
        if not self.is_configured():
            return ""
        try:
            with self._client() as client:
                # 1. principal
                r = self._propfind(
                    client, CALDAV_ROOT + "/",
                    '<d:propfind xmlns:d="DAV:"><d:prop>'
                    '<d:current-user-principal/></d:prop></d:propfind>',
                )
                if r.status_code not in (207, 200):
                    print(f"[Apple Calendar] principal PROPFIND -> {r.status_code}")
                    return ""
                principal_href = _extract_href(r.text, "d:propstat", "d:prop",
                                               "d:current-user-principal")
                if not principal_href:
                    return ""
                principal_url = self._resolve(principal_href, r.url)

                # 2. calendar-home-set
                r = self._propfind(
                    client, principal_url,
                    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    '<d:prop><c:calendar-home-set/></d:prop></d:propfind>',
                )
                home_href = _extract_href(r.text, "d:propstat", "d:prop",
                                          "c:calendar-home-set")
                if not home_href:
                    return ""
                home_url = self._resolve(home_href, r.url)

                # 3. list calendars, pick one
                r = self._propfind(
                    client, home_url,
                    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    '<d:prop><d:resourcetype/><d:displayname/>'
                    '<c:supported-calendar-component-set/></d:prop></d:propfind>',
                    depth="1",
                )
                cal_href = _pick_calendar(r.text, APPLE_CALENDAR_NAME)
                if not cal_href:
                    print("[Apple Calendar] no VEVENT-capable calendar found")
                    return ""
                calendar_url = self._resolve(cal_href, r.url)

            self._save_discovery({
                "principal_url": principal_url,
                "home_url": home_url,
                "calendar_url": calendar_url,
            })
            return calendar_url
        except Exception as e:
            print(f"[Apple Calendar] discovery failed: {e}")
            return ""

    # -- reads --

    def _events_between(self, start: datetime, end: datetime) -> list:
        calendar_url = self._discover_calendar_url()
        if not calendar_url:
            return []
        body = (
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:prop><d:getetag/><c:calendar-data/></d:prop>'
            '<c:filter><c:comp-filter name="VCALENDAR">'
            '<c:comp-filter name="VEVENT">'
            f'<c:time-range start="{start.strftime("%Y%m%dT%H%M%SZ")}" '
            f'end="{end.strftime("%Y%m%dT%H%M%SZ")}"/>'
            '</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'
        )
        try:
            with self._client() as client:
                r = client.request(
                    "REPORT", calendar_url,
                    content=body.encode("utf-8"),
                    headers={"Depth": "1",
                             "Content-Type": "application/xml; charset=utf-8"},
                )
            if r.status_code not in (207, 200):
                print(f"[Apple Calendar] calendar-query -> {r.status_code}")
                return []
            events = []
            for href, ics in _parse_multistatus(r.text):
                for ev in _parse_vevents(ics):
                    # Prefer the resource href as the stable id (that's
                    # what event_exists reads back), fall back to the UID.
                    ev["id"] = href or ev.get("id", "")
                    events.append(ev)
            events.sort(key=lambda e: e.get("start", ""))
            return events
        except Exception as e:
            print(f"[Apple Calendar] {e}")
            return []

    def get_today(self) -> list:
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self._events_between(start, start + timedelta(days=1))

    def get_upcoming(self, hours: int = 24) -> list:
        now = datetime.now(timezone.utc)
        return self._events_between(now, now + timedelta(hours=hours))

    # -- writes --

    def create_event(self, title: str, start_iso: str, end_iso: str,
                     description: str = "") -> dict:
        calendar_url = self._discover_calendar_url()
        if not calendar_url:
            return {"error": "Calendar not connected"}
        uid = f"friday-{uuid.uuid4()}"
        event_url = calendar_url.rstrip("/") + f"/{uid}.ics"
        ics = _build_vevent(uid, title, start_iso, end_iso, description)
        try:
            with self._client() as client:
                r = client.put(
                    event_url,
                    content=ics.encode("utf-8"),
                    headers={"Content-Type": "text/calendar; charset=utf-8",
                             # Don't clobber an existing resource at this URL.
                             "If-None-Match": "*"},
                )
            if r.status_code in (200, 201, 204):
                # event_id is the resource URL -- event_exists reads it back.
                return {"ok": True, "event": event_url, "event_id": event_url}
            return {"error": f"Failed to create event: {r.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def event_exists(self, event_id: str) -> dict:
        """Same three-state contract as FridayCalendar.event_exists /
        FridayGmail.message_exists, so core/outcome_verify.py can confirm
        a create actually landed. event_id here is the event's resource
        URL returned by create_event()."""
        if not event_id:
            return {"state": "unknown", "detail": "no event id was returned"}
        if not self.is_configured():
            return {"state": "unknown", "detail": "calendar not connected"}
        try:
            with self._client() as client:
                r = client.get(event_id)
        except Exception as e:
            return {"state": "unknown", "detail": f"couldn't reach iCloud: {e}"}
        if r.status_code == 404:
            return {"state": "contradicted", "detail": "no such event on the calendar"}
        if r.status_code not in (200, 207):
            return {"state": "unknown", "detail": f"iCloud returned {r.status_code}"}
        return {"state": "confirmed", "detail": event_id}

    # -- OAuth-shaped stubs --
    # Apple config is env-var based; there is no browser auth flow. These
    # exist only so nothing crashes if the OAuth route reaches this backend
    # (the route in routes/spotify_calendar.py targets the Google instance
    # explicitly, so these are defensive, not the intended path).

    def auth_url(self) -> str:
        return ""

    def exchange_code(self, code: str) -> dict:
        return {"error": "Apple Calendar uses an app-specific password, not a browser sign-in."}


friday_apple_calendar = FridayAppleCalendar()
