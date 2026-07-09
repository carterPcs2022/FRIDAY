"""core/scenario_engine.py — Infinity War's "14 million futures" framing,
adapted for FRIDAY: N independent, parallel single-shot projections tallied
into a real success rate. Uses core.friday_brain.friday_brain.think()
since FRIDAY has no generic LLM router with tier control."""
import concurrent.futures

from core.friday_brain import friday_brain


class ScenarioEngine:

    def analyze_futures(self, situation: str, n_scenarios: int = 6) -> dict:
        """Default n_scenarios kept lower than JARVIS's (10) — each call
        goes through friday_brain's normal Groq/Anthropic budget-gated
        path, and FRIDAY's daily call budget (budget_2.py) is smaller."""
        def run_one(i: int) -> dict:
            text = friday_brain.think(
                f"Future scenario {i + 1}/{n_scenarios}:\n"
                f"Situation: {situation}\n\n"
                f"Model one possible future outcome. What happens? Does it "
                f"succeed or fail? Key decision point that determines outcome.\n"
                f"Reply as: OUTCOME: [success/failure] | PATH: [key decision] | "
                f"RESULT: [what happens]",
            )["response"]
            outcome = "success" if "SUCCESS" in text.upper() else "failure"
            return {"scenario": i + 1, "text": text, "outcome": outcome}

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run_one, i) for i in range(n_scenarios)]
            for f in concurrent.futures.as_completed(futures, timeout=30):
                try:
                    results.append(f.result())
                except Exception:
                    pass

        successes = [s for s in results if s["outcome"] == "success"]
        failures = [s for s in results if s["outcome"] == "failure"]

        if successes:
            winning_path = friday_brain.think(
                f"From {len(successes)} successful scenarios:\n"
                + "\n".join(s["text"][:100] for s in successes[:3])
                + "\n\nWhat is the single path to success? One clear recommendation."
            )["response"]
        else:
            winning_path = "No clear path to success found."

        return {
            "situation": situation, "scenarios": n_scenarios,
            "successes": len(successes), "failures": len(failures),
            "success_rate": f"{len(successes) / max(n_scenarios, 1) * 100:.0f}%",
            "winning_path": winning_path,
        }


scenario_engine = ScenarioEngine()
