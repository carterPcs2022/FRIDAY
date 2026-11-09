"""Emergency alert system: the one component where a bug can hurt someone, and until now
the only one with ZERO tests. Covers the countdown/cancel/send lifecycle, false-alarm
safeguards, honest result reporting, restart recovery, cancel-veto across instances,
the Turso store (against a real SQL engine), the HTTP routes, and the glasses page."""
import json
import re
import sqlite3
from unittest import mock

import pytest

from services import friday_emergency as fe
from services.friday_emergency import EmergencyManager, TursoStore, parse_contacts

CONTACTS = [{"name": "Mom", "number": "+15551230001"}, {"name": "Sam", "number": "+15551230002"}]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("EMERGENCY_CONTACTS", "EMERGENCY_USER_NAME", "EMERGENCY_MEDICAL_NOTE", "EMERGENCY_COUNTDOWN_SECONDS",
              "EMERGENCY_CALL_FIRST", "EMERGENCY_TIMEZONE"):
        monkeypatch.delenv(k, raising=False)


class FakeTimer:
    def __init__(self, interval, fn, args=()):
        self.interval, self.fn, self.args = interval, fn, args
        self.started = self.cancelled = False
        self.daemon = False

    def start(self): self.started = True
    def cancel(self): self.cancelled = True
    def fire(self):
        if self.started and not self.cancelled:
            self.fn(*self.args)


class Clock:
    def __init__(self, t=1_000_000.0): self.t = t
    def __call__(self): return self.t


class MemStore:
    """Stands in for Turso; round-trips through JSON like the real thing."""
    def __init__(self): self.records = {}
    def save(self, rec): self.records[rec["id"]] = json.loads(json.dumps(rec))
    def load_all(self): return [json.loads(json.dumps(r)) for r in self.records.values()]
    def get_state(self, aid): return self.records.get(aid, {}).get("state")


class BrokenStore:
    def save(self, rec): raise RuntimeError("db down")
    def load_all(self): raise RuntimeError("db down")
    def get_state(self, aid): raise RuntimeError("db down")


def make(contacts=CONTACTS, sms=None, call=None, store=None, clock=None, **kw):
    clock = clock or Clock()
    timers, sent, calls, notes = [], [], [], []

    def timer_factory(interval, fn, args=()):
        t = FakeTimer(interval, fn, args)
        timers.append(t)
        return t

    def default_sms(number, text):
        sent.append((number, text))
        return {"ok": True}

    def default_call(number, text):
        calls.append((number, text))
        return {"ok": True}

    m = EmergencyManager(send_sms=sms or default_sms, send_call=call or default_call,
                         notify=lambda t, b: notes.append((t, b)), timer_factory=timer_factory, clock=clock,
                         contacts_provider=lambda: contacts, store=store if store is not None else MemStore(),
                         persist_async=False, sleep=lambda s: None, **kw)
    m.timers, m.sent, m.calls, m.notes, m.clock = timers, sent, calls, notes, clock
    return m


# ── lifecycle ──────────────────────────────────────────────────────────────────
def test_trigger_arms_a_countdown_and_sends_nothing_yet():
    m = make()
    a = m.trigger(reason="chest pain", lat=40.7, lon=-74.0, accuracy=12)
    assert a["state"] == "pending" and a["seconds_left"] == 15 and a["ok"]
    assert m.timers[0].interval == 15 and m.timers[0].started and m.timers[0].daemon
    assert m.sent == [] and m.notes == []


def test_countdown_expiry_texts_every_contact_and_is_honest_about_it():
    m = make()
    aid = m.trigger(reason="chest pain", lat=40.7, lon=-74.0, accuracy=12)["id"]
    m.timers[0].fire()
    a = m.get(aid)
    assert a["state"] == "sent" and [n for n, _ in m.sent] == ["+15551230001", "+15551230002"]
    text = m.sent[0][1]
    assert "EMERGENCY ALERT" in text and "chest pain" in text and "maps?q=40.70000,-74.00000" in text and "+/-12 m" in text
    assert "can't confirm anyone has read them" in a["summary"]          # "accepted" != "read"
    assert len(m.notes) == 1 and "FRIDAY emergency alert" in m.notes[0][0]
    assert "I can't call 911 for you" in a["note"] and a["call_911"] == "tel:911"


def test_cancel_before_zero_stops_everything():
    m = make()
    aid = m.trigger()["id"]
    r = m.cancel(aid)
    assert r["state"] == "cancelled" and "Nobody was notified" in r["summary"] and m.timers[0].cancelled
    m.timers[0].fire()
    m._fire(aid)                                                        # even a stray fire does nothing
    assert m.sent == [] and m.get(aid)["state"] == "cancelled"


def test_cancel_after_send_says_too_late_and_cancel_with_nothing_pending():
    m = make()
    aid = m.trigger()["id"]
    m.timers[0].fire()
    r = m.cancel(aid)
    assert r["ok"] is False and "Too late" in r["summary"]
    assert m.cancel()["state"] == "none"


def test_send_now_skips_the_wait_and_disarms_the_timer():
    m = make()
    aid = m.trigger()["id"]
    assert m.send_now(aid)["state"] == "sent" and len(m.sent) == 2 and m.timers[0].cancelled
    m.timers[0].fire()
    assert len(m.sent) == 2                                             # no double send
    assert m.send_now()["state"] == "none"


def test_one_live_alert_at_a_time():
    m = make()
    first = m.trigger(reason="a")
    second = m.trigger(reason="b")
    assert second["id"] == first["id"] and second["existing"] is True and len(m.timers) == 1


def test_hourly_rate_limit_blocks_a_fourth_live_alert_but_not_drills():
    m = make()
    for _ in range(fe.MAX_LIVE_PER_HOUR):
        m.trigger(); m.timers[-1].fire()
    blocked = m.trigger()
    assert blocked["ok"] is False and blocked["state"] == "rate_limited" and "911" in blocked["summary"]
    assert len(m.timers) == fe.MAX_LIVE_PER_HOUR                        # nothing was armed
    assert m.trigger(drill=True)["state"] == "pending"
    m.clock.t += 3601
    m.timers[-1].fire()                                                 # finish the drill
    assert m.trigger()["state"] == "pending"                            # window passed


def test_drill_sends_nothing_and_says_so():
    m = make()
    aid = m.trigger(reason="test", drill=True)["id"]
    m.timers[0].fire()
    a = m.get(aid)
    assert a["state"] == "drill" and m.sent == [] and m.notes == [] and a["summary"].startswith("Drill complete. NOTHING was sent")


def test_no_contacts_is_reported_as_nobody_notified():
    m = make(contacts=[])
    aid = m.trigger()["id"]
    m.timers[0].fire()
    a = m.get(aid)
    assert a["state"] == "not_configured" and "NOBODY" in a["summary"] and m.sent == []


def test_partial_failure_names_who_failed():
    def sms(number, text):
        return {"ok": True} if number.endswith("1") else {"error": "21211 invalid number"}
    m = make(sms=sms)
    aid = m.trigger()["id"]
    m.timers[0].fire()
    a = m.get(aid)
    assert a["state"] == "partial" and "FAILED" in a["summary"] and "Sam" in a["summary"] and "21211" in a["summary"]
    assert [r["ok"] for r in a["results"]] == [True, False]


def test_a_transient_failure_is_retried_once():
    calls = {}
    def sms(number, text):
        calls[number] = calls.get(number, 0) + 1
        return {"error": "timeout"} if (number.endswith("2") and calls[number] == 1) else {"ok": True}
    m = make(sms=sms)
    aid = m.trigger()["id"]
    m.timers[0].fire()
    a = m.get(aid)
    assert a["state"] == "sent" and calls["+15551230002"] == 2
    assert "after retry" in a["results"][1]["detail"]


def test_total_failure_and_sender_exceptions_never_pretend_success():
    def boom(number, text): raise ConnectionError("twilio down")
    m = make(sms=boom)
    aid = m.trigger()["id"]
    m.timers[0].fire()
    a = m.get(aid)
    assert a["state"] == "failed" and "could NOT text any emergency contact" in a["summary"] and "ConnectionError" in a["summary"]


def test_call_first_phones_only_the_first_contact(monkeypatch):
    monkeypatch.setenv("EMERGENCY_CALL_FIRST", "true")
    m = make()
    aid = m.trigger(reason="fall")["id"]
    m.timers[0].fire()
    assert [n for n, _ in m.calls] == ["+15551230001"] and "fall" in m.calls[0][1]
    assert [r["kind"] for r in m.get(aid)["results"]] == ["sms", "sms", "call"]


@pytest.mark.parametrize("arg,env,expected", [(1, None, 5), (999, None, 60), (30, None, 30), (None, "40", 40), (None, "garbage", 15), (None, "1", 5)])
def test_countdown_is_clamped(monkeypatch, arg, env, expected):
    if env is not None:
        monkeypatch.setenv("EMERGENCY_COUNTDOWN_SECONDS", env)
    m = make()
    assert m.trigger(countdown=arg)["seconds_left"] == expected


# ── contacts + message ─────────────────────────────────────────────────────────
def test_parse_contacts_accepts_good_numbers_and_reports_bad_ones():
    ok, problems = parse_contacts("Mom=+1 (555) 123-0001; Sam=+15551230002,+15551230002\nbad=12345, +15551230003")
    assert [c["number"] for c in ok] == ["+15551230001", "+15551230002", "+15551230003"]       # normalised + de-duplicated
    assert ok[2]["name"] == "…0003" and len(problems) == 1 and "bad" in problems[0]
    assert parse_contacts("") == ([], [])


def test_message_cleans_control_characters_and_includes_medical_note(monkeypatch):
    monkeypatch.setenv("EMERGENCY_USER_NAME", "Kai")
    monkeypatch.setenv("EMERGENCY_MEDICAL_NOTE", "Allergic to penicillin")
    m = make()
    a = m.trigger(reason="a\nb\x00c" + "x" * 500)["id"]
    msg = m.build_message(m._alerts[a])
    assert "\n" not in msg and "\x00" not in msg and "EMERGENCY ALERT from Kai" in msg and "Allergic to penicillin" in msg
    assert "Location: unavailable" in msg and len(msg) < 700


def test_message_time_is_local_when_a_zone_is_configured(monkeypatch):
    m = make()
    aid = m.trigger()["id"]
    assert re.search(r"at \d{2}:\d{2} UTC\.", m.build_message(m._alerts[aid]))
    monkeypatch.setenv("EMERGENCY_TIMEZONE", "America/New_York")
    assert re.search(r"at \d{1,2}:\d{2} [AP]M E[SD]T\.", m.build_message(m._alerts[aid]))
    monkeypatch.setenv("EMERGENCY_TIMEZONE", "Not/AZone")
    assert "UTC" in m.build_message(m._alerts[aid])                      # bad zone never breaks an alert


def test_drill_messages_are_unmistakable():
    m = make()
    aid = m.trigger(drill=True)["id"]
    assert m.build_message(m._alerts[aid]).startswith("[DRILL - NOT A REAL EMERGENCY]")


def test_location_can_be_attached_while_the_countdown_runs():
    m = make()
    aid = m.trigger()["id"]
    assert m.get(aid)["location_url"] == ""
    r = m.update_location(aid, 40.7128, -74.006, 8)
    assert r["location_url"].endswith("q=40.71280,-74.00600")
    m.timers[0].fire()
    assert "q=40.71280,-74.00600" in m.sent[0][1] and "+/-8 m" in m.sent[0][1]
    assert m.update_location(aid, 1, 1)["ok"] is False                  # too late once it has sent


# ── persistence, recovery, and cross-instance cancel ───────────────────────────
def test_state_changes_are_persisted_without_internals():
    store = MemStore()
    m = make(store=store)
    aid = m.trigger(reason="x")["id"]
    assert store.records[aid]["state"] == "pending" and "_timer" not in store.records[aid]
    m.timers[0].fire()
    assert store.records[aid]["state"] == "sent" and len(store.records[aid]["results"]) == 2
    aid2 = m.trigger()["id"]
    m.cancel(aid2)
    assert store.records[aid2]["state"] == "cancelled"


def test_persistence_failure_never_blocks_or_breaks_an_alert():
    m = make(store=BrokenStore())
    aid = m.trigger()["id"]
    m.timers[0].fire()
    assert m.get(aid)["state"] == "sent" and len(m.sent) == 2


def test_async_persistence_writes_the_latest_state():
    store = MemStore()
    m = EmergencyManager(send_sms=lambda n, t: {"ok": True}, notify=lambda *a: None, timer_factory=FakeTimer,
                         contacts_provider=lambda: CONTACTS, store=store, persist_async=True, sleep=lambda s: None)
    aid = m.trigger()["id"]
    m.cancel(aid)
    m._executor.shutdown(wait=True)
    assert store.records[aid]["state"] == "cancelled"


def _crash_and_restart(state_setup, later=0.0, **kw):
    """Old instance does `state_setup`, 'crashes', a new instance boots `later` seconds on with the same store."""
    store, clock = MemStore(), Clock()
    old = make(store=store, clock=clock)
    aid = state_setup(old)
    new = make(store=store, clock=Clock(clock.t + later), **kw)
    return old, new, aid, new.recover()


def test_restart_mid_countdown_rearms_the_alert_instead_of_losing_it():
    old, new, aid, actions = _crash_and_restart(lambda m: m.trigger(reason="help")["id"], later=5)
    assert actions == [{"id": aid, "action": "rearmed", "delay": 30.0}]      # 15s deadline + 20s margin - 5s elapsed
    assert new.get(aid)["state"] == "pending"
    new.timers[0].fire()
    assert new.get(aid)["state"] == "sent" and len(new.sent) == 2


def test_restart_after_the_deadline_still_sends_promptly():
    old, new, aid, actions = _crash_and_restart(lambda m: m.trigger()["id"], later=60)
    assert actions[0]["action"] == "rearmed" and actions[0]["delay"] == 0.0
    new.timers[0].fire()
    assert new.get(aid)["state"] == "sent"


def test_a_stale_alert_is_never_sent_late_and_the_user_is_told():
    # Literal numbers on purpose: a test derived from the constant it checks can't catch that constant being broken.
    old, new, aid, actions = _crash_and_restart(lambda m: m.trigger()["id"], later=3600)      # an hour overdue
    assert actions == [{"id": aid, "action": "expired"}]
    assert new.timers == [] and new.sent == [] and new.get(aid)["state"] == "expired"
    assert len(new.notes) == 1 and "NOT sent" in new.notes[0][1] and "min ago" in new.notes[0][1]


def test_an_alert_only_a_few_minutes_overdue_is_still_sent():
    old, new, aid, actions = _crash_and_restart(lambda m: m.trigger()["id"], later=15 + 300)  # 5 minutes overdue
    assert actions[0]["action"] == "rearmed" and actions[0]["delay"] == 0.0
    new.timers[0].fire()
    assert new.get(aid)["state"] == "sent" and len(new.sent) == 2


def test_crash_during_sending_is_reported_as_interrupted_not_resent():
    def setup(m):
        aid = m.trigger()["id"]
        m._begin_send(aid)                                              # state 'sending', then the process dies
        return aid
    old, new, aid, actions = _crash_and_restart(setup, later=3)
    assert actions == [{"id": aid, "action": "interrupted"}]
    a = new.get(aid)
    assert a["state"] == "interrupted" and "MAY have been texted" in a["summary"] and new.sent == [] and len(new.notes) == 1


def test_finished_alerts_are_adopted_and_keep_the_rate_limit_honest():
    def setup(m):
        for _ in range(fe.MAX_LIVE_PER_HOUR):
            m.trigger(); m.timers[-1].fire()
        return m.latest()["id"]
    old, new, aid, actions = _crash_and_restart(setup, later=60)
    assert {a["action"] for a in actions} == {"adopted"} and len(actions) == fe.MAX_LIVE_PER_HOUR
    assert new.trigger()["state"] == "rate_limited"                     # a restart doesn't reset the limit


def test_overdue_drills_close_quietly_and_recovery_is_idempotent_and_safe():
    old, new, aid, actions = _crash_and_restart(lambda m: m.trigger(drill=True)["id"], later=60)
    assert actions == [{"id": aid, "action": "drill_closed"}] and new.notes == [] and new.get(aid)["state"] == "drill"
    assert new.recover() == []                                          # second call changes nothing
    assert make(store=BrokenStore()).recover() == []                    # a down database can't break boot


def test_a_still_alive_old_instance_wins_and_the_recovered_timer_does_not_double_send():
    store, clock = MemStore(), Clock()
    old = make(store=store, clock=clock)
    aid = old.trigger()["id"]
    new = make(store=store, clock=Clock(clock.t + 1))                  # deploy overlap: both instances alive
    assert new.recover()[0]["action"] == "rearmed"
    old.timers[0].fire()                                                # the original fires on time
    assert len(old.sent) == 2
    new.timers[0].fire()                                                # the recovered timer fires 20s later
    assert new.sent == [] and new.get(aid)["state"] == "sent"


def test_a_cancel_on_another_instance_vetoes_this_instances_timer():
    store = MemStore()
    m = make(store=store)
    aid = m.trigger()["id"]
    store.records[aid]["state"] = "cancelled"                          # e.g. cancelled via another gunicorn worker
    m.timers[0].fire()
    assert m.sent == [] and m.get(aid)["state"] == "cancelled"


def test_if_the_store_is_down_the_alert_still_fires():
    m = make(store=MemStore())
    aid = m.trigger()["id"]
    m._store = BrokenStore()                                            # can't verify -> send (safer error for an emergency)
    m.timers[0].fire()
    assert len(m.sent) == 2


# ── the real Turso store, against a real SQL engine ────────────────────────────
@pytest.fixture
def turso_sqlite(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)

    def _execute(sql, args=None):
        cur = conn.execute(sql, args or [])
        conn.commit()
        return {"cols": [], "rows": [list(r) for r in cur.fetchall()]}

    monkeypatch.setattr("db.turso_http_client.is_configured", lambda: True)
    monkeypatch.setattr("db.turso_http_client._execute", _execute)
    return conn


def test_turso_store_round_trips_through_real_sql(turso_sqlite):
    s = TursoStore()
    s.save({"id": "abc", "state": "pending", "deadline": 1.0, "results": []})
    s.save({"id": "abc", "state": "sent", "deadline": 1.0, "results": [1]})        # upsert, not duplicate
    assert s.get_state("abc") == "sent" and s.get_state("nope") is None
    assert [r["state"] for r in s.load_all()] == ["sent"]


def test_full_restart_recovery_through_the_real_store(turso_sqlite):
    clock = Clock()
    old = make(store=TursoStore(), clock=clock)
    aid = old.trigger(reason="help", lat=1.0, lon=2.0)["id"]
    new = make(store=TursoStore(), clock=Clock(clock.t + 2))
    assert new.recover()[0]["action"] == "rearmed"
    new.timers[0].fire()
    assert new.get(aid)["state"] == "sent" and "q=1.00000,2.00000" in new.sent[0][1]


def test_turso_store_is_inert_when_turso_is_not_configured(monkeypatch):
    monkeypatch.setattr("db.turso_http_client.is_configured", lambda: False)
    s = TursoStore()
    s.save({"id": "x", "state": "pending"})
    assert s.load_all() == [] and s.get_state("x") is None


# ── HTTP routes ────────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch):
    import core.access_auth as auth
    import routes.emergency as route
    from server import app
    monkeypatch.setattr(auth, "ACCESS_TOKEN", "test-token")
    m = make()
    monkeypatch.setattr(route, "_mgr", lambda: m)
    c = app.test_client()
    c.manager = m
    return c


AUTH = {"Authorization": "Bearer test-token"}


def test_routes_are_closed_without_the_token_and_disabled_when_unconfigured(client, monkeypatch):
    for method, path in (("get", "/api/emergency/status"), ("post", "/api/emergency/trigger"), ("post", "/api/emergency/cancel"),
                         ("post", "/api/emergency/send_now"), ("post", "/api/emergency/location"), ("get", "/api/emergency/alert/x")):
        assert getattr(client, method)(path).status_code == 401, path
    assert client.manager.timers == []
    import core.access_auth as auth
    monkeypatch.setattr(auth, "ACCESS_TOKEN", "")
    assert client.post("/api/emergency/trigger", json={}).status_code == 503        # never fail OPEN for texting your family


def test_trigger_validates_input(client):
    for bad in ({"lat": 91, "lon": 0}, {"lat": 10}, {"lat": "x", "lon": 0}, {"lat": True, "lon": 0}, {"drill": "yes"}, {"reason": 5}, {"accuracy": -1}):
        r = client.post("/api/emergency/trigger", json=bad, headers=AUTH)
        assert r.status_code == 400, bad
    assert client.manager.timers == []


def test_trigger_cancel_flow_over_http(client):
    r = client.post("/api/emergency/trigger", json={"reason": "fall", "lat": 40.7, "lon": -74.0, "accuracy": 9}, headers=AUTH)
    a = r.get_json()
    assert r.status_code == 200 and a["state"] == "pending"
    assert client.get(f"/api/emergency/alert/{a['id']}", headers=AUTH).get_json()["state"] == "pending"
    assert client.get("/api/emergency/alert/nope", headers=AUTH).status_code == 404
    c = client.post("/api/emergency/cancel", json={"id": a["id"]}, headers=AUTH).get_json()
    assert c["state"] == "cancelled" and client.manager.sent == []


def test_send_now_location_and_rate_limit_over_http(client):
    aid = client.post("/api/emergency/trigger", json={}, headers=AUTH).get_json()["id"]
    assert client.post("/api/emergency/location", json={"id": aid, "lat": 1, "lon": 2}, headers=AUTH).get_json()["location_url"]
    assert client.post("/api/emergency/location", json={"lat": 1}, headers=AUTH).status_code == 400
    assert client.post("/api/emergency/send_now", json={"id": aid}, headers=AUTH).get_json()["state"] == "sent"
    for _ in range(fe.MAX_LIVE_PER_HOUR - 1):
        client.post("/api/emergency/trigger", json={}, headers=AUTH)
        client.manager.timers[-1].fire()
    assert client.post("/api/emergency/trigger", json={}, headers=AUTH).status_code == 429


def test_status_reports_readiness_and_the_911_note(client):
    s = client.get("/api/emergency/status", headers=AUTH).get_json()
    assert "ready" in s and "warnings" in s and s["call_911"] == "tel:911" and "can't call 911" in s["note"]
    assert all(c["number"].startswith("…") for c in s["contacts"])           # numbers are masked


# ── the glasses page ───────────────────────────────────────────────────────────
def test_glasses_page_has_the_safety_behaviours(client):
    html = client.get("/hud/glasses", headers=AUTH).get_data(as_text=True)
    for needle in ("HOLD FOR SOS", "tel:911", "/api/emergency/trigger", "/api/emergency/location", "watchPosition",
                   "wakeLock", "CANCEL FAILED", "CONNECTION LOST", "deadlineLocal"):
        assert needle in html, needle


def test_glasses_page_starts_the_alert_before_waiting_for_a_gps_fix(client):
    html = client.get("/hud/glasses", headers=AUTH).get_data(as_text=True)
    trigger = html[html.index("async function trigger()"):html.index("$('cancel').addEventListener")]
    assert "getCurrentPosition" not in trigger and "await location_" not in trigger       # the old 6-second stall
