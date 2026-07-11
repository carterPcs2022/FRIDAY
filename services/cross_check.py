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


class CrossCheck:

    def ask_both(self, question: str) -> dict:
        from core.friday_brain import friday_brain

        friday_answer = friday_brain.think(
            f"Independent analysis (don't know what anyone else thinks): {question}"
        )["response"]

        jarvis_answer = self._ask_jarvis(question)

        agreement = self._judge(question, friday_answer, jarvis_answer)

        return {
            "question": question,
            "friday": friday_answer,
            "jarvis": jarvis_answer,
            "agreement": agreement,
        }

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
