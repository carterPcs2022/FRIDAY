"""services/recognizance.py — MCU-flavored recon: plan a couple of
research angles, run them in parallel, fold in whatever second_brain
already has stored, then hand back one tactical brief. Same honest
framing as core/friday_capabilities.py's other capability wrappers —
there's no dedicated research engine behind this, just friday_brain.think()
called twice with a real web search and a real memory recall stitched
in between.

core.tools.web actually exists in this repo (it was ported in after
core/friday_capabilities.py's docstring was written claiming it doesn't —
that comment is stale for this module; verified by reading
core/tools/web.py directly). Still wrapped in try/except below so a
network hiccup or a future removal degrades to a memory-only recon
instead of crashing the request.
"""
import re
import concurrent.futures


class RecognizanceProtocol:

    def scout(self, situation: str) -> dict:
        from core.friday_brain import friday_brain

        plan = friday_brain.think(
            f"Recon planning for: {situation}\n\n"
            f"List 2-3 specific research queries that would help assess this "
            f"situation. One per line, each starting with '-'."
        )["response"]

        queries = re.findall(r'[-•]\s*(.+)', plan)
        if not queries:
            queries = [situation]
        queries = queries[:3]

        results = []
        try:
            from core.tools.web import search
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(search, q, 3) for q in queries]
                for f in concurrent.futures.as_completed(futures, timeout=15):
                    try:
                        results.extend(f.result())
                    except Exception:
                        pass
        except Exception:
            pass  # degrade to memory-only recon if web search is unavailable

        memory_hits = []
        try:
            from services.second_brain import second_brain
            memory_hits = second_brain.recall(situation, 3)
        except Exception:
            pass

        brief = friday_brain.think(
            f"Recon brief for: {situation}\n\n"
            f"Research findings:\n"
            + "\n".join(f"- {r.get('title', '')}: {r.get('snippet', '')[:150]}" for r in results[:6])
            + "\n\nRelevant memory:\n"
            + "\n".join(f"- {m.get('summary', '')}" for m in memory_hits)
            + "\n\nTactical brief. Under 100 words. FRIDAY style."
        )["response"]

        return {"situation": situation, "queries": queries, "brief": brief}


recognizance = RecognizanceProtocol()
