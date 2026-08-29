"""core/confidence.py — how FRIDAY knows how much she knows.

The tempting implementation is to ask the model how confident it is.
That does not work: a model's self-reported certainty is highest exactly
where it is confabulating, because fluent invention and recall feel the
same from the inside. Asking would produce a number that looks like
calibration and isn't.

So confidence here is derived from *provenance* -- where the answer came
from -- which FRIDAY already knows for certain and which does not require
the model's cooperation:

    grounded    a real service produced it. The weather API answered, the
                calendar was read, the inbox was fetched. This is data.

    recalled    it came out of her own memory stores -- something the
                boss told her, or she wrote down.

    inferred    the conversational model answered from its own training,
                with no service and no memory behind it. It may well be
                right. It is not something she looked up, and right now
                it is presented in exactly the same voice as a weather
                report.

    unverified  she acted, and the outcome check came back "unknown"
                (see core/outcome_verify.py).

The last mile is deliberately restrained. config/friday_personality.py's
one rule is that actions get one line, and hedging every reply would
break the voice it spends 374 words establishing -- as well as training
the boss to skim past qualifiers, which costs more than it buys on the
day one is real.

So the level is always attached to the response for the HUD to show, and
the spoken text only changes for `inferred` answers to questions that
sound like they have a checkable answer. "What's the capital of Peru"
gets a note. "What do you think" does not, because there was never data
to be missing.
"""
import re

GROUNDED = "grounded"
RECALLED = "recalled"
INFERRED = "inferred"
UNVERIFIED = "unverified"

# Modes from the conversational fallback -- the model talking, with no
# service behind it. Every other mode in server.py is a handler that
# actually touched something.
_MODEL_ONLY_MODES = {"friday", "friday-coverage", "emergency"}

# A question whose answer is a fact about the world, so "I didn't look
# this up" is worth saying. Matched at the start, because "what is the
# tallest mountain" is a lookup and "tell me what you think about
# mountains" is not.
_FACTUAL_OPENERS = re.compile(
    r"^(what|when|where|who|which|how many|how much|how long|how far|how old)\b",
    re.I,
)

# Asking about herself, her state, or the conversation is not a lookup --
# she is the authority on those, and a "not looked up" note would be
# both wrong and irritating.
_ABOUT_HERSELF = re.compile(
    r"\b(you|your|yourself|we|our|us|i|me|my)\b", re.I,
)

_LAST = {"level": "", "prompt": "", "response": "", "mode": ""}


def assess(mode: str, response: str = "", used_memory: bool = False,
           verified: str = "") -> str:
    """The provenance of one answer. Cheap and side-effect free."""
    if verified == "unknown":
        return UNVERIFIED
    if mode not in _MODEL_ONLY_MODES:
        return GROUNDED
    return RECALLED if used_memory else INFERRED


def remember(level: str, prompt: str, response: str, mode: str):
    """Hold the last answer's provenance so "are you sure?" has something
    真 to answer from. In-memory and single-slot, like _pending_calendar_add
    -- one process, one last answer."""
    _LAST.update(level=level, prompt=prompt[:300],
                 response=response[:300], mode=mode)


def last() -> dict:
    return dict(_LAST)


_SOURCE = {
    GROUNDED: "I pulled that from {source} just now, so it's current.",
    RECALLED: "That came from what you've told me, not from anything I looked up.",
    INFERRED: "That one's from memory, boss — I didn't look it up. Worth "
              "checking if it matters.",
    UNVERIFIED: "I did it, but the confirmation didn't come back, so I "
                "can't swear it landed.",
}


def explain(entry: dict) -> str:
    """How she answers "are you sure?" -- one line, in her own voice.

    The value is in the honest distinction: "I read that off your
    calendar" and "I think that's right" arrive in identical language
    otherwise, and only one of them is checkable.
    """
    level = entry.get("level")
    if not level:
        return "Nothing to check back on yet, boss."
    if level == GROUNDED:
        return _SOURCE[GROUNDED].format(source=_source_name(entry.get("mode", "")))
    return _SOURCE.get(level, "Not sure how I got that one, boss.")


def _source_name(mode: str) -> str:
    return {
        "weather": "the weather service", "news": "the news feed",
        "email": "your inbox", "email_triage": "your inbox",
        "calendar": "your calendar", "task_show": "your task list",
        "self_audit": "my own logs",
    }.get(mode, "a live source")
