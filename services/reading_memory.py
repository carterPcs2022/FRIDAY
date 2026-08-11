"""services/reading_memory.py — everything you've read, indexed and
searchable months later. Ported from JARVIS_V5's services/reading_memory.py;
FRIDAY had no equivalent. Reuses core/tools/web.py's fetch() (ported
alongside this, regex-based HTML stripping) rather than adding a
BeautifulSoup dependency for the same job.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_FILE = BASE_DIR / "memory" / "reading_index.json"


def _load() -> list:
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text())
        except Exception:
            pass
    return []


def _save(data: list):
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(data[-5000:], indent=2))


class ReadingMemory:

    def index_url(self, url: str, title: str = "") -> dict:
        """Index a webpage you've read — extracts key concepts and stores
        it for later recall."""
        from core.tools.web import fetch

        text = fetch(url, max_chars=3000)
        if not text or text.startswith("[Fetch error"):
            return {"error": text or "Could not fetch URL"}

        try:
            from core.friday_brain import friday_brain, MODELS
            result = friday_brain._call_anthropic(
                [{"role": "user", "content":
                  f"Extract 5-10 key concepts from this article:\n{text[:1000]}\n\n"
                  f"Return as a comma-separated list."}],
                "You extract key concepts from text concisely.", MODELS["nuanced"], max_tokens=150,
            )
            concepts = result["content"] if result else "[concept extraction unavailable]"
        except Exception as e:
            concepts = f"[concept extraction unavailable: {e}]"

        entry = {
            "url": url, "title": title or url, "concepts": concepts,
            "preview": text[:300], "ts": datetime.now().isoformat(),
        }

        index = _load()
        index.append(entry)
        _save(index)

        try:
            from core.friday_memory import save_fact
            save_fact(f"Read: {entry['title']} — {concepts[:100]}")
        except Exception:
            pass

        return entry

    def search_reading(self, query: str) -> list[dict]:
        """Find things you've previously read, ranked by keyword overlap."""
        index = _load()
        q_words = set(query.lower().split())
        scored = []
        for entry in index:
            text = f"{entry.get('title', '')} {entry.get('concepts', '')} {entry.get('preview', '')}".lower()
            score = sum(1 for w in q_words if w in text)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:5]]


reading_mem = ReadingMemory()
