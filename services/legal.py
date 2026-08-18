"""services/legal.py — plain-English contract analysis. Educational only,
never legal advice — every response says so explicitly. Ported from
JARVIS_V5's services/legal.py; FRIDAY had no equivalent.

Calls core/friday_brain.py's friday_brain._call_anthropic() directly
rather than think() — think() is built for short conversational replies
and hard-truncates anything past ~400 chars (voice_mode's max_chars),
which would mutilate a real contract analysis. Same pattern
core/friday_brain.py's own deep_think()/self_critique() already use for
their opt-in, endpoint-only advanced calls. Still budget-gated (see
budget_2.py) exactly like every other Anthropic call in this repo.
"""
from core.friday_brain import friday_brain, MODELS

_SYSTEM = "You are a careful, precise legal document analyst helping a layperson understand a document."


def _call(prompt: str, max_tokens: int = 1024) -> str:
    result = friday_brain._call_anthropic(
        [{"role": "user", "content": prompt}], _SYSTEM, MODELS["deep"], max_tokens=max_tokens,
    )
    if not result:
        return "Couldn't reach the model to analyze this right now, boss — try again in a bit."
    return result["content"]


class LegalAnalyzer:

    def analyze_contract(self, text: str) -> dict:
        analysis = _call(
            f"Analyze this legal document as a knowledgeable friend explaining it in plain English.\n\n"
            f"For each major section:\n1. What it means in simple terms\n"
            f"2. Any red flags or unusual clauses\n3. What you're agreeing to\n"
            f"4. Questions to ask a lawyer\n\nDocument:\n{text[:4000]}\n\n"
            f"Note: This is educational analysis, not legal advice.",
            max_tokens=1500,
        )
        return {"analysis": analysis, "disclaimer": "Educational analysis only. Not legal advice."}

    def find_red_flags(self, text: str) -> list[str]:
        result = _call(
            f"List only the red flags and concerning clauses in this document. Be specific:\n\n{text[:3000]}",
            max_tokens=800,
        )
        return [line for line in result.split("\n") if line.strip()]

    def simplify_clause(self, clause: str) -> str:
        return _call(f"Explain this legal clause in one simple sentence that anyone can understand:\n\n{clause}",
                      max_tokens=200)


legal = LegalAnalyzer()
