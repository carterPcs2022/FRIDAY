"""core/friday_brain.py — FRIDAY's brain. Faster than JARVIS by design: she
trusts her instincts, less deliberation, a more direct path from input to
output.

Model cascade:
1. Groq 8B instant  -> simple/fast queries
2. Groq 70B         -> complex reasoning
3. Claude Haiku     -> emotional/nuanced
4. Claude Sonnet     -> hardest problems (long/multi-part requests)
5. Offline fallback -> always responds
"""
import os
import time
import re
import threading
import httpx
from datetime import datetime

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_BASE = "https://api.groq.com/openai/v1"

# Provider health, tracked from real chat calls instead of a separate
# polling loop that hit GET .../v1/models every 30s regardless of actual
# usage (core/friday_protocols.py's check_range() called it on every
# JARVIS-monitor tick — 2 extra API calls every 30s, forever, burning
# quota independent of whether FRIDAY was even being used). Updated
# in-place from _call_groq()/_call_anthropic() below.
_HEALTH_FRESH_SECONDS = 300
_last_groq_success = 0.0
_last_groq_failure = 0.0
_last_anthropic_success = 0.0
_last_anthropic_failure = 0.0


def is_groq_healthy() -> bool:
    """True if the most recent real call succeeded more recently than the
    most recent real failure, OR nothing's been tried recently either way
    (idle isn't the same as down — defaulting to "assume down" here would
    mean every quiet period looks like an outage)."""
    if not GROQ_API_KEY:
        return False
    if _last_groq_failure > _last_groq_success:
        return time.time() - _last_groq_failure > _HEALTH_FRESH_SECONDS
    return True


def is_anthropic_healthy() -> bool:
    if not ANTHROPIC_KEY:
        return False
    if _last_anthropic_failure > _last_anthropic_success:
        return time.time() - _last_anthropic_failure > _HEALTH_FRESH_SECONDS
    return True

# Module-level pooled client, reused across every _call_groq() instead of
# a fresh httpx.post() (and its own TCP+TLS handshake) per call — saves
# 200-500ms per request via keep-alive connection reuse.
_GROQ_CLIENT = httpx.Client(
    base_url=GROQ_BASE,
    timeout=httpx.Timeout(connect=1.0, read=8.0, write=5.0, pool=5.0),
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5, keepalive_expiry=30),
)

# Real, currently-available model IDs — verified against provider docs, not
# guessed. claude-sonnet-4-6 doesn't exist; claude-sonnet-5 is current.
MODELS = {
    "fast": "llama-3.1-8b-instant",
    "smart": "llama-3.3-70b-versatile",
    "nuanced": "claude-haiku-4-5-20251001",
    "deep": "claude-sonnet-5",
    "maximum": "claude-opus-4-8",
}

MAXIMUM_TRIGGERS = [
    "maximum intelligence", "your best", "think hard",
    "most important", "critical decision",
]

from config.friday_personality import FRIDAY_PERSONALITY, FRIDAY_VOICE_MODES


class FridayBrain:

    def __init__(self):
        self.voice_mode = "normal"
        self._response_cache: dict = {}
        self._call_times: list = []
        # friday_brain is a shared singleton — the main request thread and
        # several core/autonomous_agent.py background monitors (news_spike,
        # sunday_brief, meeting_prep, emotional_check, goal_nudge) all call
        # think() -> _call_groq() concurrently, so this rate-limit
        # bookkeeping list needs protecting from the same read-modify-write
        # race as autonomous_agent.py's _actions_taken.
        self._call_times_lock = threading.Lock()

    # ── Query classification ─────────────────────────────────────────────────

    def classify(self, query: str) -> str:
        """FRIDAY classifies faster than JARVIS — she trusts pattern
        matching more than deliberation."""
        q = query.lower().strip()
        words = len(query.split())

        if any(t in q for t in MAXIMUM_TRIGGERS):
            return "maximum"

        INSTANT = ["what time", "what's the time", "hey friday", "you there",
                  "hello", "hi", "thanks", "thank you", "good morning",
                  "good night", "how are you"]
        if any(p in q for p in INSTANT) or words < 4:
            return "instant"

        EMOTIONAL = ["i'm feeling", "i feel", "i'm stressed", "i'm worried",
                    "i'm sad", "i'm anxious", "i need help",
                    "i don't know what to do", "i'm struggling", "this is hard"]
        if any(p in q for p in EMOTIONAL):
            return "nuanced"

        # Genuinely hard: long AND asking for real judgment, not just long.
        DEEP = ["should i", "help me decide", "pros and cons", "best approach",
               "walk me through", "think through this carefully"]
        if (any(p in q for p in DEEP) and words > 25) or words > 60:
            return "deep"

        STANDARD = ["should i", "help me decide", "what do you think",
                   "advice", "recommend", "analyze", "think through",
                   "pros and cons", "best approach"]
        if any(p in q for p in STANDARD) or words > 25:
            return "smart"

        return "fast"

    # ── Core thinking ─────────────────────────────────────────────────────────

    def think(self, query: str, context: str = "", emotion_context: str = "") -> dict:
        """FRIDAY's main think function. Fast, warm, instinctive."""
        start = time.time()

        if not query:
            return {"response": "Say something, boss.", "model": "instant", "ms": 0}

        instant = self._instant_response(query)
        if instant:
            return {"response": instant, "model": "instant", "ms": round((time.time() - start) * 1000)}

        cache_key = hash(query + context[:100])
        if cache_key in self._response_cache:
            cached = self._response_cache[cache_key]
            if time.time() - cached["ts"] < 300:
                return {**cached["data"], "cached": True}

        tier = self.classify(query)
        system = self._build_system(emotion_context)
        messages = self._build_messages(query, context)

        result = None
        if tier == "maximum" and ANTHROPIC_KEY:
            result = self._call_anthropic(messages, system, MODELS["maximum"])
        elif tier == "nuanced" and ANTHROPIC_KEY:
            result = self._call_anthropic(messages, system, MODELS["nuanced"])
        elif tier == "deep" and ANTHROPIC_KEY:
            result = self._call_anthropic(messages, system, MODELS["deep"])
        elif tier in ("fast", "instant") and GROQ_API_KEY:
            result = self._call_groq(messages, system, MODELS["fast"])
        elif GROQ_API_KEY:
            result = self._call_groq(messages, system, MODELS["smart"])

        if not result and ANTHROPIC_KEY:
            result = self._call_anthropic(messages, system, MODELS["nuanced"])

        if not result:
            result = {"content": f"(offline) Got it, boss: {query}", "model": "offline", "provider": "local"}

        ms = round((time.time() - start) * 1000)
        response = self._clean(result["content"])

        mode = FRIDAY_VOICE_MODES.get(self.voice_mode, {})
        max_chars = mode.get("max_chars", 400)
        if len(response) > max_chars:
            last_sentence = response[:max_chars].rfind(".")
            if last_sentence > max_chars * 0.6:
                response = response[:last_sentence + 1]
            else:
                response = response[:max_chars].rstrip() + "..."

        final = {
            "response": response, "model": result.get("model", ""),
            "provider": result.get("provider", ""), "ms": ms, "tier": tier,
        }

        self._response_cache[cache_key] = {"ts": time.time(), "data": final}
        if len(self._response_cache) > 100:
            oldest = min(self._response_cache, key=lambda k: self._response_cache[k]["ts"])
            del self._response_cache[oldest]

        return final

    # ── Instant responses ────────────────────────────────────────────────────

    def _instant_response(self, query: str) -> str | None:
        q = query.lower().strip()

        if any(t in q for t in ["what time", "what's the time"]):
            return f"It's {datetime.now().strftime('%I:%M %p')}, boss."
        if any(t in q for t in ["what day", "what's the date", "today's date"]):
            return datetime.now().strftime("%A, %B %d.")
        if any(t in q for t in ["hey friday", "you there", "friday are you", "are you online"]):
            return "Right here, boss."
        if any(t in q for t in ["thank", "thanks"]):
            return "Always."
        if "good morning" in q:
            return "Morning, boss. Ready when you are."
        if "good night" in q:
            return "Night, boss. I'll keep watch."
        # Without this guard a calendar question just goes to the LLM,
        # which has no way to know whether a calendar is connected and
        # may invent plausible-sounding events.
        if any(t in q for t in ["my calendar", "on my schedule", "any meetings",
                                "any events", "what's on my agenda"]):
            try:
                from services.friday_calendar import friday_calendar
                if friday_calendar.is_connected():
                    events = friday_calendar.get_today()
                    if not events:
                        return "Nothing on your calendar today, boss."
                    names = ", ".join(e["title"] for e in events[:5])
                    return f"You've got {len(events)} today: {names}."
            except Exception:
                pass
            return "Your calendar isn't connected yet, boss."

        return None

    # ── LLM calls ─────────────────────────────────────────────────────────────

    def _call_groq(self, messages: list, system: str, model: str, max_tokens: int = 512) -> dict | None:
        if not GROQ_API_KEY:
            return None

        now = time.time()
        with self._call_times_lock:
            self._call_times = [t for t in self._call_times if now - t < 60]
            over_limit = len(self._call_times) >= 28
        if over_limit:
            time.sleep(5)

        try:
            msgs = [{"role": "system", "content": system}] + messages
            r = _GROQ_CLIENT.post(
                "/chat/completions",
                json={
                    "model": model, "messages": msgs, "max_tokens": max_tokens,
                    "temperature": FRIDAY_VOICE_MODES.get(self.voice_mode, {}).get("temperature", 0.8),
                },
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            )
            if r.status_code == 429:
                # Fail fast and let think() fall through to Anthropic
                # immediately instead of blocking the request for 10s first
                # (same fix as JARVIS's core/llm/openai.py — a reactive
                # sleep-after-429 just delays the fallback that's already
                # about to happen). Not a health failure — Groq is reachable
                # and working, just rate-limited right now.
                print("[FRIDAY] Groq rate limited — falling back immediately")
                return None
            r.raise_for_status()
            self._call_times.append(time.time())
            content = r.json()["choices"][0]["message"]["content"]
            global _last_groq_success
            _last_groq_success = time.time()
            return {"content": content, "model": model, "provider": "groq"}
        except Exception as e:
            print(f"[FRIDAY] Groq error: {e}")
            global _last_groq_failure
            _last_groq_failure = time.time()
            return None

    def _call_anthropic(self, messages: list, system: str, model: str, max_tokens: int = 256) -> dict | None:
        if not ANTHROPIC_KEY:
            return None

        import budget_2 as budget
        if not budget.can_call():
            return None

        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=ANTHROPIC_KEY)
            r = client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages)
            budget.record_call(r.usage.output_tokens, model)
            global _last_anthropic_success
            _last_anthropic_success = time.time()
            return {"content": r.content[0].text, "model": model, "provider": "anthropic"}
        except Exception as e:
            print(f"[FRIDAY] Anthropic error: {e}")
            global _last_anthropic_failure
            _last_anthropic_failure = time.time()
            return None

    # ── Advanced reasoning (opt-in, endpoint-only — not wired into casual
    # chat triggers, same convention as JARVIS_V5's server/routes/
    # brain_enhancement.py: "none of this is auto-triggered by regular
    # chat, since most of it costs multiple LLM calls per invocation") ──────

    def deep_think(self, query: str, context: str = "") -> dict:
        """Multi-step reasoning before answering: understand -> reason
        -> answer. Three real LLM calls, so this is meaningfully slower
        and costs more than a normal think() — use it deliberately."""
        start = time.time()

        understanding = self._call_groq([
            {"role": "user", "content":
             f"What is actually being asked here? What do I need to know "
             f"to answer well?\n\nQuestion: {query}"}
        ], "You analyze questions carefully.", MODELS["fast"], max_tokens=400)

        reasoning = self._call_anthropic([
            {"role": "user", "content":
             f"Think through this step by step:\n{query}\n\n"
             f"What I understand about the question: "
             f"{understanding.get('content', '') if understanding else ''}\n\n"
             f"Context: {context[:500]}\n\n"
             f"Work through this carefully before answering."}
        ], FRIDAY_PERSONALITY, MODELS["deep"], max_tokens=800)

        final = self._call_anthropic([
            {"role": "user", "content":
             f"Question: {query}\n\n"
             f"Your reasoning: {reasoning.get('content', '') if reasoning else ''}\n\n"
             f"Now give the final answer. Clear. Direct. FRIDAY style."}
        ], FRIDAY_PERSONALITY, MODELS["deep"], max_tokens=600)

        ms = round((time.time() - start) * 1000)
        content = final.get("content", "") if final else ""

        return {
            "response": content,
            "reasoning": reasoning.get("content", "") if reasoning else "",
            "method": "chain_of_thought", "model": MODELS["deep"], "ms": ms,
        }

    def self_critique(self, query: str, initial_response: str) -> str:
        """FRIDAY critiques her own answer and improves it before handing
        it back — like reviewing your own work before submitting it."""
        critique = self._call_anthropic([
            {"role": "user", "content":
             f"You just answered this question:\nQ: {query}\nA: {initial_response}\n\n"
             f"Critique your answer:\n- Is it accurate?\n- Is it complete?\n"
             f"- Is it the best possible answer?\n- What's missing?\n\n"
             f"Then give an improved version.\n"
             f"Format: CRITIQUE: [critique]\nIMPROVED: [better answer]"}
        ], FRIDAY_PERSONALITY, MODELS["deep"], max_tokens=800)

        if not critique:
            return initial_response

        content = critique.get("content", "")
        if "IMPROVED:" in content:
            return content.split("IMPROVED:")[-1].strip()
        return initial_response

    def parallel_think(self, query: str) -> str:
        """Three angles generated simultaneously, then a judge step picks
        the strongest or synthesizes the best of each — inspired by how
        JARVIS's Mythos system cross-validates findings from multiple
        sources rather than trusting a single pass."""
        import concurrent.futures

        angles = [
            "Answer directly and practically — the most straightforward, "
            "actionable take.",
            "Answer analytically — consider edge cases, risks, and what "
            "could go wrong.",
            "Answer creatively — consider an unconventional angle others "
            "might miss.",
        ]

        def generate_angle(angle: str) -> str:
            result = self._call_groq([
                {"role": "user", "content": f"{angle}\n\nQuestion: {query}"}
            ], FRIDAY_PERSONALITY, MODELS["smart"])
            return result.get("content", "") if result else ""

        answers = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(generate_angle, a) for a in angles]
            for f in concurrent.futures.as_completed(futures, timeout=15):
                try:
                    text = f.result()
                    if text:
                        answers.append(text)
                except Exception:
                    pass

        if not answers:
            return ""
        if len(answers) == 1:
            return answers[0]

        judge = self._call_anthropic([
            {"role": "user", "content":
             f"Question: {query}\n\n"
             + "\n\n".join(f"Answer {i + 1}:\n{a}" for i, a in enumerate(answers))
             + "\n\nPick the strongest answer, or synthesize the best parts "
               "of each into one. Reply with ONLY the final answer text, "
               "nothing else."}
        ], FRIDAY_PERSONALITY, MODELS["deep"], max_tokens=600)

        return judge.get("content", "") if judge else answers[0]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_system(self, emotion_context: str = "") -> str:
        system = FRIDAY_PERSONALITY
        if emotion_context:
            system += f"\n\nEmotional context: {emotion_context}"
        if self.voice_mode == "coverage":
            system += ("\n\nYou are currently covering for JARVIS who is offline. "
                      "Acknowledge this if relevant. Be extra helpful.")
        mode_note = FRIDAY_VOICE_MODES.get(self.voice_mode, {}).get("system_note", "")
        if mode_note:
            system += f"\n\n{mode_note}"
        return system

    def _build_messages(self, query: str, context: str) -> list[dict]:
        messages = []
        if context:
            messages.append({"role": "user", "content": f"[Context]: {context[:500]}"})
            messages.append({"role": "assistant", "content": "Got it, I'll keep that in mind."})
        messages.append({"role": "user", "content": query})
        return messages

    def _clean(self, text: str) -> str:
        """Clean response for voice output."""
        if not text:
            return "Give me a second, boss."
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'`[^`]+`', '', text)
        text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
        text = re.sub(r'#{1,6}\s', '', text)
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def set_voice_mode(self, mode: str):
        if mode in FRIDAY_VOICE_MODES:
            self.voice_mode = mode

    def status(self) -> dict:
        return {
            "brain": "online", "voice_mode": self.voice_mode,
            "groq": bool(GROQ_API_KEY), "anthropic": bool(ANTHROPIC_KEY),
            "cache_size": len(self._response_cache),
        }


friday_brain = FridayBrain()
