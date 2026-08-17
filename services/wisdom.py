"""services/wisdom.py — folds FRIDAY's own accumulated experience into
her live answers.

She already logs all of this — past decisions and their outcomes
(services/decisions.py), things she's read (services/reading_memory.py),
journal reflections (services/friday_journal.py) — but none of it fed
back into what she actually says: she could log a decision's outcome and
never recall it being relevant again next time something similar came
up. get_wisdom_context() is the missing link, using the same
keyword-overlap relevance scoring core/friday_memory.py already uses for
its own recall(), applied across these three stores instead.

Local, no-cost keyword filtering — not a fourth LLM call. Only returns
something when it's actually relevant to the current query, not a
running summary attached to every request.
"""
import re

_WORD_RE = re.compile(r"[a-z0-9']+")


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _overlap_score(query_words: set[str], text: str) -> int:
    return len(query_words & _words(text))


def get_wisdom_context(query: str, limit: int = 3) -> str:
    q_words = _words(query)
    if not q_words:
        return ""

    parts = []

    try:
        from services.decisions import decisions
        scored = []
        for entry in decisions.decision_log():
            text = f"{entry.get('decision', '')} {entry.get('notes', '')} {entry.get('outcome') or ''}"
            score = _overlap_score(q_words, text)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored:
            lines = []
            for _, e in scored[:limit]:
                line = f"{e.get('decision', '')}"
                if e.get("chosen_option"):
                    line += f" -> chose: {e['chosen_option']}"
                if e.get("outcome"):
                    line += f" (outcome: {e['outcome']})"
                lines.append(line)
            parts.append("Past decisions relevant to this: " + "; ".join(lines))
    except Exception:
        pass

    try:
        from services.reading_memory import reading_mem
        found = reading_mem.search_reading(query)
        titles = [e.get("title", "") for e in found[:limit] if e.get("title")]
        if titles:
            parts.append("Previously read on this: " + "; ".join(titles))
    except Exception:
        pass

    try:
        from services.friday_journal import journal
        scored = []
        for entry in journal.recent_entries(90):
            score = _overlap_score(q_words, entry.get("content", ""))
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored:
            lines = [f"{e.get('date', '')}: {e.get('content', '')[:150]}" for _, e in scored[:limit]]
            parts.append("Relevant journal entries: " + "; ".join(lines))
    except Exception:
        pass

    return "\n".join(parts)
