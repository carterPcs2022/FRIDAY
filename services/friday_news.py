"""services/friday_news.py — personalized brief over core.tools.web's
DuckDuckGo search. Honest about the source: Instant-Answer results, not a
real news wire, so coverage of breaking stories will often be thin."""
import os
import json
from pathlib import Path

INTERESTS_FILE = Path("memory/friday_interests.json")

# FRIDAY_NEWS_INTERESTS overrides the built-in default list — comma-
# separated, e.g. "AI,robotics,SpaceX". Only the seed default; once
# add_interest()/_save_interests() has written memory/friday_interests.json,
# that file wins on every subsequent read (same as before this existed).
_DEFAULT_INTERESTS_FALLBACK = (
    "artificial intelligence,Iron Man technology,exoskeleton,"
    "wearable tech,robotics,Anthropic,tech startups,SpaceX"
)
DEFAULT_INTERESTS = [
    t.strip() for t in os.getenv("FRIDAY_NEWS_INTERESTS", _DEFAULT_INTERESTS_FALLBACK).split(",")
    if t.strip()
]


class FridayNewsAnchor:

    def morning_brief(self) -> str:
        from core.friday_brain import friday_brain
        from core.tools.web import search

        interests = self._load_interests()
        all_results = []
        for topic in interests[:4]:
            all_results.extend(search(f"{topic} latest news", 2))

        if not all_results:
            return "No news to report this morning, boss."

        result = friday_brain.think(
            f"Morning news brief:\n\n"
            + "\n".join(
                f"- {r.get('title', '')}: {r.get('snippet', '')[:100]}"
                for r in all_results[:8]
            )
            + "\n\nTop 3-4 stories only. Under 80 words. FRIDAY anchor style."
        )
        return result["response"]

    def breaking_news(self, topic: str) -> str:
        from core.friday_brain import friday_brain
        from core.tools.web import search

        all_results = search(f"{topic} breaking news today", 5)
        if not all_results:
            return f"Nothing new on {topic}, boss."

        result = friday_brain.think(
            f"Breaking news on {topic}:\n"
            + "\n".join(f"- {r.get('title', '')}" for r in all_results[:5])
            + "\nBrief update. Under 40 words."
        )
        return result["response"]

    def add_interest(self, topic: str):
        interests = self._load_interests()
        if topic not in interests:
            interests.append(topic)
            self._save_interests(interests)

    def _load_interests(self) -> list:
        if INTERESTS_FILE.exists():
            try:
                return json.loads(INTERESTS_FILE.read_text())
            except Exception:
                return DEFAULT_INTERESTS
        return DEFAULT_INTERESTS

    def _save_interests(self, interests: list):
        INTERESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        INTERESTS_FILE.write_text(json.dumps(interests, indent=2))


news_anchor = FridayNewsAnchor()
