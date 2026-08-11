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
from core.tools.search import search as _cascade_search, SearchCascade


def search(query: str, max_results: int = 5) -> list[dict]:
    return _cascade_search(query, max_results)["results"]


def news_search(query: str, max_results: int = 5) -> list[dict]:
    """Alias used by core/friday_capabilities.py's internet_monitor() and
    services/friday_news.py — same underlying search, named for what
    those callers expect."""
    return SearchCascade.news_search(query)[:max_results]
