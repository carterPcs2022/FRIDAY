"""tests/test_apple_calendar.py — services/friday_apple_calendar.py.

Two layers:

1. The pure iCalendar / CalDAV-XML helpers (build a VEVENT, parse VEVENTs
   back, parse a Multistatus, walk discovery XML, pick a calendar). These
   are the fiddly wire-format bits, and since this deploy can't reach real
   iCloud from CI, they're where correctness is actually pinned down.

2. The backend's own contract (is_configured/is_connected, and that the
   network methods compose the helpers and stay defensive) -- exercised
   against mocked httpx responses, the same way test_friday_spotify.py and
   the calendar-token tests mock their HTTP.
"""
import re
from unittest import mock

import pytest

import services.friday_apple_calendar as apple_mod
from services.friday_apple_calendar import (
    FridayAppleCalendar,
    _ical_escape, _ical_time, _exclusive_end, _build_vevent,
    _unfold_ical, _parse_vevents, _parse_multistatus,
    _extract_href, _pick_calendar, _ical_to_iso,
)


# ── pure helpers ───────────────────────────────────────────────────────────

class TestIcalEscape:
    def test_special_chars_are_escaped(self):
        assert _ical_escape("Lunch; with, Jane\\") == "Lunch\\; with\\, Jane\\\\"

    def test_newlines_become_literal_backslash_n(self):
        assert _ical_escape("line1\nline2") == "line1\\nline2"


class TestIcalTime:
    def test_all_day_uses_value_date(self):
        param, val = _ical_time("2026-09-01")
        assert param == ";VALUE=DATE"
        assert val == "20260901"

    def test_naive_datetime_stays_floating_local(self):
        param, val = _ical_time("2026-09-01T15:00:00")
        assert param == ""
        assert val == "20260901T150000"

    def test_tz_aware_datetime_is_converted_to_utc_z(self):
        # 15:00 at +02:00 is 13:00 UTC.
        param, val = _ical_time("2026-09-01T15:00:00+02:00")
        assert param == ""
        assert val == "20260901T130000Z"


class TestExclusiveEnd:
    def test_single_all_day_end_is_shifted_forward_one_day(self):
        assert _exclusive_end("2026-09-01") == "2026-09-02"


class TestBuildVevent:
    def test_a_timed_event_round_trips_through_the_parser(self):
        ics = _build_vevent("uid-1", "Dentist", "2026-09-01T15:00:00",
                            "2026-09-01T15:30:00", description="bring x-rays")
        assert ics.endswith("\r\n")
        assert "BEGIN:VEVENT" in ics and "END:VEVENT" in ics
        events = _parse_vevents(ics)
        assert len(events) == 1
        ev = events[0]
        assert ev["id"] == "uid-1"
        assert ev["title"] == "Dentist"
        assert ev["start"] == "2026-09-01T15:00:00"

    def test_an_all_day_event_gets_an_exclusive_end(self):
        ics = _build_vevent("uid-2", "Trip", "2026-09-01", "2026-09-01")
        # DTEND must be the 2nd (exclusive), not the 1st.
        assert re.search(r"DTEND;VALUE=DATE:20260902", ics)
        assert re.search(r"DTSTART;VALUE=DATE:20260901", ics)

    def test_title_with_delimiters_is_escaped_in_output(self):
        ics = _build_vevent("uid-3", "Meet, greet; go", "2026-09-01", "2026-09-01")
        assert "SUMMARY:Meet\\, greet\\; go" in ics
        # And it un-escapes cleanly on the way back.
        assert _parse_vevents(ics)[0]["title"] == "Meet, greet; go"


class TestUnfoldAndParse:
    def test_folded_lines_are_rejoined_before_parsing(self):
        ics = (
            "BEGIN:VEVENT\r\n"
            "UID:abc\r\n"
            "SUMMARY:A very long title that got\r\n"
            "  folded across two lines\r\n"
            "DTSTART:20260901T150000Z\r\n"
            "END:VEVENT\r\n"
        )
        ev = _parse_vevents(ics)[0]
        assert ev["title"] == "A very long title that got folded across two lines"
        assert ev["start"] == "2026-09-01T15:00:00Z"

    def test_property_params_before_the_colon_are_ignored_for_the_name(self):
        ics = (
            "BEGIN:VEVENT\r\nUID:x\r\n"
            "DTSTART;TZID=America/New_York:20260901T150000\r\n"
            "END:VEVENT\r\n"
        )
        assert _parse_vevents(ics)[0]["start"] == "2026-09-01T15:00:00"

    def test_location_and_attendees_are_captured(self):
        ics = (
            "BEGIN:VEVENT\r\nUID:x\r\nSUMMARY:S\r\n"
            "LOCATION:Room 4\r\n"
            "ATTENDEE:mailto:a@x.com\r\n"
            "ATTENDEE:mailto:b@x.com\r\n"
            "END:VEVENT\r\n"
        )
        ev = _parse_vevents(ics)[0]
        assert ev["location"] == "Room 4"
        assert ev["attendees"] == ["mailto:a@x.com", "mailto:b@x.com"]

    def test_multiple_vevents_are_all_returned(self):
        ics = (
            "BEGIN:VEVENT\r\nUID:1\r\nSUMMARY:One\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:2\r\nSUMMARY:Two\r\nEND:VEVENT\r\n"
        )
        titles = [e["title"] for e in _parse_vevents(ics)]
        assert titles == ["One", "Two"]

    def test_garbage_input_yields_no_events_rather_than_raising(self):
        assert _parse_vevents("not ical at all") == []
        assert _parse_vevents("") == []


class TestIcalToIso:
    def test_date_only(self):
        assert _ical_to_iso("20260901") == "2026-09-01"

    def test_utc_datetime(self):
        assert _ical_to_iso("20260901T150000Z") == "2026-09-01T15:00:00Z"

    def test_unrecognised_is_passed_through(self):
        assert _ical_to_iso("weird") == "weird"


class TestParseMultistatus:
    XML = """<?xml version="1.0"?>
    <d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
      <d:response>
        <d:href>/cal/1.ics</d:href>
        <d:propstat><d:prop>
          <c:calendar-data>BEGIN:VEVENT
UID:1
SUMMARY:Hi
END:VEVENT</c:calendar-data>
        </d:prop></d:propstat>
      </d:response>
      <d:response>
        <d:href>/cal/</d:href>
        <d:propstat><d:prop><d:getetag>"x"</d:getetag></d:prop></d:propstat>
      </d:response>
    </d:multistatus>"""

    def test_only_responses_with_calendar_data_are_returned(self):
        pairs = _parse_multistatus(self.XML)
        assert len(pairs) == 1
        href, data = pairs[0]
        assert href == "/cal/1.ics"
        assert "SUMMARY:Hi" in data

    def test_malformed_xml_returns_empty(self):
        assert _parse_multistatus("<not xml") == []


class TestExtractHref:
    def test_current_user_principal_is_walked_out(self):
        xml = """<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:">
          <d:response><d:propstat><d:prop>
            <d:current-user-principal><d:href>/123/principal/</d:href></d:current-user-principal>
          </d:prop></d:propstat></d:response>
        </d:multistatus>"""
        assert _extract_href(xml, "d:propstat", "d:prop",
                             "d:current-user-principal") == "/123/principal/"

    def test_missing_path_returns_empty(self):
        xml = '<d:multistatus xmlns:d="DAV:"></d:multistatus>'
        assert _extract_href(xml, "d:propstat", "d:prop", "d:current-user-principal") == ""


class TestPickCalendar:
    HOME = """<?xml version="1.0"?>
    <d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
      <d:response>
        <d:href>/123/calendars/inbox/</d:href>
        <d:propstat><d:prop>
          <d:resourcetype><c:schedule-inbox/></d:resourcetype>
          <d:displayname>Inbox</d:displayname>
        </d:prop></d:propstat>
      </d:response>
      <d:response>
        <d:href>/123/calendars/work/</d:href>
        <d:propstat><d:prop>
          <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
          <d:displayname>Work</d:displayname>
          <c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>
        </d:prop></d:propstat>
      </d:response>
      <d:response>
        <d:href>/123/calendars/reminders/</d:href>
        <d:propstat><d:prop>
          <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
          <d:displayname>Reminders</d:displayname>
          <c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set>
        </d:prop></d:propstat>
      </d:response>
      <d:response>
        <d:href>/123/calendars/home/</d:href>
        <d:propstat><d:prop>
          <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
          <d:displayname>Home</d:displayname>
          <c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>
        </d:prop></d:propstat>
      </d:response>
    </d:multistatus>"""

    def test_first_vevent_calendar_is_picked_when_no_preference(self):
        # Inbox skipped (not a calendar), Reminders skipped (VTODO only),
        # so Work is the first usable one.
        assert _pick_calendar(self.HOME) == "/123/calendars/work/"

    def test_a_named_preference_wins(self):
        assert _pick_calendar(self.HOME, "Home") == "/123/calendars/home/"

    def test_a_vtodo_only_calendar_is_never_picked(self):
        assert _pick_calendar(self.HOME, "Reminders") == "/123/calendars/work/"


# ── backend contract ───────────────────────────────────────────────────────

@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(apple_mod, "APPLE_ID", "boss@icloud.com")
    monkeypatch.setattr(apple_mod, "APPLE_APP_PASSWORD", "abcd-efgh-ijkl-mnop")
    monkeypatch.setattr(apple_mod, "APPLE_CALENDAR_NAME", "")
    # No Turso in these tests -> discovery is not cached, always walked.
    monkeypatch.setattr(apple_mod.turso, "is_configured", lambda: False)
    return FridayAppleCalendar()


class TestConfigGate:
    def test_not_configured_without_credentials(self, monkeypatch):
        monkeypatch.setattr(apple_mod, "APPLE_ID", "")
        monkeypatch.setattr(apple_mod, "APPLE_APP_PASSWORD", "")
        cal = FridayAppleCalendar()
        assert cal.is_configured() is False
        assert cal.is_connected() is False

    def test_configured_and_connected_with_credentials(self, configured):
        assert configured.is_configured() is True
        # No separate consent step -- credential present == connected.
        assert configured.is_connected() is True


class TestCreateEvent:
    def test_a_successful_put_returns_the_resource_url_as_event_id(self, configured, monkeypatch):
        monkeypatch.setattr(configured, "_discover_calendar_url",
                            lambda force=False: "https://p1-caldav.icloud.com/1/calendars/home/")
        put_resp = mock.Mock(status_code=201)

        fake_client = mock.MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.put.return_value = put_resp
        monkeypatch.setattr(configured, "_client", lambda: fake_client)

        result = configured.create_event("Dentist", "2026-09-01T15:00:00", "2026-09-01T15:30:00")

        assert result["ok"] is True
        assert result["event_id"].endswith(".ics")
        assert result["event_id"].startswith("https://p1-caldav.icloud.com/1/calendars/home/")
        # The PUT body must be a real VEVENT for the requested event.
        body = fake_client.put.call_args.kwargs["content"].decode()
        assert "SUMMARY:Dentist" in body

    def test_a_rejected_put_reports_the_status_and_does_not_claim_success(self, configured, monkeypatch):
        monkeypatch.setattr(configured, "_discover_calendar_url",
                            lambda force=False: "https://x/cal/")
        fake_client = mock.MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.put.return_value = mock.Mock(status_code=507)
        monkeypatch.setattr(configured, "_client", lambda: fake_client)

        result = configured.create_event("X", "2026-09-01", "2026-09-01")
        assert "ok" not in result
        assert "507" in result["error"]

    def test_no_calendar_discovered_is_an_honest_not_connected(self, configured, monkeypatch):
        monkeypatch.setattr(configured, "_discover_calendar_url", lambda force=False: "")
        result = configured.create_event("X", "2026-09-01", "2026-09-01")
        assert result == {"error": "Calendar not connected"}


class TestGetEvents:
    def test_events_are_parsed_out_of_a_report_response(self, configured, monkeypatch):
        monkeypatch.setattr(configured, "_discover_calendar_url",
                            lambda force=False: "https://x/cal/")
        report_xml = """<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
          <d:response><d:href>/cal/evt.ics</d:href><d:propstat><d:prop>
            <c:calendar-data>BEGIN:VEVENT
UID:u1
SUMMARY:Standup
DTSTART:20260901T090000Z
END:VEVENT</c:calendar-data>
          </d:prop></d:propstat></d:response>
        </d:multistatus>"""
        fake_client = mock.MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.request.return_value = mock.Mock(status_code=207, text=report_xml)
        monkeypatch.setattr(configured, "_client", lambda: fake_client)

        events = configured.get_today()
        assert len(events) == 1
        assert events[0]["title"] == "Standup"
        # id is the resource href (what event_exists reads back), not the UID.
        assert events[0]["id"] == "/cal/evt.ics"

    def test_a_non_207_report_yields_no_events_rather_than_raising(self, configured, monkeypatch):
        monkeypatch.setattr(configured, "_discover_calendar_url",
                            lambda force=False: "https://x/cal/")
        fake_client = mock.MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.request.return_value = mock.Mock(status_code=500, text="boom")
        monkeypatch.setattr(configured, "_client", lambda: fake_client)

        assert configured.get_today() == []


class TestEventExists:
    def test_present_event_is_confirmed(self, configured, monkeypatch):
        fake_client = mock.MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.get.return_value = mock.Mock(status_code=200)
        monkeypatch.setattr(configured, "_client", lambda: fake_client)
        assert configured.event_exists("https://x/cal/e.ics")["state"] == "confirmed"

    def test_a_404_is_contradicted(self, configured, monkeypatch):
        fake_client = mock.MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.get.return_value = mock.Mock(status_code=404)
        monkeypatch.setattr(configured, "_client", lambda: fake_client)
        assert configured.event_exists("https://x/cal/e.ics")["state"] == "contradicted"

    def test_no_id_is_unknown_not_a_crash(self, configured):
        assert configured.event_exists("")["state"] == "unknown"


class TestBackendSelection:
    def test_auto_prefers_apple_when_apple_is_configured(self, monkeypatch):
        import services.friday_calendar as cal_mod
        monkeypatch.setenv("FRIDAY_CALENDAR_BACKEND", "auto")
        monkeypatch.setattr(apple_mod, "APPLE_ID", "boss@icloud.com")
        monkeypatch.setattr(apple_mod, "APPLE_APP_PASSWORD", "pw")
        backend = cal_mod._select_backend()
        assert backend is apple_mod.friday_apple_calendar

    def test_google_is_forced_when_asked(self, monkeypatch):
        import services.friday_calendar as cal_mod
        monkeypatch.setenv("FRIDAY_CALENDAR_BACKEND", "google")
        monkeypatch.setattr(apple_mod, "APPLE_ID", "boss@icloud.com")
        monkeypatch.setattr(apple_mod, "APPLE_APP_PASSWORD", "pw")
        assert cal_mod._select_backend() is cal_mod.friday_google_calendar

    def test_auto_falls_back_to_google_when_apple_unconfigured(self, monkeypatch):
        import services.friday_calendar as cal_mod
        monkeypatch.setenv("FRIDAY_CALENDAR_BACKEND", "auto")
        monkeypatch.setattr(apple_mod, "APPLE_ID", "")
        monkeypatch.setattr(apple_mod, "APPLE_APP_PASSWORD", "")
        assert cal_mod._select_backend() is cal_mod.friday_google_calendar
