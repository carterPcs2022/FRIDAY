"""core/memory_hub.py — one recall() across every memory store FRIDAY
has, instead of five independent ones with no shared interface.

The V2→V3 audit's finding: facts/conversations/notes (core/friday_memory.py),
arbitrary ingested content (services/second_brain.py), things read
(services/reading_memory.py), daily journal entries (services/friday_journal.py),
and emotional/topic continuity (services/friday_continuity.py) are five
separate stores, each with its own storage and retrieval logic, and
there's no single place that answers "what does FRIDAY actually know
about X" across all of them.

This does NOT create a sixth store or migrate any existing data — every
store below keeps its own format, its own write path, its own
Turso/local-JSON fallback exactly as before. It's a read-side facade
plus a thin write-side dispatcher, not a new schema:

  recall(query)   — pulls candidates from every store, re-scores them
                     all with one consistent keyword-overlap function
                     (so a fact and a journal entry are actually
                     comparable instead of each store inventing its own
                     notion of "close enough"), returns one ranked list
                     tagged with source/score/timestamp.

  remember(...)    — one entrypoint that routes to whichever store's own
                     write method actually fits the content. Not a
                     common schema across five different kinds of
                     content — a URL isn't a mood, a topic isn't a fact —
                     just one name to remember something under instead
                     of five to learn.

services/wisdom.py already did the decisions/reading/journal part of
this well (get_wisdom_context()) — reused directly here rather than
reimplemented; recall() folds its output in as pre-scored hits instead
of re-querying those two stores a second time.
"""
import re
from datetime import datetime

_WORD_RE = re.compile(r"[a-z0-9']+")


# Filler words that used to count as "matches" (every message shares "the",
# "my", "is" with some stored text), drowning out the words that matter.
_STOPWORDS = frozenset(
    "a an the and or but if so of to in on at by for with from as is are was were be "
    "been am do does did have has had i me my mine we our you your it its this that "
    "these those what who how when where why can could should would will just not no "
    "yes about up out into than then them they he she his her there here".split())


def _words(text: str) -> set:
    return set(_WORD_RE.findall((text or "").lower()))


def overlap_score(query_words: set, text: str) -> int:
    """The one relevance scorer every source below is ranked with --
    same approach core/friday_memory.py's own recall() and
    services/wisdom.py already use, just shared here so results from
    different stores are directly comparable."""
    return len((query_words & _words(text)) - _STOPWORDS)


def _facts_and_notes(q_words: set, limit: int) -> list:
    # Wraps the whole body, not just the import: a Turso hiccup inside
    # get_facts()/get_notes() must not take every *other* store's
    # results down with it -- same "one broken piece can't sink the
    # whole request" convention this codebase uses everywhere else
    # (services/notifications.py's per-channel try/except is the
    # clearest example).
    try:
        from core.friday_memory import get_facts, get_notes

        hits = []
        for fact in get_facts(100):
            score = overlap_score(q_words, fact)
            if score:
                hits.append({"text": fact, "source": "facts", "score": score, "ts": None})
        for note in get_notes(100):
            text = f"{note.get('content', '')} {note.get('context', '')}"
            score = overlap_score(q_words, text)
            if score:
                hits.append({
                    "text": note.get("content", ""), "source": "notes",
                    "score": score, "ts": note.get("ts"),
                })
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]
    except Exception:
        return []


def _second_brain(query: str, q_words: set, limit: int) -> list:
    try:
        from services.second_brain import second_brain
        hits = []
        for entry in second_brain.recall(query, limit=limit):
            text = entry.get("summary", "") or entry.get("content", "")
            hits.append({
                "text": text, "source": "second_brain",
                "score": overlap_score(q_words, text), "ts": entry.get("ts"),
            })
        return hits
    except Exception:
        return []


def _continuity_topics(q_words: set, limit: int) -> list:
    try:
        from services.friday_continuity import continuity
        hits = []
        for t in continuity.get_unresolved_topics():
            score = overlap_score(q_words, t.get("topic", ""))
            if score:
                hits.append({
                    "text": f"Unresolved: {t.get('topic', '')} ({t.get('mentions', 0)}x mentioned)",
                    "source": "continuity", "score": score,
                    "ts": t.get("last_mentioned") or t.get("first_mentioned"),
                })
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]
    except Exception:
        return []


_WISDOM_LABELS = {
    "Past decisions relevant to this": "decisions",
    "Previously read on this": "reading",
    "Relevant journal entries": "journal",
}


def _wisdom(query: str) -> list:
    """Folds in services/wisdom.py's existing decisions/reading/journal
    coverage rather than re-querying those two stores independently --
    get_wisdom_context() already returns pre-formatted, pre-ranked text
    per source, so each source line it returned becomes one hit here."""
    try:
        from services.wisdom import get_wisdom_context
        context = get_wisdom_context(query, limit=3)
        if not context:
            return []
        hits = []
        for line in context.split("\n"):
            if not line.strip():
                continue
            label, sep, text = line.partition(": ")
            source = _WISDOM_LABELS.get(label, "wisdom")
            hits.append({"text": text if sep else line, "source": source, "score": 1, "ts": None})
        return hits
    except Exception:
        return []


def recall(query: str, limit: int = 8) -> list:
    """One ranked list across every memory store FRIDAY has, each hit
    tagged with where it came from: {"text", "source", "score", "ts"}.
    Empty query or nothing relevant anywhere returns [] -- this never
    injects a running summary into every request, only what's actually
    relevant to `query`, matching every other recall in this codebase."""
    q_words = _words(query)
    if not q_words:
        return []

    hits = []
    hits += _facts_and_notes(q_words, limit)
    hits += _second_brain(query, q_words, limit)
    hits += _continuity_topics(q_words, limit)
    hits += _wisdom(query)

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:limit]


def remember(content: str, kind: str = "general", **kwargs) -> dict:
    """One entrypoint to store something, routed to whichever store's
    own write method actually fits `kind`:

      fact    -> core.friday_memory.save_fact(content)
      note    -> core.friday_memory.save_note(...)
      reading -> services.reading_memory.index_url(url=content, title=kwargs["title"])
      journal -> services.friday_journal.log_entry(content, mood=kwargs["mood"])
      topic   -> services.friday_continuity.record_topic(content, resolved=kwargs["resolved"])
      general (default) -> services.second_brain.ingest(content, source=..., tags=...)

    Every write still has a reason (the caller picked `kind`) -- this
    isn't a "store everything" bucket, just one name to remember
    something under instead of five to learn.
    """
    kind = (kind or "general").lower()

    if kind == "fact":
        from core.friday_memory import save_fact
        save_fact(content)
        return {"stored": True, "kind": "fact"}

    if kind == "note":
        from core.friday_memory import save_note
        save_note({
            "content": content, "context": kwargs.get("context", ""),
            "ts": datetime.now().isoformat(),
        })
        return {"stored": True, "kind": "note"}

    if kind == "reading":
        from services.reading_memory import reading_mem
        result = reading_mem.index_url(content, title=kwargs.get("title", ""))
        return {"stored": "error" not in result, "kind": "reading", **result}

    if kind == "journal":
        from services.friday_journal import journal
        result = journal.log_entry(content, mood=kwargs.get("mood", "neutral"))
        return {"stored": True, "kind": "journal", **result}

    if kind == "topic":
        from services.friday_continuity import continuity
        continuity.record_topic(content, resolved=kwargs.get("resolved", False))
        return {"stored": True, "kind": "topic"}

    from services.second_brain import second_brain
    result = second_brain.ingest(content, source=kwargs.get("source", ""), tags=kwargs.get("tags"))
    return {"kind": "general", **result}
