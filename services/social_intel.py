"""services/social_intel.py — pre-meeting intelligence briefs on people and
companies, combining FRIDAY's own memory with a public web search. Ported
from JARVIS_V5's services/social_intel.py; FRIDAY had no equivalent.

JARVIS's core/memory.recall_facts(name, k) does keyword-scored fact
recall out of the box. FRIDAY's core/friday_memory.py only has a flat
get_facts(n) (most-recent-N, no relevance scoring) — no equivalent
exists yet — so person_brief() does its own simple keyword filter over
her recent facts rather than inventing a new general-purpose scored-
recall function for one caller.
"""


def _relevant_facts(name: str, limit: int = 5) -> list[str]:
    from core.friday_memory import get_facts
    name_words = set(name.lower().split())
    matches = [f for f in get_facts(200) if any(w in f.lower() for w in name_words)]
    return matches[-limit:]


class SocialIntelligence:

    def person_brief(self, name: str, company: str = "", context: str = "") -> dict:
        from core.tools.web import search
        from core.friday_brain import friday_brain, MODELS

        memory_context = "\n".join(_relevant_facts(name))

        query = f"{name} {company}".strip()
        results = search(query, max_results=5)
        web_context = "\n".join(f"• {r.get('snippet', '')}" for r in results if r.get("snippet"))

        li_results = search(f"{name} {company} LinkedIn", max_results=3)
        li_context = "\n".join(f"• {r.get('snippet', '')}" for r in li_results if r.get("snippet"))

        prompt = (
            f"Generate a pre-meeting intelligence brief on:\n"
            f"Name: {name}\nCompany: {company}\nMeeting context: {context}\n\n"
            f"What FRIDAY knows: {memory_context}\n"
            f"Public information: {web_context[:500]}\n"
            f"Professional background: {li_context[:500]}\n\n"
            f"Include:\n1. Who they are (2 sentences)\n2. What they're working on recently\n"
            f"3. What they care about\n4. Talking points / common ground\n"
            f"5. What to avoid\n6. How to make a good impression\n\n"
            f"FRIDAY-style delivery. Briefing format."
        )
        result = friday_brain._call_anthropic(
            [{"role": "user", "content": prompt}], "You are FRIDAY, a helpful personal assistant.",
            MODELS["deep"], max_tokens=700,
        )
        brief = result["content"] if result else "Couldn't generate the brief right now, boss."
        return {"name": name, "company": company, "brief": brief, "sources": len(results)}

    def company_brief(self, company: str) -> dict:
        """Brief on a company before a meeting or pitch. Two separate
        searches (overview + recent news) rather than a nonexistent
        dedicated news-search tool."""
        from core.tools.web import search
        from core.friday_brain import friday_brain, MODELS

        web_results = search(f"{company} company overview", max_results=5)
        news_results = search(f"{company} news", max_results=5)

        web_context = "\n".join(f"• {r.get('snippet', '')}" for r in web_results if r.get("snippet"))
        news_context = "\n".join(f"• {r.get('snippet', '')}" for r in news_results if r.get("snippet"))

        prompt = (
            f"Intelligence brief on: {company}\n\n"
            f"Company info: {web_context[:500]}\nRecent news: {news_context[:500]}\n\n"
            f"Cover: what they do, size, recent news, opportunities, risks, "
            f"how to position yourself."
        )
        result = friday_brain._call_anthropic(
            [{"role": "user", "content": prompt}], "You are FRIDAY, a helpful personal assistant.",
            MODELS["deep"], max_tokens=600,
        )
        brief = result["content"] if result else "Couldn't generate the brief right now, boss."
        return {"company": company, "brief": brief}


social = SocialIntelligence()
