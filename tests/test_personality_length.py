"""tests/test_personality_length.py — brevity is the prompt's job, and
max_chars must not sever a real answer.

FRIDAY_PERSONALITY asks for one line on actions and a real answer on real
questions. core/friday_brain.py hard-truncates at the mode's max_chars,
so a cap tuned for the first kind cuts the second in half. At the old
normal-mode 400 that's ~80 words -- less than one solid technical
answer -- and the result reads as broken rather than terse, which is the
opposite of the intent.
"""
from unittest import mock

import pytest

import core.friday_brain as brain_mod
from core.friday_brain import friday_brain
from config.friday_personality import FRIDAY_PERSONALITY, FRIDAY_VOICE_MODES


# What a genuine "how should I structure the auth for this app?" answer
# looks like -- the case the cap has to survive.
REAL_ANSWER = (
    "Token-based, with the session cookie doing the work in the browser. "
    "Issue a short-lived access token on login and keep the refresh token "
    "httpOnly so script on the page can't read it. Check the token in one "
    "place, before the route runs, so a new endpoint can't forget to. "
    "Skip roles until you actually have a second kind of user, because "
    "guessing at them now means migrating them later for nothing. The one "
    "thing worth doing immediately is rotating on privilege change."
)


@pytest.fixture
def fake_llm(monkeypatch):
    calls = {}

    def _call(messages, system, model=None):
        calls["system"] = system
        return {"content": calls.get("reply", "ok"), "model": "fake", "provider": "fake"}

    monkeypatch.setattr(brain_mod, "GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(friday_brain, "_call_groq", _call)
    friday_brain._response_cache.clear()
    return calls


class TestARealAnswerSurvives:

    def test_a_technical_answer_is_not_truncated_in_normal_mode(self, fake_llm):
        fake_llm["reply"] = REAL_ANSWER
        friday_brain.set_voice_mode("normal")
        out = friday_brain.think("how should i structure the auth for this app")

        assert out["response"] == REAL_ANSWER, (
            "a real answer got cut -- normal-mode max_chars is acting as a "
            "style control instead of a runaway guard"
        )
        assert not out["response"].endswith("..."), "answer was truncated"

    def test_the_old_cap_would_have_cut_it(self):
        """Pins why this changed: 400 characters is less than one real
        answer, so the previous setting couldn't have delivered the
        'real questions get a real answer' half of the prompt."""
        assert len(REAL_ANSWER) > 400

    def test_normal_mode_is_generous_enough_to_be_a_guard(self):
        assert FRIDAY_VOICE_MODES["normal"]["max_chars"] >= 1000


class TestDeliberatelyClippedModesStayClipped:
    """combat/brief exist precisely to force terseness -- the truncation
    there is the intent, not a bug."""

    @pytest.mark.parametrize("mode,cap", [("combat", 100), ("brief", 200), ("night", 200)])
    def test_clipped_modes_keep_tight_caps(self, mode, cap):
        assert FRIDAY_VOICE_MODES[mode]["max_chars"] <= cap

    def test_combat_mode_actually_truncates(self, fake_llm):
        fake_llm["reply"] = REAL_ANSWER
        friday_brain.set_voice_mode("combat")
        out = friday_brain.think("status")
        friday_brain.set_voice_mode("normal")

        assert len(out["response"]) <= FRIDAY_VOICE_MODES["combat"]["max_chars"] + 3


class TestThePromptItself:

    def test_it_reaches_the_model(self, fake_llm):
        friday_brain.set_voice_mode("normal")
        friday_brain.think("something conversational")
        assert "You are FRIDAY" in fake_llm["system"]

    def test_it_stays_short_enough_not_to_dilute(self):
        """The previous version was ~2000 words, and the instructions that
        mattered got lost in it."""
        assert len(FRIDAY_PERSONALITY.split()) < 600

    def test_it_still_forbids_the_tells(self):
        for banned in ["Certainly", "I'd be happy to", "As an AI", "sir"]:
            assert banned in FRIDAY_PERSONALITY, f"{banned!r} is no longer ruled out"

    def test_it_asks_for_both_lengths(self):
        """The whole design: clipped on actions, complete on questions.
        Losing either half makes her annoying in a different direction."""
        p = FRIDAY_PERSONALITY.lower()
        assert "one line" in p
        assert "real answer" in p
