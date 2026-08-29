"""core/action_claims.py — catch the conversational model claiming an
action it cannot possibly have taken.

The dispatch chain in server.py runs every real capability. If none of
them claims a request, it reaches the plain conversational model, and
that path performs no actions at all -- it has no tools, touches no
service, and writes nothing. That is structural, not incidental.

So any answer from that path claiming something happened is false by
construction. It doesn't need a judgement call about whether the model
is confused; the code already knows nothing was done.

Every hallucination found on this branch was this exact shape:

  "Sending an email..."          -> nothing sent            (#16)
  "Self repair initiated, boss." -> nothing ran
  "Boss, lockdown initiated."    -> nothing locked

Each was patched where it surfaced -- a guard for unavailable services,
another for near-miss safety commands. This catches the class rather
than the instances, including the ones nobody has hit yet.

Deliberately narrow. It looks for a claim in the FIRST PERSON, PAST or
PROGRESSIVE tense, about an action FRIDAY performs. "I sent the email"
is caught. "You should send her an email", "sending email is easy", "I
can send email" and "I'll need the address before I can send it" are
not, because none of them asserts that something was done. A guard that
fires on ordinary conversation would be worse than the bug: it would
make her refuse to talk about her own capabilities.
"""
import re

# Verbs for things FRIDAY actually does somewhere in the codebase. A
# claim only matters if it's about a real capability -- "I opened the
# door" isn't something she can do or claim to have done.
_ACTION_VERBS = (
    "sent|emailed|added|created|scheduled|booked|logged|saved|stored|"
    "deleted|removed|cancelled|canceled|updated|set|started|initiated|"
    "activated|enabled|disabled|locked|unlocked|ran|executed|played|"
    "paused|texted|called|posted|filed|recorded|noted|reminded|"
    "triggered|deployed|repaired|fixed|applied"
)

# "I sent", "I've sent", "I have sent", "I already sent"
_PAST_CLAIM = re.compile(
    rf"\b(?:i|i've|i have|i already|i just)\s+(?:just\s+|already\s+)?(?:{_ACTION_VERBS})\b",
    re.I,
)

# "Sending the email now", "Initiating lockdown" -- progressive claims
# that read as "this is happening" when nothing is.
_PROGRESSIVE_CLAIM = re.compile(
    r"\b(?:sending|adding|creating|scheduling|booking|logging|saving|"
    r"storing|deleting|removing|cancelling|canceling|updating|starting|"
    r"initiating|activating|locking|unlocking|running|executing|playing|"
    r"texting|calling|posting|filing|recording|triggering|deploying|"
    r"repairing|applying)\b\s+(?:the|your|a|an|it|that|my)\b",
    re.I,
)

# Bare status assertions, in the two shapes the model actually produces.
# Both had to tolerate a vocative, because that's how she talks -- the
# real cases were "Boss, lockdown initiated." and "Self repair
# initiated, boss.", and a pattern keyed only to sentence boundaries
# missed both.

# (a) The sentence opens with the action itself, no subject to soften
#     it: "Done.", "Added it to your calendar, boss.", "Sent."
_LEADING_ACTION = re.compile(
    rf"(?:^|[.!?]\s+)(?:boss,\s*)?(?:done|{_ACTION_VERBS})\b",
    re.I,
)

# (b) The action lands at the end as a report on some object:
#     "Self repair initiated, boss.", "Boss, lockdown initiated."
#     Bounded to a few words so it stays a short status line rather than
#     matching a verb buried anywhere in a long sentence.
_TRAILING_ACTION = re.compile(
    rf"(?:^|[.!?,]\s*|—\s*)(?:\w+\s+){{1,3}}(?:{_ACTION_VERBS})\s*(?:[.!]|,\s*boss\b)",
    re.I,
)

# Said while explicitly NOT doing it -- these must not trip the guard.
_NEGATED = re.compile(
    r"\b(?:not|never|didn't|did not|haven't|have not|won't|will not|"
    r"can't|cannot|couldn't|could not|unable)\b",
    re.I,
)


# Questions that ask how a capability WORKS rather than asking for it to
# be used. An answer to one of these describes the mechanism, and
# describing a mechanism in the first person is indistinguishable, at the
# sentence level, from claiming to have just done it:
#
#   "I'm adding it straight to your calendar"      explanation
#   "I've set it up so you can just say the date"  explanation
#
# Both were flagged, and "how does the calendar thing work" came back as
# "I didn't actually do anything there, boss" -- a confusing non-answer to
# a question that asked for one, and a worse failure than the
# hallucination the guard exists to catch, because it destroys a correct
# reply.
#
# Deliberately narrow. "can you send an email to jane" is a request
# wearing a question mark and must still be guarded, so it is not here.
# Only openers that cannot be an instruction qualify.
_EXPLANATORY = re.compile(
    r"^\s*(how (do|does|did|would|can) (you|it|that|the)"
    r"|what happens when"
    r"|what does .{0,40} do\b"
    r"|explain\b"
    r"|tell me about\b"
    r"|how's .{0,30} work)",
    re.I,
)


def is_explanatory(prompt: str) -> bool:
    return bool(prompt) and bool(_EXPLANATORY.search(prompt))


def claims_action(text: str, prompt: str = "") -> str | None:
    """Return the matched claim if `text` asserts FRIDAY did something,
    else None.

    Negation is checked first and wins outright: "I have not locked
    anything down" and "I couldn't send that" are the honest answers this
    branch added, and flagging them would be exactly backwards.

    `prompt` is what was asked. When it asks how something works, a
    first-person description of the mechanism is an answer rather than a
    claim about this turn -- see _EXPLANATORY. Passing it is optional so
    existing callers keep working, but the guard is noticeably blunter
    without it."""
    if not text:
        return None
    if _NEGATED.search(text):
        return None
    if is_explanatory(prompt):
        return None
    for pattern in (_PAST_CLAIM, _PROGRESSIVE_CLAIM,
                    _LEADING_ACTION, _TRAILING_ACTION):
        m = pattern.search(text)
        if m:
            return m.group(0).strip()
    return None
