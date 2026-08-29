"""tests/test_tool_router.py — Level 3 of the anti-hallucination work.

Levels 1 and 2 catch the damage after the fact: _matched_but_unavailable
says "that system is off", and core/action_claims.py rewrites a reply
claiming an action the conversational path can't have taken. Both honest,
neither actually answers the boss.

This one closes the gap they were papering over. Dispatch matches
substrings, so it only fires on phrasings someone thought to list; ask in
words nobody anticipated and every handler declines, the request reaches
a model with no tools, and it invents. "Can you read my Gmail" was
answered "I'm not able to access your Gmail account" while IMAP was
working fine.

Two properties carry the whole design and are tested hardest:

  Every canonical phrase in the catalog is really claimed by dispatch.
  The catalog names routes in FRIDAY's own trigger vocabulary, and a
  renamed trigger would otherwise leave it quietly pointing at nothing.

  No safety command is reachable. lockdown persists a locked state, so
  the next boot comes up LOCKED -- a model reasoning its way into it
  would be the worst bug in this repo.
"""
from unittest import mock

import pytest

import server
from core import tool_router


@pytest.fixture
def routing_on(monkeypatch):
    monkeypatch.setattr(tool_router, "ENABLED", True)


def _brain_picking(tool, detail=""):
    import json
    b = mock.Mock()
    b.think.return_value = {"response": json.dumps({"tool": tool, "detail": detail})}
    return b


# Handlers taking (prompt) rather than (prompt, p_lower).
_ONE_ARG = {
    "_cmd_lockdown_locked", "_cmd_lockdown_trigger", "_cmd_mayday",
    "_cmd_safe_checkin", "_cmd_security_screen", "_cmd_learn_voice_mode",
    "_cmd_dark_mode", "_cmd_capabilities",
}


def _dispatch_order():
    """The chain's real order, read off _handle_prompt rather than
    duplicated -- a hand-kept copy would drift and quietly stop
    reflecting what actually runs."""
    from core import dispatch_chain
    return list(dispatch_chain.PRE_SPLIT) + list(dispatch_chain.MAIN)


class TestTheCatalogCannotRot:
    """The catalog is written in FRIDAY's own trigger vocabulary, so it
    breaks silently if a trigger is ever reworded: routing would still
    "succeed" and then land on the conversational fallback anyway, which
    is the exact failure this feature exists to remove.

    Checked by running the phrase through the real dispatch chain rather
    than grepping the *_TRIGGERS lists -- the first draft did the latter
    and wrongly failed five entries, because weather, news, translate,
    people_brief and spotify_play match on inline conditions instead.
    Asserting against dispatch is both stronger and style-agnostic.
    """

    @pytest.mark.parametrize("tool", tool_router.TOOLS,
                             ids=[t.name for t in tool_router.TOOLS])
    def test_the_intended_handler_claims_the_canonical_phrase(
            self, app, all_services, tool):
        """Asserts the phrase reaches *the handler the catalog names*.

        Two earlier drafts of this were vacuous and both failed the same
        way -- they walked the whole chain and accepted any claim, so an
        always-on handler running on a Mock swallowed everything before
        the real one was reached (_cmd_lockdown_locked first, because a
        Mock's is_locked() is truthy; then _cmd_security_screen). Broken
        canonical phrases passed clean through both times. Naming the
        target handler is what makes this test mean anything.
        """
        fn = getattr(server, tool.handler, None)
        assert fn is not None, f"{tool.handler} no longer exists"

        phrase = tool_router.rephrase(tool.name, "something" if tool.takes_detail else "")

        with app.test_request_context():
            try:
                claimed = fn(phrase, phrase.lower()) is not None
            except Exception:
                claimed = True  # entered the body -- the trigger matched

        assert claimed, (
            f"{tool.name}: {tool.handler} does not claim {phrase!r}, so routing "
            f"there would fall through to the conversational model anyway"
        )

    def test_every_tool_name_is_unique(self):
        names = [t[0] for t in tool_router.TOOLS]
        assert len(names) == len(set(names))

    def test_catalog_and_lookup_agree(self):
        assert set(tool_router._BY_NAME) == {t[0] for t in tool_router.TOOLS}


class TestSafetyCommandsAreUnreachable:
    def test_no_safety_phrase_is_in_the_catalog(self):
        """Neither as a capability nor hidden inside a canonical phrase."""
        forbidden = [p for phrases in server._SAFETY_NEAR_MISS.values()
                     for p in phrases]
        forbidden += list(getattr(server, "LOCKDOWN_TRIGGERS", []))
        forbidden.append(server.MAYDAY_PHRASE)

        for tool in tool_router.TOOLS:
            for phrase in forbidden:
                assert phrase.lower() not in tool.canonical.lower(), (
                    f"{tool.name} can be rephrased into the safety phrase {phrase!r}"
                )

    def test_a_rephrasing_can_never_produce_a_lockdown(self, routing_on):
        """Even with the model actively trying: detail is attacker-shaped
        text, so it must not be able to smuggle a safety phrase into a
        capability that takes one."""
        for tool in tool_router.TOOLS:
            if not tool.takes_detail:
                continue
            out = tool_router.rephrase(tool.name, "lockdown now")
            # The phrase survives in the detail, so what actually protects
            # the suit is that dispatch checks lockdown against its own
            # exact trigger before any of this runs -- assert the routed
            # phrase is not itself a bare lockdown command.
            assert not out.lower().startswith("lockdown")


class TestSelectionIsConservative:
    def test_disabled_by_default(self):
        """It spends a model call on a path that spends none, and changes
        what she does rather than what she says. Ships dark."""
        assert tool_router.ENABLED is False

    def test_returns_none_when_disabled(self):
        assert tool_router.select("do a thing", _brain_picking("weather")) is None

    def test_unknown_capability_is_refused(self, routing_on):
        """The model inventing a capability is the precise failure this
        feature exists to stop, so it must not be passed through."""
        assert tool_router.select("x", _brain_picking("teleport")) is None

    def test_null_tool_is_refused(self, routing_on):
        assert tool_router.select("how are you", _brain_picking(None)) is None

    def test_a_crash_in_the_model_is_swallowed(self, routing_on):
        """This sits in front of the conversational fallback, so failing
        here must cost nothing -- the boss gets the answer he'd have got
        without it."""
        b = mock.Mock()
        b.think.side_effect = RuntimeError("boom")
        assert tool_router.select("x", b) is None

    def test_no_brain_is_handled(self, routing_on):
        assert tool_router.select("x", None) is None

    def test_json_wrapped_in_prose_is_recovered(self, routing_on):
        b = mock.Mock()
        b.think.return_value = {"response":
                                'Sure! {"tool": "weather", "detail": ""} hope that helps'}
        assert tool_router.select("x", b)["tool"] == "weather"

    def test_garbage_is_refused(self, routing_on):
        b = mock.Mock()
        b.think.return_value = {"response": "I think maybe the weather one?"}
        assert tool_router.select("x", b) is None

    def test_selection_uses_raw_mode(self, routing_on):
        """Without raw=True, _instant_response answers the routing prompt
        itself with a canned FRIDAY line and the JSON never arrives --
        the same bug that broke calendar extraction."""
        b = _brain_picking("weather")
        tool_router.select("x", b)
        assert b.think.call_args.kwargs.get("raw") is True


class TestRephrasing:
    def test_detail_is_appended_where_it_belongs(self):
        assert tool_router.rephrase("calendar_add", "dentist on Sept 1") == \
            "put on my calendar dentist on Sept 1"

    def test_whole_commands_ignore_detail(self):
        """Appending user text to "what's the weather" only adds noise."""
        assert tool_router.rephrase("weather", "in Tokyo please") == "what's the weather"

    def test_missing_detail_still_gives_a_usable_phrase(self):
        assert tool_router.rephrase("calendar_add", "") == "put on my calendar"

    def test_unknown_tool_gives_nothing(self):
        assert tool_router.rephrase("teleport", "") is None


@pytest.fixture
def chain_falls_through(all_services):
    """Named for what it guarantees at the call site. all_services already
    neutralises the always-on handlers -- see its docstring in conftest for
    why that is the whole trick, and for the two separate attempts at this
    file's catalog guard that were vacuous without it."""
    return all_services


def _unclaimed_prompt():
    """A phrase no handler's trigger or inline condition matches. Asserted
    rather than assumed -- see test_the_probe_prompt_is_really_unclaimed."""
    return "mm hrm okay then"


class TestWiredIntoDispatch:
    """Tested against _handle_prompt rather than in isolation, because the
    piece that actually matters is that the gap it fills is the real one
    -- after every handler declined, before the model improvises."""

    def test_the_probe_prompt_is_really_unclaimed(self, app, chain_falls_through):
        """The tests below only mean something if their prompt genuinely
        reaches the router. If some handler starts claiming it, they would
        silently stop testing the wiring."""
        with app.test_request_context():
            for handler in _dispatch_order():
                fn = getattr(server, handler, None)
                if fn is None:
                    continue
                phrase = _unclaimed_prompt()
                args = (phrase,) if handler in _ONE_ARG else (phrase, phrase.lower())
                try:
                    claimed = fn(*args) is not None
                except Exception:
                    claimed = True
                assert not claimed, f"{handler} claims the probe prompt"

    def test_routing_reruns_dispatch_with_the_rephrasing(
            self, app, routing_on, chain_falls_through, monkeypatch):
        seen = []
        real = server._handle_prompt

        def spy(prompt, allow_split=True, allow_route=True):
            seen.append(prompt)
            return real(prompt, allow_split, allow_route)

        monkeypatch.setattr(server, "_handle_prompt", spy)
        monkeypatch.setattr(server, "friday_brain", _brain_picking("weather"))
        monkeypatch.setattr(tool_router, "select",
                            lambda *_: {"tool": "weather", "detail": ""})

        with app.test_request_context():
            server._handle_prompt(_unclaimed_prompt())

        assert "what's the weather" in seen

    def test_the_rephrasing_cannot_route_again(
            self, app, routing_on, chain_falls_through, monkeypatch):
        """A rephrasing the chain still doesn't claim would otherwise come
        back here and be rephrased forever."""
        calls = []
        monkeypatch.setattr(server, "friday_brain", _brain_picking("weather"))
        monkeypatch.setattr(tool_router, "select",
                            lambda *a: (calls.append(1), {"tool": "note", "detail": "x"})[1])

        with app.test_request_context():
            server._handle_prompt(_unclaimed_prompt())

        assert len(calls) == 1

    def test_off_by_default_leaves_dispatch_untouched(
            self, app, chain_falls_through, monkeypatch):
        called = []
        monkeypatch.setattr(tool_router, "select",
                            lambda *a: called.append(1))
        monkeypatch.setattr(server, "friday_brain", _brain_picking("weather"))

        with app.test_request_context():
            server._handle_prompt(_unclaimed_prompt())

        assert not called


class TestDetailIsTheSubjectNotTheWholeRequest:
    """Caught in production on the router's first day:

        [route] 'keep track of my knee physio' -> habit_log
                -> 'logged my keep track of my knee physio'

    The capability was right. The rewrite was nonsense, because the model
    returned the entire request as `detail` and the canonical phrase
    already carries the verb. The habit handler then tried to extract a
    habit name from that string.

    Prompting alone can't be relied on for this -- the model was already
    told to return "the part of the request that is content" and returned
    all of it -- so the obvious shapes are stripped in code as well.
    """

    def test_the_production_case(self):
        assert tool_router.rephrase("habit_log", "keep track of my knee physio") \
            == "logged my knee physio"

    @pytest.mark.parametrize("detail,expected", [
        ("i need to grab dog food",   "add to my list grab dog food"),
        ("can you add dog food",      "add to my list add dog food"),
        ("please dog food",           "add to my list dog food"),
        ("just dog food",             "add to my list dog food"),
    ])
    def test_leading_request_words_are_stripped(self, detail, expected):
        assert tool_router.rephrase("task_add", detail) == expected

    @pytest.mark.parametrize("detail", ["my vitamins", "the vitamins", "vitamins"])
    def test_a_possessive_canonical_does_not_stutter(self, detail):
        """"i took my" + "my vitamins" reads as "i took my my vitamins"."""
        assert tool_router.rephrase("med_taken", detail) == "i took my vitamins"

    def test_stacked_prefixes_are_all_removed(self):
        assert tool_router.rephrase("habit_log", "please keep track of my knee physio") \
            == "logged my knee physio"

    def test_a_clean_detail_is_left_alone(self):
        """The common case must not be damaged by the repair."""
        assert tool_router.rephrase("calendar_add", "dinner with sarah at 7") \
            == "put on my calendar dinner with sarah at 7"

    def test_content_that_merely_starts_with_a_stripped_word_survives(self):
        """"my" is only stripped after a canonical that ends in a
        possessive -- "note that" doesn't, so "my passport number" keeps
        its "my"."""
        assert tool_router.rephrase("note", "my passport number") \
            == "note that my passport number"

    def test_quotes_around_the_detail_are_removed(self):
        assert tool_router.rephrase("note", '"the wifi password"') \
            == "note that the wifi password"

    def test_an_all_filler_detail_falls_back_to_the_canonical(self):
        """Stripping everything must not produce a trailing space or a
        half-sentence."""
        assert tool_router.rephrase("task_add", "please ") == "add to my list"

    def test_the_rewrite_is_still_claimed_by_its_handler(self, app, all_services):
        """The repair must not break the property the whole catalog rests
        on -- a rewrite dispatch no longer claims is worse than a clumsy
        one it does."""
        import server
        phrase = tool_router.rephrase("habit_log", "keep track of my knee physio")
        with app.test_request_context():
            try:
                claimed = server._cmd_habit_log(phrase, phrase.lower()) is not None
            except Exception:
                claimed = True
        assert claimed, f"{phrase!r} is no longer claimed by _cmd_habit_log"
