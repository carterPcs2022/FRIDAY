"""tests/test_dispatch_chain.py — the order is now asserted, not emergent.

The 59-branch if-chain in server.py has been replaced by a declared list.
That is only an improvement if the order came through unchanged, because
the order IS the behaviour: dispatch returns on its first match, so
moving one handler earlier silently steals every phrase it happens to
match from everything below it.

Every dispatch bug on this branch was that. Spotify's "put on" swallowed
"put on my calendar". The reminder handler took "remind me to take my
pills" before the medication tracker saw it.

GOLDEN below was captured from server.py by script immediately before the
refactor, and is the literal sequence the inline chain executed in. It is
not derived from the registry, so it can disagree with it -- which is the
entire point.
"""
import pytest

from core import dispatch_chain


GOLDEN_PRE_SPLIT = [
    "_cmd_lockdown_locked",
    "_cmd_lockdown_trigger",
    "_cmd_mayday",
    "_cmd_safety_near_miss",
    "_cmd_safe_checkin",
    "_cmd_security_screen",
]

GOLDEN_MAIN = [
    "_cmd_learn_voice_mode",
    "_cmd_dark_mode",
    "_cmd_capabilities",
    "_cmd_weather",
    "_cmd_news",
    "_cmd_translate",
    "_cmd_code_review",
    "_cmd_remember_this",
    "_cmd_people_brief",
    "_cmd_caller_id",
    "_cmd_call_initiate",
    "_cmd_sms_send",
    "_cmd_confidence_query",
    "_cmd_self_audit",
    "_cmd_catchup",
    "_cmd_focus",
    "_cmd_habit_log",
    "_cmd_journal",
    "_cmd_probability",
    "_cmd_recon",
    "_cmd_diagnostics",
    "_cmd_self_repair",
    "_cmd_cross_check",
    "_cmd_combat_mode",
    "_cmd_normal_mode",
    "_cmd_priority",
    "_cmd_travel",
    "_cmd_spotify_stop",
    "_cmd_spotify_play",
    "_cmd_calendar_add",
    "_cmd_goal_report",
    "_cmd_goal_add",
    "_cmd_goal_progress",
    "_cmd_email_draft",
    "_cmd_email_send",
    "_cmd_email_compose_send",
    "_cmd_email_triage",
    "_cmd_email_summary",
    "_cmd_note",
    "_cmd_create_file",
    "_cmd_file_recall",
    "_cmd_reminder",
    "_cmd_task_show",
    "_cmd_task_add",
    "_cmd_med_schedule",
    "_cmd_med_taken",
    "_cmd_med_skip",
    "_cmd_med_add",
    "_cmd_homekit",
    "_cmd_mac_app",
    "_cmd_ha_status",
    "_cmd_ha_toggle",
    "_cmd_jarvis_proxy",
]


class TestTheOrderSurvivedTheRefactor:
    def test_pre_split_order_is_unchanged(self):
        assert dispatch_chain.PRE_SPLIT == GOLDEN_PRE_SPLIT

    def test_main_order_is_unchanged(self):
        assert dispatch_chain.MAIN == GOLDEN_MAIN

    def test_nothing_was_dropped(self):
        assert len(dispatch_chain.PRE_SPLIT) + len(dispatch_chain.MAIN) == 59

    def test_no_handler_is_registered_twice(self):
        """A handler in both chains would run against the whole message
        and then again against every segment -- so a multi-command
        message would fire it repeatedly."""
        both = list(dispatch_chain.PRE_SPLIT) + list(dispatch_chain.MAIN)
        assert len(both) == len(set(both))


class TestTheSafetyBoundary:
    """PRE_SPLIT vs MAIN is the one place in the chain where position is
    a safety property rather than a preference."""

    def test_lockdown_and_mayday_run_before_splitting(self):
        """They are about the message as a whole. Below the split, a
        multi-command message could smuggle one past them in a fragment
        -- or fire one six times because six segments each contained the
        word."""
        for handler in ("_cmd_lockdown_locked", "_cmd_lockdown_trigger",
                        "_cmd_mayday"):
            assert handler in dispatch_chain.PRE_SPLIT

    def test_lockdown_is_checked_before_everything(self):
        """While locked, the only thing this system does with any message
        is compare it to the passphrase -- so nothing may run first."""
        assert dispatch_chain.PRE_SPLIT[0] == "_cmd_lockdown_locked"

    def test_the_near_miss_guard_runs_after_the_real_handlers(self):
        """It exists to catch phrases that only *nearly* match, so an
        exact trigger must have been claimed and returned already."""
        pre = dispatch_chain.PRE_SPLIT
        assert pre.index("_cmd_safety_near_miss") > pre.index("_cmd_lockdown_trigger")
        assert pre.index("_cmd_safety_near_miss") > pre.index("_cmd_mayday")

    def test_no_ordinary_capability_sits_in_the_pre_split_chain(self):
        """Anything here runs against the unsplit message, so a handler
        added by mistake would stop multi-command working for it."""
        allowed = {"_cmd_lockdown_locked", "_cmd_lockdown_trigger", "_cmd_mayday",
                   "_cmd_safety_near_miss", "_cmd_safe_checkin", "_cmd_security_screen"}
        assert set(dispatch_chain.PRE_SPLIT) == allowed


class TestResolution:
    def test_every_declared_handler_exists(self):
        """Resolution happens at boot and raises, so this failing means
        server.py wouldn't even start -- but the message is clearer
        here."""
        import server
        for name in list(dispatch_chain.PRE_SPLIT) + list(dispatch_chain.MAIN):
            assert getattr(server, name, None) is not None, f"{name} doesn't exist"

    def test_a_bad_name_fails_loudly(self):
        """Silently dropping a capability from the chain is the failure
        nobody notices -- 44 handlers went untested for months precisely
        because nothing complained when they weren't reached."""
        import server
        with pytest.raises(RuntimeError, match="doesn't exist"):
            server._resolve_chain(["_cmd_does_not_exist"])

    def test_arity_is_read_from_the_signature(self):
        """Not from a hand-maintained list. A handler gaining a parameter
        would otherwise start being called wrongly with nothing failing
        on the list itself."""
        import server
        assert server._takes_p_lower(server._cmd_weather) is True
        assert server._takes_p_lower(server._cmd_mayday) is False

    def test_the_resolved_chains_match_the_declared_ones(self):
        """The loop runs over the resolved callables, so a mismatch here
        would mean the declared order isn't the one executing."""
        import server
        assert [f.__name__ for f in server._PRE_SPLIT_CHAIN] == dispatch_chain.PRE_SPLIT
        assert [f.__name__ for f in server._MAIN_CHAIN] == dispatch_chain.MAIN


class TestFirstMatchWins:
    def test_the_first_handler_to_answer_ends_the_chain(self):
        calls = []
        def a(p, pl): calls.append("a"); return None
        def b(p, pl): calls.append("b"); return "claimed"
        def c(p, pl): calls.append("c"); return "late"

        import server
        assert server._run_chain([a, b, c], "x", "x") == "claimed"
        assert calls == ["a", "b"]

    def test_an_empty_chain_returns_none(self):
        import server
        assert server._run_chain([], "x", "x") is None

    def test_one_arg_handlers_are_called_with_one_arg(self):
        import server
        seen = []
        def only_prompt(p): seen.append(p); return None
        server._run_chain([only_prompt], "hello", "hello")
        assert seen == ["hello"]
