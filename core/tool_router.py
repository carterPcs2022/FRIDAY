"""core/tool_router.py — last resort before FRIDAY improvises: ask the
model which of her real capabilities a request wanted, and re-dispatch it
in words the existing chain recognises.

Levels 1 and 2 of the anti-hallucination work both catch the damage after
it happens. _matched_but_unavailable() says "that system is off" once a
trigger matched but its handler declined, and core/action_claims.py
rewrites a reply that claimed an action the conversational path cannot
have taken. Both are honest. Neither actually answers the boss.

The failure underneath them is narrower than "the model hallucinates":
dispatch is 56 handlers matching substrings, so it only fires on
phrasings someone thought to list. Ask in words nobody anticipated and
every handler declines, the request reaches a model with no tools and no
idea what FRIDAY can do, and it invents in whichever direction sounds
plausible. That is how "Can you read my Gmail" got answered "I'm not able
to access your Gmail account" while IMAP was working fine.

So this runs in that gap only -- after every handler has declined and
before the conversational model gets it. Nothing that works today
changes: a request the chain already claims never reaches here.

The design decision worth stating: this does NOT invoke handlers. It
picks a capability and rewrites the request into that capability's own
canonical trigger phrase, then hands it back to the same dispatch chain
everything else goes through. A second invocation path would mean 56
handlers reachable two ways, drifting apart, with the safety ordering in
_handle_prompt (lockdown checked before everything, near-miss guards,
pending-reply state) applying to only one of them. Rewrite-and-redispatch
keeps exactly one way in.

What it will not route to, and why:

  Safety commands -- lockdown, mayday, the near-miss guards. They are
  deliberately exact-phrase: suit_lockdown persists a locked state, so
  the next boot comes up LOCKED, and a paraphrase reaching it would be
  the single worst bug in this repo. A model must never be able to
  reason its way into one. They stay reachable only by saying them.

  Anything already gated behind a confirmation stays gated, because the
  rewrite goes through normal dispatch and hits the same pending-reply
  state everything else does.
"""
import json
import logging
import os
import re
from typing import NamedTuple


class Tool(NamedTuple):
    name: str          # what the model returns
    describes: str     # what the model reads
    canonical: str     # a phrase from the handler's own trigger list
    takes_detail: bool # whether the rest of the request is content
    handler: str       # the _cmd_* that must claim `canonical`

# One line per capability. `canonical` is a phrase from that handler's
# own trigger list -- tests/test_tool_router.py asserts every one of them
# is really claimed by dispatch, so this catalog cannot rot into naming
# routes that no longer exist.
#
# `takes_detail` marks the ones where the rest of the request carries
# content (what to add, who to text). The others are whole commands and
# appending user text to them only adds noise.
TOOLS = [
    Tool("weather",       "the weather or forecast",                    "what's the weather",   False, "_cmd_weather"),
    Tool("news",          "news or headlines",                          "give me the news",     False, "_cmd_news"),
    Tool("email_summary", "reading, checking or summarising the inbox", "check my email",       False, "_cmd_email_summary"),
    Tool("email_triage",  "sorting or prioritising the inbox",          "triage my inbox",      False, "_cmd_email_triage"),
    Tool("email_draft",   "writing a reply to an email",                "draft a reply to",     True,  "_cmd_email_draft"),
    Tool("calendar_add",  "putting an event on the calendar",           "put on my calendar",   True,  "_cmd_calendar_add"),
    Tool("reminder",      "setting a reminder for later",               "remind me",            True,  "_cmd_reminder"),
    Tool("task_add",      "adding something to the to-do list",         "add to my list",       True,  "_cmd_task_add"),
    Tool("task_show",     "showing the to-do list",                     "what's on my list",    False, "_cmd_task_show"),
    Tool("note",          "writing down a note",                        "note that",            True,  "_cmd_note"),
    Tool("journal",       "a journal or diary entry about today",       "log today:",           True,  "_cmd_journal"),
    Tool("goal_add",      "adding a long-term goal",                    "add goal",             True,  "_cmd_goal_add"),
    Tool("goal_report",   "reviewing goals",                            "what are my goals",    False, "_cmd_goal_report"),
    Tool("habit_log",     "recording a habit or workout",               "logged my",            True,  "_cmd_habit_log"),
    Tool("med_schedule",  "the medication schedule",                    "my medicine schedule", False, "_cmd_med_schedule"),
    Tool("med_taken",     "recording that medication was taken",        "i took my",            True,  "_cmd_med_taken"),
    Tool("spotify_play",  "playing music",                              "play",                 True,  "_cmd_spotify_play"),
    Tool("spotify_stop",  "stopping music",                             "stop playing",         False, "_cmd_spotify_stop"),
    Tool("translate",     "translating text",                           "translate",            True,  "_cmd_translate"),
    Tool("catchup",       "a summary of what was missed",               "what did i miss",      False, "_cmd_catchup"),
    Tool("focus",         "starting a focus session",                   "focus mode",           False, "_cmd_focus"),
    Tool("travel",        "travel information for a destination",       "traveling to",         True,  "_cmd_travel"),
    Tool("people_brief",  "background on a person",                     "people brief on",      True,  "_cmd_people_brief"),
    Tool("sms_send",      "sending a text message",                     "text me",              True,  "_cmd_sms_send"),
]

_BY_NAME = {t.name: t for t in TOOLS}

# Off unless switched on. This spends an extra model call on a path that
# currently spends none, and it changes what FRIDAY *does* rather than
# just what she says -- so it ships dark and gets turned on deliberately.
ENABLED = os.getenv("FRIDAY_TOOL_ROUTER", "").strip().lower() in ("1", "true", "yes", "on")

_SYSTEM = """You route a request to one of an assistant's capabilities.

Reply with JSON only: {"tool": "<name>", "detail": "<subject only>"}
If no capability fits, reply {"tool": null}.

`detail` is the SUBJECT of the action and nothing else. Strip every verb,
request and politeness word -- they are already carried by the capability
you picked, and repeating them produces nonsense when the request is
rebuilt. It is usually two or three words.

  "keep track of my knee physio"        -> {"tool": "habit_log", "detail": "knee physio"}
  "pencil in dinner with sarah at 7"    -> {"tool": "calendar_add", "detail": "dinner with sarah at 7"}
  "don't let that wifi password vanish" -> {"tool": "note", "detail": "the wifi password"}
  "nudge me in twenty minutes"          -> {"tool": "reminder", "detail": "in twenty minutes"}
  "i should grab dog food"              -> {"tool": "task_add", "detail": "dog food"}

Never echo the whole request back as `detail`.

Rules:
- Pick a capability ONLY if the request is clearly asking for that thing to be done.
- A question about a capability is not a request to use it. "Can you read email?" is {"tool": null}.
- A statement describing the boss's own situation, feelings, or something
  he still owes someone is not a request, even when it shares words with a
  capability's description. "I owe Sarah a reply" is talking about an
  obligation, not asking you to draft one -- {"tool": null}. Contrast with
  "draft a reply to Sarah", which is an instruction.
- Chat, opinions, greetings and general questions are {"tool": null}.
- Never guess. {"tool": null} is always a safe answer and is usually right."""

# Leading verbs and politeness the model leaves on `detail` despite being
# told not to. Stripped because the canonical phrase already supplies the
# verb, and concatenating both produced, in production:
#
#   'keep track of my knee physio' -> 'logged my keep track of my knee physio'
#
# which the habit handler then tried to extract a habit name from.
# Each alternative ends in (?:\s+|\Z) so a detail that is *only* filler
# ("please") strips to empty rather than surviving for want of a trailing
# space -- rephrase() then falls back to the bare canonical phrase.
_DETAIL_PREFIX = re.compile(
    r"^\s*(?:(?:please|just|kindly"
    r"|can you|could you|would you|will you"
    r"|i\s+(?:need|want|should|have)\s+to"
    r"|keep track of|make sure (?:to|i)"
    r"|don'?t (?:let me )?forget(?: to| about)?"
    r"|remember to|remind me to|help me|go ahead and)(?:\s+|\Z))+",
    re.I,
)

_LEADING_POSSESSIVE = re.compile(r"^\s*(?:my|the|a|an|that|this)\s+", re.I)


def _clean_detail(detail: str, canonical: str, prompt: str) -> str:
    """Strip what the canonical phrase already says.

    The model is told to return the subject only and mostly does, but
    "keep track of my knee physio" came back whole and rebuilt as
    "logged my keep track of my knee physio". A prompt alone can't be
    relied on for this, so the obvious shapes are removed here too.
    """
    detail = (detail or "").strip().strip('"\'')
    if not detail:
        return ""

    previous = None
    while previous != detail:
        previous = detail
        detail = _DETAIL_PREFIX.sub("", detail).strip()

    # The canonical phrase ends in a possessive ("logged my", "i took
    # my"), so a detail that also starts with one stutters.
    if canonical.rstrip().endswith(("my", "the", "a", "an")):
        detail = _LEADING_POSSESSIVE.sub("", detail).strip()

    return detail


def _catalog() -> str:
    return "\n".join(f"- {t.name}: {t.describes}" for t in TOOLS)


def select(prompt: str, brain) -> dict | None:
    """Ask the model which capability this wanted. Returns
    {"tool", "detail"} or None.

    None on anything unexpected. This sits in front of the conversational
    fallback, so failing here costs the boss nothing -- he gets the same
    answer he would have got without it.
    """
    if not ENABLED or not brain:
        return None

    try:
        result = brain.think(
            f"Capabilities:\n{_catalog()}\n\nRequest: {prompt}\n\n{_SYSTEM}",
            raw=True,
        )
    except Exception:
        logging.exception("[tool_router] selection call failed")
        return None

    if not result:
        return None

    choice = _parse(result.get("response", ""))
    if not choice:
        return None

    name = choice.get("tool")
    if not name or name not in _BY_NAME:
        # Includes the model inventing a capability that doesn't exist,
        # which is the exact failure this whole feature is meant to stop.
        if name:
            logging.warning("[tool_router] model picked unknown capability %r", name)
        return None

    return {"tool": name, "detail": (choice.get("detail") or "").strip()}


def _parse(text: str) -> dict | None:
    """The model wraps JSON in prose often enough that bare json.loads
    throws away good answers."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def rephrase(tool: str, detail: str) -> str | None:
    """Turn a routing decision into words the dispatch chain claims.

    This is the whole mechanism: dispatch stays the single way in, and
    the model's job is reduced from "do the thing" to "say which thing",
    which is the part it is actually reliable at.
    """
    entry = _BY_NAME.get(tool)
    if not entry:
        return None
    if not entry.takes_detail:
        return entry.canonical
    detail = _clean_detail(detail, entry.canonical, "")
    return f"{entry.canonical} {detail}".strip() if detail else entry.canonical
