"""core/fact_commands.py — let the boss see, and delete, what FRIDAY has
learned about him. Auto-learned facts (core/fact_extractor.py) will
sometimes be wrong; this is the undo button.

  "what do you know about me"   -> numbered list of her facts
  "forget fact 3"               -> delete that number from the last list
  "forget that I like X"        -> delete the one fact that clearly matches;
                                   if several match, list them to pick from

handle() returns a reply string, or None to fall through to the rest of
FRIDAY's command chain. A vague "forget that ..." that matches no fact
returns None, so it can't hijack ordinary conversation.
"""
import re

from core import memory_hub

_LIST_TRIGGERS = (
    "what do you know about me", "what have you learned about me",
    "what do you remember about me", "show my facts", "list my facts",
    "show me my facts", "what facts do you have",
)
_FORGET_NUM = re.compile(r"\bforget (?:fact|number|#)\s*#?(\d+)\b")
_FORGET_TEXT = re.compile(r"\bforget (?:that |the fact that |about )?(.{6,})$")
_LIST_CAP = 30

_last_listing: list = []


def _stem(word: str) -> str:
    """Crude suffix strip so "use" matches "uses" and "build" matches
    "builds"/"building"."""
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _words(text: str) -> set:
    return {_stem(w) for w in memory_hub._words(text) - memory_hub._STOPWORDS}


def _list_reply() -> str:
    from core.friday_memory import get_facts
    global _last_listing
    facts = list(reversed(get_facts(_LIST_CAP)))  # newest first
    _last_listing = facts
    if not facts:
        return ("I haven't picked up anything lasting about you yet, boss. "
                "Tell me about yourself and I'll start learning.")
    lines = "\n".join(f"{i}. {f}" for i, f in enumerate(facts, 1))
    return (f"Here's what I\'ve picked up, boss:\n{lines}\n"
            f"Say \"forget fact N\" to remove one.")


def _forget_number(n: int) -> str:
    from core.friday_memory import delete_fact
    if not _last_listing:
        return "Ask me \"what do you know about me\" first so we're looking at the same list, boss."
    if not 1 <= n <= len(_last_listing):
        return f"I only listed {len(_last_listing)} facts, boss — there's no number {n}."
    fact = _last_listing[n - 1]
    if delete_fact(fact):
        _last_listing.pop(n - 1)
        return f"Done, boss — forgot: {fact}"
    return "I couldn't find that one anymore — it may already be gone."


def _forget_text(query: str) -> str | None:
    from core.friday_memory import get_facts, delete_fact
    global _last_listing
    q = _words(query)
    if not q:
        return None
    scored = []
    for fact in get_facts(200):
        shared = len(q & _words(fact))
        if shared:
            scored.append((shared, fact))
    if not scored:
        return None
    scored.sort(key=lambda s: s[0], reverse=True)
    best = scored[0][0]
    top = [f for s, f in scored if s == best]
    # Need real overlap (not one stray word) to act on a vague phrase.
    if best < min(2, len(q)):
        return None
    if len(top) == 1:
        if delete_fact(top[0]):
            return f"Done, boss — forgot: {top[0]}"
        return None
    _last_listing = top[:10]
    lines = "\n".join(f"{i}. {f}" for i, f in enumerate(_last_listing, 1))
    return (f"A few of those could match, boss:\n{lines}\n"
            f"Say \"forget fact N\" for the one you mean.")


def handle(prompt: str) -> str | None:
    p = (prompt or "").strip().lower().rstrip(".!?")
    if any(trigger in p for trigger in _LIST_TRIGGERS):
        return _list_reply()
    m = _FORGET_NUM.search(p)
    if m:
        return _forget_number(int(m.group(1)))
    m = _FORGET_TEXT.search(p)
    if m:
        return _forget_text(m.group(1))
    return None
