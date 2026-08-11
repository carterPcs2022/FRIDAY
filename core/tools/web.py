"""core/tools/web.py — thin, stable-shape wrapper over core/tools/search.py's
multi-provider cascade (Serper -> Tavily -> SerpApi -> DuckDuckGo, same one
JARVIS_V5 uses). This module used to hit DuckDuckGo's Instant Answer API
directly — an encyclopedia/disambiguation service, not a real search index,
so genuinely current queries often came back empty. search()/news_search()
keep their original bare list[dict] return shape (title/url/snippet) so the
five existing callers (services/recognizance.py, services/friday_news.py,
server.py, core/autonomous_agent.py, core/friday_capabilities.py) don't need
to change; DuckDuckGo still applies automatically as the cascade's no-key
fallback, so behavior is a strict upgrade with nothing configured."""
import re

import httpx

from core.tools.search import search as _cascade_search, SearchCascade

_TIMEOUT = 12


def search(query: str, max_results: int = 5) -> list[dict]:
    return _cascade_search(query, max_results)["results"]


def news_search(query: str, max_results: int = 5) -> list[dict]:
    """Alias used by core/friday_capabilities.py's internet_monitor() and
    services/friday_news.py — same underlying search, named for what
    those callers expect."""
    return SearchCascade.news_search(query)[:max_results]


def fetch(url: str, max_chars: int = 3000) -> str:
    """Fetch a URL and strip it down to plain text — regex-based, not a
    real HTML parser, same tradeoff JARVIS_V5's core/tools/web.py makes
    to avoid a BeautifulSoup dependency for what's ultimately just LLM
    context. Ported for services/reading_memory.py, which FRIDAY had no
    equivalent of before."""
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as c:
            r = c.get(url, headers={"User-Agent": "FRIDAY/2.0"})
            text = r.text
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()[:max_chars]
    except Exception as e:
        return f"[Fetch error: {e}]"
