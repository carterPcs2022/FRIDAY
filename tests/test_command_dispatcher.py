"""tests/test_command_dispatcher.py — regression coverage for the /command
NLU dispatcher refactor: command()'s ~1100-line if-chain was mechanically
split into individually named module-level _cmd_* functions, called
sequentially in the exact original order. Same behavior, same ordering,
just named. These tests exist to catch the two ways that kind of
extraction can quietly break: a block losing access to a variable it used
to share scope with (p_lower, matched_recon, etc.), or the call order
drifting from the original if-chain's documented ordering dependencies.
"""
from unittest import mock

import server


def _post(client, prompt):
    return client.post("/command", json={"prompt": prompt})


# Every function name from the extraction plan, in call order. Mirrors the
# dispatcher's actual sequence inside command() -- if this list and the
# real call order in server.py ever diverge, that's exactly the kind of
# silent drift this test is meant to catch.
DISPATCHER_FUNCTIONS = [
    "_cmd_lockdown_locked", "_cmd_lockdown_trigger", "_cmd_mayday",
    "_cmd_safe_checkin", "_cmd_security_screen", "_cmd_learn_voice_mode",
    "_cmd_dark_mode", "_cmd_capabilities", "_cmd_weather", "_cmd_news", "_cmd_translate",
    "_cmd_code_review", "_cmd_remember_this", "_cmd_people_brief",
    "_cmd_caller_id", "_cmd_call_initiate", "_cmd_sms_send", "_cmd_catchup",
    "_cmd_focus", "_cmd_habit_log", "_cmd_journal", "_cmd_probability",
    "_cmd_recon", "_cmd_diagnostics", "_cmd_self_repair", "_cmd_cross_check", "_cmd_combat_mode",
    "_cmd_normal_mode", "_cmd_priority", "_cmd_travel", "_cmd_spotify_stop",
    "_cmd_spotify_play", "_cmd_calendar_add", "_cmd_goal_report",
    "_cmd_goal_add", "_cmd_goal_progress", "_cmd_email_draft",
    "_cmd_email_send", "_cmd_email_compose_send", "_cmd_email_triage",
    "_cmd_email_summary", "_cmd_note", "_cmd_create_file", "_cmd_file_recall",
    "_cmd_reminder", "_cmd_task_show",
    "_cmd_task_add", "_cmd_med_schedule", "_cmd_med_taken", "_cmd_med_skip",
    "_cmd_med_add", "_cmd_homekit", "_cmd_mac_app", "_cmd_ha_status",
    "_cmd_ha_toggle", "_cmd_jarvis_proxy",
]


class TestDispatcherFunctionsExist:
    def test_all_extracted_functions_are_present_and_callable(self):
        missing = [n for n in DISPATCHER_FUNCTIONS if not callable(getattr(server, n, None))]
        assert missing == []

    def test_no_unexpected_extra_cmd_functions(self):
        actual = {n for n in dir(server) if n.startswith("_cmd_")}
        assert actual == set(DISPATCHER_FUNCTIONS)


class TestDispatcherOrdering:
    def test_lockdown_checked_before_mayday(self, client):
        """suit_lockdown.is_locked() must short-circuit everything else,
        including Mayday -- a locked device shouldn't respond to any
        trigger phrase except the unlock passphrase (see command()'s
        header comment on _cmd_lockdown_locked)."""
        with mock.patch("server.LOCKDOWN_OK", True), \
             mock.patch("server.suit_lockdown") as sl:
            sl.is_locked.return_value = True
            sl.try_unlock.return_value = False
            resp = _post(client, server.MAYDAY_PHRASE)
        body = resp.get_json()
        assert body["mode"] == "lockdown"
        assert body.get("blocked") is True

    def test_mayday_checked_before_capability_map(self, client):
        """Mayday is a hard-coded phrase with no LLM call and must fire
        even if CAPABILITY_MAP would otherwise also match something in
        the same prompt."""
        with mock.patch("server.LOCKDOWN_OK", False), \
             mock.patch("server.CHECKIN_OK", False), \
             mock.patch("server.VOICE_OK", False):
            resp = _post(client, server.MAYDAY_PHRASE)
        assert resp.get_json()["mode"] == "MAYDAY"


class TestExtractedTriggerBlocks:
    """Directly exercise a sample of extracted functions -- including the
    ones with a __MERGE_NEXT__ fold-in (recon, diagnostics, cross_check,
    mac_app) -- to prove the locally-scoped setup each block needs
    (matched_recon, DIAGNOSTICS_TRIGGERS, CROSS_CHECK_TRIGGERS,
    MAC_APP_TRIGGERS) still lives inside the extracted function rather
    than having been left behind as a dangling reference to the old
    top-level statement."""

    def test_recon_matches_trigger_and_strips_it(self, app):
        with app.test_request_context(), \
             mock.patch("server.RECON_OK", True), \
             mock.patch("server.recognizance") as recon, \
             mock.patch("server.VOICE_OK", False):
            recon.scout.return_value = {"brief": "all clear, boss"}
            result = server._cmd_recon("recon on the east wing", "recon on the east wing")
            assert result is not None
            assert result.get_json()["mode"] == "recon"
        recon.scout.assert_called_once()

    def test_recon_returns_none_when_no_trigger_present(self, app):
        with app.test_request_context():
            result = server._cmd_recon("what time is it", "what time is it")
        assert result is None

    def test_diagnostics_matches_trigger(self, app):
        with app.test_request_context(), \
             mock.patch("server.friday_brain", None), \
             mock.patch("server.VOICE_OK", False), \
             mock.patch("services.system_doctor.full_check", return_value={"ok": True}):
            result = server._cmd_diagnostics("run diagnostics", "run diagnostics")
            assert result is not None
            assert result.get_json()["mode"] == "diagnostics"

    def test_diagnostics_returns_none_when_no_trigger(self, app):
        with app.test_request_context():
            result = server._cmd_diagnostics("how are you", "how are you")
        assert result is None

    def test_self_repair_run_trigger_reports_nothing_to_repair(self, app):
        with app.test_request_context(), \
             mock.patch("server.SELF_REPAIR_OK", True), \
             mock.patch("server.self_repair") as sr, \
             mock.patch("server.VOICE_OK", False):
            sr.attempt_repair.return_value = {"status": "nothing_to_repair"}
            result = server._cmd_self_repair("run a self repair", "run a self repair")
            assert result is not None
            body = result.get_json()
            assert body["mode"] == "self_repair"
            assert "nothing to repair" in body["response"].lower()
        sr.attempt_repair.assert_called_once()
        sr.confirm_repair.assert_not_called()

    def test_self_repair_confirm_trigger_applies_staged_fix(self, app):
        with app.test_request_context(), \
             mock.patch("server.SELF_REPAIR_OK", True), \
             mock.patch("server.self_repair") as sr, \
             mock.patch("server.VOICE_OK", False):
            sr.confirm_repair.return_value = {"applied": True, "target": "core/friday_memory.py"}
            result = server._cmd_self_repair("apply the fix", "apply the fix")
            assert result is not None
            body = result.get_json()
            assert body["mode"] == "self_repair"
            assert "core/friday_memory.py" in body["response"]
        sr.confirm_repair.assert_called_once()
        sr.attempt_repair.assert_not_called()

    def test_self_repair_returns_none_when_no_trigger(self, app):
        with app.test_request_context(), mock.patch("server.self_repair") as sr:
            result = server._cmd_self_repair("what time is it", "what time is it")
        assert result is None
        sr.attempt_repair.assert_not_called()
        sr.confirm_repair.assert_not_called()

    def test_cross_check_matches_trigger(self, app):
        with app.test_request_context(), mock.patch("server.cross_check") as cc:
            cc.ask_both.return_value = {
                "friday": "yes", "jarvis": "yes",
                "agreement": {"aligned": True},
            }
            result = server._cmd_cross_check("cross check this", "cross check this")
            assert result is not None
            assert result.get_json()["mode"] == "cross_check"

    def test_cross_check_returns_none_when_no_trigger(self, app):
        with app.test_request_context(), mock.patch("server.cross_check") as cc:
            result = server._cmd_cross_check("just chatting", "just chatting")
            assert result is None
            cc.ask_both.assert_not_called()

    def test_mac_app_matches_trigger(self, app):
        with app.test_request_context(), \
             mock.patch("server.TRAINING_WHEELS_OK", False), \
             mock.patch("services.mac_bridge.mac_bridge") as mb:
            mb.open_app.return_value = {"ok": True}
            result = server._cmd_mac_app("open spotify", "open spotify")
            assert result is not None
            assert result.get_json()["mode"] == "mac_bridge"

    def test_mac_app_returns_none_when_no_trigger(self, app):
        with app.test_request_context():
            result = server._cmd_mac_app("close the pod bay doors", "close the pod bay doors")
        assert result is None


class TestCommandSmokeAcrossTriggers:
    """Every trigger phrase below routes through the full dispatcher chain
    under the natural unconfigured test state (see conftest.py) -- most
    services are None/OK=False, so most _cmd_* calls fall through, but the
    call chain itself must never raise (a NameError from a lost local
    variable would surface here as a 200-with-fallback becoming a 500)."""

    PROMPTS = [
        "what's the news today",
        "translate hola",
        "remember this for later",
        "people brief on Tony",
        "who's calling",
        "call mom",
        "text dad I'm running late",
        "catch me up",
        "start focus mode",
        "log a workout",
        "journal entry: good day",
        "what's the probability we ship on time",
        "recon on the perimeter",
        "run diagnostics",
        "cross check with jarvis",
        "combat mode",
        "normal mode",
        "priority alert",
        "travel plans for Friday",
        "stop the music",
        "play some music",
        "add to calendar lunch at noon",
        "goal report",
        "add goal learn piano",
        "goal progress",
        "draft an email to the team",
        "send the email",
        "compose and send an email to Tony",
        "triage my inbox",
        "email summary",
        "take a note",
        "create a file called smoke-test: hello world",
        "open the file called smoke-test",
        "remind me to call back",
        "show my tasks",
        "add task buy milk",
        "medication schedule",
        "took my medication",
        "skip medication",
        "add medication aspirin",
        "turn on the lights",
        "open spotify",
        "home assistant status",
        "turn on the tv",
        "hello friday",
    ]

    def test_every_trigger_phrase_returns_200_with_response(self, client):
        # SECURITY_OK bypassed here on purpose: friday_security's rate
        # limiter is a session-lifetime singleton shared with every other
        # test hitting /command, so 40+ sequential posts in one test would
        # otherwise trip the same 30-req/60s limit real traffic would --
        # a real, separately-tested behavior (see test_security.py), not
        # something this dispatcher-ordering test is about.
        #
        # news_anchor is mocked too: "news"/"catch up" both reach
        # FridayNewsAnchor.morning_brief(), which does real DuckDuckGo
        # searches (see services/friday_news.py) -- up to 8 real outbound
        # requests, several seconds even when they just fail fast. That
        # made this test slow enough (~3-19s depending on the sandbox's
        # network timeout behavior) to let the background JARVIS/Groq/
        # Anthropic connectivity-check thread (core/friday_protocols.py)
        # complete its first cycle mid-suite and flip friday_protocols.
        # range_level to DARK -- which made every /command call in every
        # test running after this one short-circuit through the dark-mode
        # emergency response instead of reaching friday_brain, breaking
        # tests/test_command_memory_integration.py's mocks entirely
        # unrelated to what this test is actually checking (dispatcher
        # call order, not news content).
        with mock.patch("server.SECURITY_OK", False), \
             mock.patch("server.news_anchor") as news:
            news.morning_brief.return_value = "Nothing new, boss."
            for prompt in self.PROMPTS:
                resp = _post(client, prompt)
                assert resp.status_code == 200, f"{prompt!r} -> {resp.status_code}"
                body = resp.get_json()
                assert "response" in body, f"{prompt!r} -> missing response key"
