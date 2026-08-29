"""tests/test_outcome_verify.py — checking that an action really happened.

Levels 1-3 all concern what FRIDAY says she *can* do. None of them helps
once a real handler runs: if it acts and the action half-fails, she
reports success, because "the handler returned" and "the thing happened"
are different facts and only the first was ever checked.

That is exactly the SMTP bug. She said "sending an email, boss" and meant
it, the send timed out inside a library call, and the success path had
already been taken.

The state this file guards hardest is `unknown`. A network blip, an
expired token, or an id that never came back are all cases where she
genuinely cannot tell -- and reporting those as failures would have her
announcing that an email didn't send when she simply couldn't look. That
is a worse lie than the one being fixed, because it arrives with
confidence.
"""
from unittest import mock

import pytest

from core import outcome_verify as verify


@pytest.fixture(autouse=True)
def restore_registry():
    original = dict(verify._VERIFIERS)
    yield
    verify._VERIFIERS.clear()
    verify._VERIFIERS.update(original)


class TestTheThreeStates:
    def test_confirmed_leaves_the_reply_untouched(self):
        """The overwhelmingly common case. Appending "(verified)" to
        every success would make her tiresome and train the boss to stop
        reading."""
        out = verify.amend("Sent.", "email_send",
                           {"state": "confirmed", "label": "sent that email"})
        assert out == "Sent."

    def test_contradicted_retracts_the_claim(self):
        out = verify.amend("Sent.", "email_send",
                           {"state": "contradicted", "detail": "no such message",
                            "label": "sent that email"})
        assert "Correction" in out and "no such message" in out
        assert not out.startswith("Sent.")

    def test_unknown_softens_rather_than_retracts(self):
        """The distinction the whole module exists for: "couldn't
        confirm" is a different sentence from "didn't work", and the
        difference matters most when both are plausible."""
        out = verify.amend("Sent.", "email_send",
                           {"state": "unknown", "label": "sent that email"})
        assert out.startswith("Sent.")
        assert "couldn't confirm" in out.lower()


class TestVerifyNeverRaises:
    """It runs on the request path after a successful action. It must
    never turn a working send into an error."""

    def test_a_crashing_verifier_yields_unknown(self):
        verify.register("boom", "did that", mock.Mock(side_effect=RuntimeError("x")))
        assert verify.verify("boom", {})["state"] == "unknown"

    def test_a_verifier_returning_nonsense_yields_unknown(self):
        """Guessing which way it meant would be worse than saying so."""
        verify.register("weird", "did that", lambda p: {"state": "probably?"})
        assert verify.verify("weird", {})["state"] == "unknown"

    def test_a_verifier_returning_none_yields_unknown(self):
        verify.register("none", "did that", lambda p: None)
        assert verify.verify("none", {})["state"] == "unknown"

    def test_an_unregistered_mode_is_not_verifiable(self):
        assert not verify.is_verifiable("weather")


class TestRegisteredModesAreReal:
    """The registry keys on the mode strings handlers tag their responses
    with. A renamed mode would silently switch verification off with no
    test failing anywhere -- the same rot that made the tool router's
    catalog guard necessary."""

    @pytest.mark.parametrize("mode", ["email_send", "email_compose_send", "calendar"])
    def test_the_mode_is_still_emitted_by_a_handler(self, mode):
        from pathlib import Path
        import server
        src = Path(server.__file__).read_text()
        assert f'"mode": "{mode}"' in src, (
            f"no handler emits mode {mode!r} any more, so its verifier is dead"
        )


class TestGmailReadback:
    def _gmail(self, status, body=None):
        g = mock.Mock()
        g._get_send_access_token.return_value = "tok"
        r = mock.Mock(status_code=status)
        r.json.return_value = body or {}
        return g, r

    def test_a_message_in_sent_is_confirmed(self, monkeypatch):
        import services.friday_gmail as gm
        g = gm.FridayGmail()
        monkeypatch.setattr(g, "_get_send_access_token", lambda: "tok")
        r = mock.Mock(status_code=200)
        r.json.return_value = {"labelIds": ["SENT", "INBOX"]}
        monkeypatch.setattr(gm.httpx, "get", lambda *a, **k: r)

        assert g.message_exists("abc")["state"] == "confirmed"

    def test_a_missing_message_is_contradicted(self, monkeypatch):
        import services.friday_gmail as gm
        g = gm.FridayGmail()
        monkeypatch.setattr(g, "_get_send_access_token", lambda: "tok")
        monkeypatch.setattr(gm.httpx, "get", lambda *a, **k: mock.Mock(status_code=404))

        assert g.message_exists("abc")["state"] == "contradicted"

    def test_a_message_not_in_sent_is_contradicted(self, monkeypatch):
        """It exists but never left -- a draft. Reporting that as sent is
        the failure mode being closed."""
        import services.friday_gmail as gm
        g = gm.FridayGmail()
        monkeypatch.setattr(g, "_get_send_access_token", lambda: "tok")
        r = mock.Mock(status_code=200)
        r.json.return_value = {"labelIds": ["DRAFT"]}
        monkeypatch.setattr(gm.httpx, "get", lambda *a, **k: r)

        assert g.message_exists("abc")["state"] == "contradicted"

    def test_a_network_failure_is_unknown_not_contradicted(self, monkeypatch):
        import services.friday_gmail as gm
        g = gm.FridayGmail()
        monkeypatch.setattr(g, "_get_send_access_token", lambda: "tok")
        def boom(*a, **k):
            raise RuntimeError("connection reset")
        monkeypatch.setattr(gm.httpx, "get", boom)

        assert g.message_exists("abc")["state"] == "unknown"

    def test_a_server_error_is_unknown(self, monkeypatch):
        import services.friday_gmail as gm
        g = gm.FridayGmail()
        monkeypatch.setattr(g, "_get_send_access_token", lambda: "tok")
        monkeypatch.setattr(gm.httpx, "get", lambda *a, **k: mock.Mock(status_code=503))

        assert g.message_exists("abc")["state"] == "unknown"

    def test_no_id_is_unknown(self):
        import services.friday_gmail as gm
        assert gm.FridayGmail().message_exists("")["state"] == "unknown"


class TestTheSendCapturesAnId:
    """Without the id there is nothing to verify against, and the API was
    handing it back and having it thrown away."""

    def test_send_returns_the_gmail_message_id(self, monkeypatch):
        import services.friday_gmail as gm
        g = gm.FridayGmail()
        monkeypatch.setattr(g, "send_is_connected", lambda: True)
        monkeypatch.setattr(g, "_get_send_access_token", lambda: "tok")
        r = mock.Mock(status_code=200)
        r.json.return_value = {"id": "18f2c"}
        monkeypatch.setattr(gm.httpx, "post", lambda *a, **k: r)

        result = g.send_email("jane@example.com", "hi", "body")

        assert result["ok"] and result["message_id"] == "18f2c"


class TestWiredIntoDispatch:
    """Split deliberately into "does _verify_outcome do the right thing"
    and "does dispatch call it".

    The first version of this drove everything through /command and
    asserted on the resulting mode. It passed locally and failed in CI,
    because friday_brain doesn't import there -- the email handler never
    engaged, the request fell through to emergency(), and the assertions
    were about a path that never ran. Which handler answers depends on
    which optional packages installed, so a test shaped that way measures
    the environment, not the code.
    """

    def _response(self, app, mode="email_send", text="Sent.", **extra):
        from flask import jsonify
        with app.test_request_context():
            return jsonify({"response": text, "mode": mode, **extra})

    def _verifier(self, monkeypatch, state, detail=""):
        monkeypatch.setattr(verify, "_VERIFIERS", dict(verify._VERIFIERS))
        verify.register("email_send", "sent that email",
                        lambda p: {"state": state, "detail": detail})

    def test_a_contradicted_send_is_retracted_in_the_reply(
            self, app, monkeypatch):
        """The whole point. She said it went; it didn't; the boss must be
        told before he assumes it did."""
        import server
        self._verifier(monkeypatch, "contradicted", "no such message")

        with app.test_request_context():
            out = server._verify_outcome(self._response(app), None)

        body = out.get_json()
        assert "Correction" in body["response"]
        assert body["verified"] == "contradicted"

    def test_an_unconfirmable_send_is_flagged_not_retracted(
            self, app, monkeypatch):
        import server
        self._verifier(monkeypatch, "unknown", "network down")

        with app.test_request_context():
            body = server._verify_outcome(self._response(app), None).get_json()

        assert body["response"].startswith("Sent.")
        assert "couldn't confirm" in body["response"].lower()

    def test_a_confirmed_send_is_left_exactly_alone(self, app, monkeypatch):
        import server
        self._verifier(monkeypatch, "confirmed")

        with app.test_request_context():
            body = server._verify_outcome(self._response(app), None).get_json()

        assert body["response"] == "Sent."
        assert "verified" not in body

    def test_an_unverifiable_mode_is_left_completely_alone(self, app):
        """Verification costs a round trip, so it must not run for the
        modes with no verifier -- which is nearly all of them."""
        import server
        with app.test_request_context():
            body = server._verify_outcome(
                self._response(app, mode="weather", text="Sunny."), None).get_json()

        assert body["response"] == "Sunny." and "verified" not in body

    def test_a_contradicted_action_is_a_failure_in_the_ledger(
            self, app, monkeypatch):
        import server
        from core import action_ledger
        self._verifier(monkeypatch, "contradicted", "no such message")
        entry = action_ledger.record("send it", "")

        with app.test_request_context():
            server._verify_outcome(self._response(app), entry)

        assert action_ledger.recent()[0]["status"] == "failed"

    def test_an_unconfirmable_action_is_not_recorded_as_a_failure(
            self, app, monkeypatch):
        """She did the work and the service accepted it; only the
        confirmation is missing. Logging that as failure would fill the
        ledger with phantom breakage every time the network hiccuped."""
        import server
        from core import action_ledger
        self._verifier(monkeypatch, "unknown", "network down")
        entry = action_ledger.record("send it", "")

        with app.test_request_context():
            server._verify_outcome(self._response(app), entry)

        assert action_ledger.recent()[0]["status"] == "ok"

    def test_dispatch_actually_calls_verification(self, app, client, monkeypatch):
        """The tests above all pass with the call site deleted -- this is
        the one that proves the feature is reachable at all."""
        import server
        seen = []
        real = server._verify_outcome
        monkeypatch.setattr(server, "_verify_outcome",
                            lambda r, e: (seen.append(1), real(r, e))[1])

        client.post("/command", json={"prompt": "hello there"})

        assert seen, "_handle_prompt never called _verify_outcome"

    def test_verification_runs_once_per_request_not_per_hop(
            self, app, client, monkeypatch):
        import server
        seen = []
        real = server._verify_outcome
        monkeypatch.setattr(server, "_verify_outcome",
                            lambda r, e: (seen.append(1), real(r, e))[1])
        monkeypatch.setattr(server, "_split_commands",
                            lambda p: ["what's the weather", "check my email"])

        client.post("/command", json={"prompt": "weather and email"})

        assert len(seen) == 1
