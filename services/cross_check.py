"""services/cross_check.py — asks FRIDAY and JARVIS the same question
independently, then has FRIDAY judge whether the two answers actually
agree, instead of either assistant silently deferring to the other.

JARVIS's real chat endpoint is server/routes/chat.py's
POST /stark/chat (FastAPI, protected by Depends(verify_token) reading
JARVIS_API_TOKEN on JARVIS's side) — it takes {"message": ...} and
returns {"response": ...} among other fields, same shape server.py's own
JARVIS proxy already relies on (see the "Proxy to JARVIS" block in
command() in server.py). Reusing that exact request/response shape here
rather than inventing a second convention for the same endpoint.
"""
import os
import httpx

JARVIS_URL = os.getenv("JARVIS_URL", "http://localhost:8000")
JARVIS_TOKEN = os.getenv("JARVIS_API_TOKEN", "")


_NO_HALLUCINATION_CONSTRAINT = (
    "You have no specific project data beyond what's in your actual memory and "
    "second brain. If asked about project specifics (manufacturing status, "
    "components, timelines) that you don't have real logged information about, "
    "say so explicitly — do not invent specific details, percentages, component "
    "names, or status updates that aren't grounded in actual stored data. A "
    "probability estimate itself is fine to give (that's the nature of the ask), "
    "but do NOT list fake specific 'contributing factors' with fabricated "
    "precision numbers unless those factors are real and known."
)


class CrossCheck:

    def ask_both(self, question: str) -> dict:
        from core.friday_brain import friday_brain

        # Ground the answer in whatever's actually stored before asking —
        # a question about "the exoskeleton" or "the energy core" with no
        # real second_brain/goals entry behind it is exactly the pattern
        # that previously got a confident, entirely fabricated status
        # update. If nothing real turns up, say so in the prompt instead
        # of leaving the model to fill the gap itself.
        stored_context = self._gather_stored_facts(question)

        friday_answer = friday_brain.think(
            f"Independent analysis (don't know what anyone else thinks): {question}\n\n"
            f"Actual stored facts relevant to this question:\n{stored_context}\n\n"
            f"{_NO_HALLUCINATION_CONSTRAINT}"
        )["response"]

        jarvis_answer = self._ask_jarvis(question)

        agreement = self._judge(question, friday_answer, jarvis_answer)

        return {
            "question": question,
            "friday": friday_answer,
            "jarvis": jarvis_answer,
            "agreement": agreement,
        }

    def _gather_stored_facts(self, question: str) -> str:
        """Real second_brain/goals entries relevant to the question, or an
        explicit "nothing found" line — never silence, which is what let
        the model assume it was free to invent something plausible."""
        facts = []
        try:
            from services.second_brain import second_brain
            for entry in second_brain.recall(question, limit=5):
                summary = entry.get("summary", "")
                if summary:
                    facts.append(f"- {summary}")
        except Exception:
            pass

        try:
            from services.friday_goals import goals
            q_words = set(question.lower().split())
            for goal in goals.get_active_goals():
                text = (goal.get("name", "") + " " + goal.get("description", "")).lower()
                if any(w in text for w in q_words if len(w) > 3):
                    facts.append(f"- Goal: {goal.get('name', '')} — {goal.get('description', '')}")
        except Exception:
            pass

        return "\n".join(facts) if facts else "(No real stored facts found relevant to this question.)"

    def _ask_jarvis(self, question: str) -> str:
        if not JARVIS_TOKEN:
            return "(JARVIS isn't reachable — no JARVIS_API_TOKEN configured)"
        try:
            r = httpx.post(
                f"{JARVIS_URL}/stark/chat",
                json={"message": question},
                headers={"Authorization": f"Bearer {JARVIS_TOKEN}"},
                timeout=15,
            )
            if r.status_code == 200:
                return r.json().get("response", "") or "(JARVIS returned no response)"
            return f"(JARVIS returned {r.status_code})"
        except Exception as e:
            return f"(Couldn't reach JARVIS: {e})"

    def _judge(self, question: str, friday_answer: str, jarvis_answer: str) -> dict:
        # _ask_jarvis()'s four failure paths (no token, non-200, timeout/
        # network error, empty body) all come back as a parenthesized
        # placeholder, never a real answer. Handing one to the model here
        # anyway used to get it judged like a genuine opinion -- confirmed
        # live: "(JARVIS returned 503)" was scored "AGREE Both advise
        # obtaining an independent specialist's opinion," inventing an
        # opinion JARVIS never gave. There is nothing to compare against,
        # so say that instead of asking the model to judge a non-answer.
        if jarvis_answer.strip().startswith("("):
            return {
                "aligned": None,
                "note": "Couldn't compare — JARVIS didn't give a real answer to check against.",
            }

        from core.friday_brain import friday_brain

        result = friday_brain.think(
            f"Two independent answers to the same question.\n\n"
            f"Question: {question}\n\n"
            f"Answer A (FRIDAY): {friday_answer}\n\n"
            f"Answer B (JARVIS): {jarvis_answer}\n\n"
            f"Do these two answers substantively agree? Reply with AGREE or "
            f"DISAGREE on the first line, then one sentence explaining why."
        )["response"]

        aligned = result.strip().upper().startswith("AGREE")
        return {"aligned": aligned, "note": result}


cross_check = CrossCheck()
