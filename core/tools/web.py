"""core/tools/web.py — DuckDuckGo Instant Answer search, no API key
required. Ported from JARVIS_V5's core/tools/web.py, which this repo
didn't have at all — News Anchor and the pre-existing
core/friday_capabilities.py's internet_monitor() both imported a
core.tools.web that never existed, so both silently always returned no
results. This makes that real instead of a permanent no-op.

Caveat worth knowing: DuckDuckGo's Instant Answer API is an
encyclopedia/disambiguation service, not a real news index — it will
often come back empty for genuinely current event queries. Real, but
weaker than the name "search" implies."""
import httpx

TIMEOUT = 12


def search(query: str, max_results: int = 5) -> list[dict]:
    try:
        params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.get("https://api.duckduckgo.com/", params=params,
                      headers={"User-Agent": "FRIDAY/2.0"})
            data = r.json()
        results = []
        if data.get("AbstractText"):
            results.append({"title": data.get("Heading", ""), "url": data.get("AbstractURL", ""),
                            "snippet": data["AbstractText"][:400]})
        for t in data.get("RelatedTopics", [])[:max_results - len(results)]:
            if "Text" in t and "FirstURL" in t:
                results.append({"title": t["Text"][:80], "url": t["FirstURL"],
                                "snippet": t["Text"][:400]})
        return results[:max_results]
    except Exception:
        return []


def news_search(query: str, max_results: int = 5) -> list[dict]:
    """Alias used by core/friday_capabilities.py's internet_monitor() and
    services/friday_news.py — same underlying search, named for what
    those callers expect."""
    return search(query, max_results)
