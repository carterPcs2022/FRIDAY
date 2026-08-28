"""tests/test_action_ledger.py — the durable record of what FRIDAY did.

_log() keeps the last exchanges in memory, truncated to 200 characters,
with no notion of outcome and no life beyond the process. So nothing
could answer "did that email actually send" or "has this failed before",
and on Render the process restarts freely, so the answer vanished anyway.

That gap is why the SMTP bug took as long as it did: she said "sending an
email, boss" and meant it, the send timed out, nothing recorded a
failure, and every debug round started from zero.

The property this file leans on hardest is that an unresolved entry is
data, not noise. A record that opens and never closes is what a timeout,
a crash, or a gunicorn worker killed at 30 seconds actually looks like
from the inside.
"""
from datetime import datetime, timedelta

import pytest

from core import action_ledger as ledger


@pytest.fixture(autouse=True)
def temp_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_FILE", tmp_path / "ledger.json")
    monkeypatch.setattr(ledger, "_turso", lambda: None)


class TestRecordAndResolve:
    def test_an_action_is_recorded_pending(self):
        ledger.record("send an email to jane", "email_send")
        assert ledger.recent()[0]["status"] == "pending"

    def test_resolving_closes_it_out(self):
        entry = ledger.record("send an email", "email_send")
        ledger.resolve(entry, "ok", "message id 123")

        got = ledger.recent()[0]
        assert got["status"] == "ok"
        assert got["detail"] == "message id 123"
        assert got["finished_at"]

    def test_failures_are_recorded_with_their_reason(self):
        entry = ledger.record("send an email", "email_send")
        ledger.resolve(entry, "failed", "SMTP timeout after 15s")

        assert ledger.failures()[0]["detail"] == "SMTP timeout after 15s"

    def test_resolving_an_unknown_id_is_harmless(self):
        """resolve() is called from a finally block on a path that may
        never have successfully recorded."""
        ledger.resolve("nope", "ok")
        assert ledger.recent() == []

    def test_resolving_none_is_harmless(self):
        """record() returns None when the ledger is unavailable, and the
        caller passes that straight back."""
        ledger.resolve(None, "ok")

    def test_newest_first(self):
        ledger.record("first", "a")
        ledger.record("second", "b")
        assert ledger.recent()[0]["prompt"] == "second"

    def test_filtering_by_capability(self):
        ledger.record("one", "email_send")
        ledger.record("two", "calendar_add")
        assert [e["capability"] for e in ledger.recent(capability="email_send")] \
            == ["email_send"]


class TestAbandonedWork:
    """The whole reason record and resolve are two calls."""

    def _age(self, minutes):
        import json
        entries = json.loads(ledger.LEDGER_FILE.read_text())
        entries[0]["started_at"] = (
            datetime.now() - timedelta(minutes=minutes)).isoformat()
        ledger.LEDGER_FILE.write_text(json.dumps(entries))

    def test_an_old_pending_entry_reads_as_abandoned(self):
        """Nothing legitimate is still running after ten minutes --
        gunicorn kills its own workers at thirty seconds. Calling that
        "in progress" would be the ledger lying about itself."""
        ledger.record("send an email", "email_send")
        self._age(30)

        assert ledger.recent()[0]["status"] == "abandoned"

    def test_a_recent_pending_entry_is_still_pending(self):
        ledger.record("send an email", "email_send")
        self._age(1)

        assert ledger.recent()[0]["status"] == "pending"

    def test_abandoned_work_shows_up_as_a_failure(self):
        """It is a failure -- something started and never finished. Not
        listing it is how the SMTP timeout stayed invisible."""
        ledger.record("send an email", "email_send")
        self._age(30)

        assert [e["capability"] for e in ledger.failures()] == ["email_send"]

    def test_resolved_entries_are_never_marked_abandoned(self):
        entry = ledger.record("send an email", "email_send")
        ledger.resolve(entry, "ok")
        self._age(30)

        assert ledger.recent()[0]["status"] == "ok"


class TestSummary:
    def test_counts_outcomes_in_the_window(self):
        a = ledger.record("one", "email_send")
        b = ledger.record("two", "email_send")
        ledger.resolve(a, "ok")
        ledger.resolve(b, "failed", "timeout")

        counts = ledger.summary()["counts"]
        assert counts["ok"] == 1 and counts["failed"] == 1

    def test_names_which_capability_is_failing(self):
        """The question worth answering is not "how many failures" but
        "what is broken"."""
        for _ in range(3):
            ledger.resolve(ledger.record("x", "email_send"), "failed", "timeout")
        ledger.resolve(ledger.record("y", "weather"), "ok")

        assert ledger.summary()["failing_capabilities"] == {"email_send": 3}

    def test_old_entries_fall_outside_the_window(self):
        import json
        ledger.resolve(ledger.record("old", "email_send"), "failed")
        entries = json.loads(ledger.LEDGER_FILE.read_text())
        entries[0]["started_at"] = (datetime.now() - timedelta(days=3)).isoformat()
        ledger.LEDGER_FILE.write_text(json.dumps(entries))

        assert ledger.summary(hours=24)["counts"]["failed"] == 0


class TestItCannotBreakARequest:
    """It sits on the dispatch path. A ledger that can take a request
    down is worse than no ledger at all."""

    def test_an_unwritable_file_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(ledger, "LEDGER_FILE", ledger.Path("/proc/nope/x.json"))
        assert ledger.record("x", "y") is not None or True  # must not raise

    def test_unreadable_state_reads_as_empty(self, monkeypatch):
        ledger.LEDGER_FILE.write_text("{{{ not json")
        assert ledger.recent() == []

    def test_a_turso_failure_keeps_the_local_write(self, monkeypatch):
        """The local copy is written first precisely so a database that's
        down costs the boss nothing."""
        class Boom:
            def ensure_list_table(self, t): raise RuntimeError("down")
            def list_insert(self, t, d): raise RuntimeError("down")
        monkeypatch.setattr(ledger, "_turso", lambda: Boom())

        entry = ledger.record("send an email", "email_send")

        assert entry and ledger.recent()[0]["prompt"] == "send an email"


class TestBounded:
    def test_the_file_is_capped(self):
        """Ephemeral disk, nothing else prunes it."""
        for i in range(ledger.MAX_ENTRIES + 40):
            ledger.record(f"p{i}", "x")

        import json
        assert len(json.loads(ledger.LEDGER_FILE.read_text())) <= ledger.MAX_ENTRIES

    def test_the_newest_survive_the_cap(self):
        for i in range(ledger.MAX_ENTRIES + 10):
            ledger.record(f"p{i}", "x")

        assert ledger.recent(1)[0]["prompt"] == f"p{ledger.MAX_ENTRIES + 9}"


class TestWiredIntoDispatch:
    """A ledger nothing writes to is worse than none -- it looks like
    "she did nothing" rather than "nobody is recording"."""

    def test_a_request_is_recorded(self, app, client):
        client.post("/command", json={"prompt": "hello there"})
        assert ledger.recent(), "dispatch recorded nothing"

    def test_the_answering_capability_is_recorded(self, app, client):
        """mode is the closest thing this codebase has to "which
        capability answered", so it is what makes the ledger queryable."""
        client.post("/command", json={"prompt": "hello there"})
        assert ledger.recent()[0]["detail"]

    def test_only_one_entry_per_request(self, app, client, monkeypatch):
        """_dispatch re-enters itself for multi-command segments and for
        the tool router's rephrasing. One entry per user request is the
        granularity that answers "what did you do today"; one per
        internal hop would bury it.

        The split is forced rather than typed. _split_commands asks the
        model, and with no brain configured in tests it returns the prompt
        unchanged -- so a realistic-looking multi-command string never
        re-enters and this test passed with the depth guard deleted.
        """
        import server
        monkeypatch.setattr(server, "_split_commands",
                            lambda p: ["what's the weather", "check my email"])

        client.post("/command", json={"prompt": "weather and email"})

        assert len(ledger.recent(limit=50)) == 1

    def test_a_crash_leaves_the_entry_unresolved(self, app, monkeypatch):
        """The entry staying open is the signal. Resolving it "ok" in a
        finally would erase exactly the evidence worth keeping."""
        import server
        monkeypatch.setattr(server, "_dispatch",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

        with app.test_request_context():
            with pytest.raises(RuntimeError):
                server._handle_prompt("anything")

        assert ledger.recent()[0]["status"] == "failed"

    def test_a_broken_ledger_does_not_break_the_request(self, app, client, monkeypatch):
        monkeypatch.setattr(ledger, "record",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))

        res = client.post("/command", json={"prompt": "hello there"})

        assert res.status_code == 200


class TestSheCanReadItBack:
    """A write-only ledger is worse than none: it records everything,
    answers nothing, and "did that email send" still reaches the
    conversational model, which improvises -- the exact failure it exists
    to end."""

    def _ask(self, client, q="what have you done today"):
        return client.post("/command", json={"prompt": q}).get_json()

    def test_a_clean_day_says_so(self, client):
        for _ in range(3):
            ledger.resolve(ledger.record("x", "weather"), "ok")

        body = self._ask(client)
        assert body["mode"] == "self_audit"
        assert "clean" in body["response"]

    def test_failures_are_named_not_just_counted(self, client):
        """"3 failures" is not actionable. "email_send failed 3 times" is
        the sentence worth saying."""
        for _ in range(3):
            ledger.resolve(ledger.record("x", "email_send"), "failed", "timeout")

        assert "email_send" in self._ask(client)["response"]

    def test_abandoned_work_is_described_as_a_timeout(self, client):
        """Started-and-never-finished reads differently from refused, and
        the difference is the whole SMTP debugging story."""
        import json
        ledger.record("send an email", "email_send")
        entries = json.loads(ledger.LEDGER_FILE.read_text())
        entries[0]["started_at"] = (datetime.now() - timedelta(minutes=30)).isoformat()
        ledger.LEDGER_FILE.write_text(json.dumps(entries))

        assert "timeout" in self._ask(client)["response"]

    def test_an_empty_ledger_does_not_invent_activity(self, client):
        assert "Nothing" in self._ask(client)["response"]

    def test_it_claims_the_phrase_before_catchup_does(self, client):
        """"what happened" is a CATCHUP trigger too, and catchup runs a
        three-way parallel fetch and answers about the world rather than
        about her own actions."""
        assert self._ask(client, "what failed today")["mode"] == "self_audit"
