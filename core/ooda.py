"""core/ooda.py — OODA loop (Observe/Orient/Decide/Act) adapted for
FRIDAY. The source spec's version imported core.llm.router.think() with a
force_model tier param — that module doesn't exist here; FRIDAY has no
generic LLM router, only core.friday_brain.friday_brain.think(), which
auto-classifies its own tier internally. Same four-phase structure, wired
to FRIDAY's real entry point instead."""
import time

from core.friday_brain import friday_brain


class OODAEngine:

    def run(self, situation: str, context: str = "") -> dict:
        start = time.time()

        observe = friday_brain.think(
            f"OBSERVE phase — gather all facts:\n"
            f"Situation: {situation}\n"
            f"{f'Context: {context}' if context else ''}\n\n"
            f"What is actually happening right now? What data do we have?\n"
            f"No interpretation yet. Facts only.",
        )["response"]

        orient = friday_brain.think(
            f"ORIENT phase — interpret the facts:\n"
            f"Situation: {situation}\n"
            f"Observations: {observe[:300]}\n\n"
            f"What does this mean? What patterns apply? What are the implications?",
        )["response"]

        decide = friday_brain.think(
            f"DECIDE phase — choose action:\n"
            f"Situation: {situation}\n"
            f"Orientation: {orient[:300]}\n\n"
            f"What are the options? Which is best and why?\n"
            f"Decision: [clear single action]",
        )["response"]

        act = friday_brain.think(
            f"ACT phase — execute and prepare:\n"
            f"Decision: {decide[:200]}\n\n"
            f"Specific next action to take NOW.\n"
            f"What to watch for in the next OBSERVE cycle. One sentence each.",
        )["response"]

        return {
            "situation": situation, "observe": observe, "orient": orient,
            "decide": decide, "act": act,
            "loop_ms": round((time.time() - start) * 1000),
            "method": "OODA",
        }

    def rapid_ooda(self, situation: str) -> str:
        """Single-call OODA for time-critical situations."""
        return friday_brain.think(
            f"OODA rapid analysis:\n{situation}\n\n"
            f"OBSERVE: [facts]\nORIENT: [meaning]\nDECIDE: [action]\nACT: [now]\n\n"
            f"Four lines. Fast.",
        )["response"]


ooda = OODAEngine()
