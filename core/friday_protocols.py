"""core/friday_protocols.py — what FRIDAY does when she can't reach JARVIS,
or the cloud, or anything at all. She never goes fully dark; she just
operates at whatever level of connectivity is actually available.

Range levels:
FULL     — JARVIS online, all capabilities
LIMITED  — JARVIS offline, FRIDAY standalone (Groq/Anthropic still up)
MINIMAL  — All cloud LLMs unreachable too
DARK     — Complete isolation, emergency responses only

check_range() takes an already-known JARVIS status instead of checking it
itself — server.py's existing JARVIS monitor loop already polls /health
every 30s to drive COVERAGE_MODE; a second independent poll here would
duplicate that traffic and risk the two ever disagreeing about whether
JARVIS is actually reachable. Groq/Anthropic reachability is still
checked here since nothing else in this codebase already does that.
"""
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime
from enum import Enum

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent

# Same handful of files JARVIS watches for Protocol 11, scoped to what
# FRIDAY actually has.
_WATCHED_FILES = ["server.py", "core/friday_brain.py", "core/emotional_intel.py", "core/friday_memory.py"]
_BASELINE_FILE = BASE_DIR / "memory" / "friday_baseline.json"


def _hash_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


class RangeLevel(Enum):
    FULL = "full"
    LIMITED = "limited"
    MINIMAL = "minimal"
    DARK = "dark"


PROTOCOL_LOG = BASE_DIR / "logs" / "friday_protocols.jsonl"

FRIDAY_PROTOCOLS = {
    1: {
        "name": "COVERAGE",
        "description": "JARVIS offline — FRIDAY assumes control",
        "trigger": "JARVIS health check fails",
        "actions": ["Switch to coverage voice mode", "Notify user via voice", "Log coverage start time"],
    },
    2: {
        "name": "STANDALONE",
        "description": "JARVIS offline and all cloud LLMs unreachable — local/cached only",
        "trigger": "Groq and Anthropic both unreachable",
        "actions": ["Switch to focused voice mode", "Rely on response cache", "Alert user to limited capability"],
    },
    3: {
        "name": "DARK MODE",
        "description": "Complete isolation — emergency responses only",
        "trigger": "All checks failed",
        "actions": ["Activate emergency response database", "Log status", "Await reconnection"],
    },
    4: {
        "name": "RECONNECTION",
        "description": "Partial connectivity restored",
        "trigger": "Range level improved but not yet FULL",
        "actions": ["Note reconnection", "Continue monitoring"],
    },
    5: {
        "name": "HANDOFF",
        "description": "JARVIS back online — transfer control",
        "trigger": "JARVIS health check passes after coverage",
        "actions": ["Brief JARVIS on coverage duration", "Return to normal voice mode"],
    },
    6: {
        "name": "OUT OF RANGE",
        "description": "Manual standby/cache-warming mode",
        "trigger": "Manual only — no automatic detection wired (would need location "
                   "data this app doesn't have access to)",
        "actions": ["Warm response cache for common queries"],
    },
    7: {
        "name": "EMERGENCY BRIEF",
        "description": "Summarize what happened while disconnected",
        "trigger": "Manual only — call after a DARK/MINIMAL period ends",
        "actions": ["Summarize recent conversation", "Speak a brief welcome-back"],
    },
    8: {
        "name": "INTEGRITY CHECK",
        "description": "Verify FRIDAY's own core files haven't changed unexpectedly",
        "trigger": "Manual, or scheduled alongside the daily JARVIS sync",
        "actions": ["Hash watched files", "Compare against baseline", "Auto-heal baseline on a multi-file deploy"],
    },
    9: {
        "name": "BUDGET ALERT",
        "description": "Warn when the daily Anthropic call/token budget is running low",
        "trigger": "Manual, or checked opportunistically from /command",
        "actions": ["Check budget_2.status()", "Speak + push a warning past 80% used"],
    },
}

EMERGENCY_RESPONSES = {
    "time": lambda: f"It's {datetime.now().strftime('%I:%M %p')}.",
    "date": lambda: datetime.now().strftime("%A, %B %d, %Y."),
    "status": lambda: "FRIDAY running in emergency mode. Limited connectivity.",
    "help": lambda: "Emergency mode active. I can answer time, date, and status.",
    "jarvis": lambda: "JARVIS is currently unreachable. I'm covering, boss.",
    "online": lambda: "Limited connectivity. Core systems operational.",
}


class FridayProtocols:

    def __init__(self):
        self.range_level = RangeLevel.FULL
        self.coverage_start = None
        self.reconnect_count = 0

    def check_range(self, jarvis_ok: bool) -> RangeLevel:
        """Called from server.py's existing JARVIS monitor loop with the
        JARVIS health result it already fetched — this only adds the
        Groq/Anthropic checks on top."""
        groq_ok = self._check_groq()
        anthropic_ok = self._check_anthropic()

        old_level = self.range_level

        if jarvis_ok and (groq_ok or anthropic_ok):
            self.range_level = RangeLevel.FULL
        elif not jarvis_ok and (groq_ok or anthropic_ok):
            self.range_level = RangeLevel.LIMITED
        elif jarvis_ok:
            # JARVIS reachable but both LLM clouds down — still meaningfully
            # degraded, not full dark isolation.
            self.range_level = RangeLevel.MINIMAL
        else:
            self.range_level = RangeLevel.DARK

        if old_level != self.range_level:
            self._on_range_change(old_level, self.range_level)

        return self.range_level

    def _on_range_change(self, old: RangeLevel, new: RangeLevel):
        transitions = {
            (RangeLevel.FULL, RangeLevel.LIMITED): (1, "JARVIS is offline. I've got you, boss. Running on my own systems."),
            (RangeLevel.FULL, RangeLevel.MINIMAL): (2, "JARVIS is up but my cloud brains are unreachable. Cached responses only for now."),
            (RangeLevel.LIMITED, RangeLevel.MINIMAL): (2, "Cloud connectivity limited. Switching to cached responses. I'll do what I can, boss."),
            (RangeLevel.MINIMAL, RangeLevel.DARK): (3, "All external systems unreachable. Dark mode active. Emergency responses only."),
            (RangeLevel.DARK, RangeLevel.MINIMAL): (4, "Partial connectivity restored."),
            (RangeLevel.DARK, RangeLevel.LIMITED): (4, "Partial connectivity restored."),
            (RangeLevel.MINIMAL, RangeLevel.LIMITED): (4, "Cloud connectivity back. JARVIS is still offline, but I'm running normally again."),
            (RangeLevel.LIMITED, RangeLevel.FULL): (5, "JARVIS is back online. Handing back over, boss."),
            (RangeLevel.MINIMAL, RangeLevel.FULL): (5, "Full connectivity restored. All systems back online."),
            (RangeLevel.DARK, RangeLevel.FULL): (5, "Everything's back. All systems online."),
        }

        key = (old, new)
        if key in transitions:
            protocol_num, message = transitions[key]
            self.run_protocol(protocol_num)
            try:
                from services.friday_voice import speak
                speak(message)
            except Exception:
                pass

        self._log_event({"type": "range_change", "from": old.value, "to": new.value})

    def run_protocol(self, number: int) -> dict:
        protocol = FRIDAY_PROTOCOLS.get(number)
        if not protocol:
            return {"error": f"Protocol {number} not found"}

        print(f"[FRIDAY Protocol {number}] {protocol['name']}")

        if number == 1:
            self._protocol_coverage()
        elif number == 2:
            self._protocol_standalone()
        elif number == 3:
            self._protocol_dark_mode()
        elif number == 4:
            self.reconnect_count += 1
        elif number == 5:
            self._protocol_handoff()
        elif number == 6:
            self._protocol_out_of_range()
        elif number == 7:
            self._protocol_emergency_brief()
        elif number == 8:
            return {**self._protocol_integrity_check(), "executed": number, "name": protocol["name"]}
        elif number == 9:
            return {**self._protocol_budget_alert(), "executed": number, "name": protocol["name"]}

        self._log_event({"type": "protocol_run", "protocol": number, "name": protocol["name"]})
        return {"executed": number, "name": protocol["name"]}

    def _protocol_coverage(self):
        self.coverage_start = datetime.now()
        try:
            from core.friday_brain import friday_brain
            friday_brain.set_voice_mode("coverage")
        except Exception:
            pass

    def _protocol_standalone(self):
        try:
            from core.friday_brain import friday_brain
            friday_brain.set_voice_mode("focused")
        except Exception:
            pass

    def _protocol_dark_mode(self):
        self._log_event({"type": "dark_mode_activated", "range": self.range_level.value})

    def _protocol_handoff(self):
        if not self.coverage_start:
            return
        duration = (datetime.now() - self.coverage_start).total_seconds() / 60
        try:
            httpx.post(
                f"{os.getenv('JARVIS_URL', '')}/stark/chat",
                json={"message": f"FRIDAY coverage report: you were offline for {duration:.0f} minutes. "
                                 f"FRIDAY handled all requests in coverage mode. All systems normal."},
                headers={"Authorization": f"Bearer {os.getenv('JARVIS_API_TOKEN', '')}"},
                timeout=5,
            )
        except Exception:
            pass

        self.coverage_start = None
        try:
            from core.friday_brain import friday_brain
            friday_brain.set_voice_mode("normal")
        except Exception:
            pass

    def _protocol_out_of_range(self):
        """Manual-only cache warm — see FRIDAY_PROTOCOLS[6]'s trigger note."""
        try:
            from core.friday_brain import friday_brain
            for q in ["what time is it", "status update", "any alerts", "what did I miss"]:
                try:
                    friday_brain.think(q)
                except Exception:
                    pass
        except Exception:
            pass

    def _protocol_emergency_brief(self):
        try:
            from core.friday_brain import friday_brain
            from core.friday_memory import get_recent_turns

            recent = get_recent_turns(10)
            if not recent:
                return

            brief = friday_brain.think(
                "Generate a quick reconnection brief. The user was out of range. "
                "Here's what happened while away:\n"
                + "\n".join(f"- {t.get('user', '')[:60]}: {t.get('friday', '')[:80]}" for t in recent)
                + "\n\nBrief summary in FRIDAY's voice. Under 50 words. Start with 'Welcome back, boss.'"
            )
            from services.friday_voice import speak
            speak(brief.get("response", "Welcome back, boss."))
        except Exception:
            pass

    def _protocol_integrity_check(self) -> dict:
        """Hash FRIDAY's own watched files and compare against a saved
        baseline. Same auto-heal reasoning as JARVIS's Protocol 11 (which
        had a real bug: with no auto-heal, every restart after a
        legitimate deploy re-flagged the same already-shipped changes as
        tampering forever) — more than half the watched files changing
        together reads as a deploy, not an attack, so the baseline
        rebuilds silently instead of alerting on it every time."""
        current = {f: _hash_file(BASE_DIR / f) for f in _WATCHED_FILES}

        baseline = {}
        if _BASELINE_FILE.exists():
            try:
                baseline = json.loads(_BASELINE_FILE.read_text())
            except Exception:
                baseline = {}

        if not baseline:
            _BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _BASELINE_FILE.write_text(json.dumps({"ts": datetime.now().isoformat(), "hashes": current}))
            return {"status": "baseline_created", "checked": len(current)}

        stored = baseline.get("hashes", {})
        changed = [f for f, h in current.items() if stored.get(f) and h and stored[f] != h]

        if len(changed) > len(_WATCHED_FILES) // 2:
            _BASELINE_FILE.write_text(json.dumps({"ts": datetime.now().isoformat(), "hashes": current}))
            print(f"[FRIDAY Protocol 8] Deployment detected — {len(changed)} file(s) changed together, baseline rebuilt")
            return {"status": "baseline_rebuilt", "checked": len(current), "modified": []}

        if changed:
            print(f"[FRIDAY Protocol 8] ⚠ {len(changed)} file(s) changed offline: {changed}")

        return {"status": "clean" if not changed else "MODIFIED", "checked": len(current), "modified": changed}

    def _protocol_budget_alert(self) -> dict:
        """Warn once the daily Anthropic budget (budget_2.py) is mostly
        used — not a hard block, just a heads-up before it runs out."""
        try:
            import budget_2 as budget
            status = budget.status()
        except Exception as e:
            return {"error": str(e)}

        calls_pct = status["calls"] / max(status["calls_limit"], 1)
        tokens_pct = status["output_tokens"] / max(status["output_tokens_limit"], 1)
        pct = max(calls_pct, tokens_pct)

        if pct >= 0.8:
            message = f"Boss, running low on API calls today — {pct:.0%} of budget used."
            try:
                from services.friday_voice import speak
                speak(message)
            except Exception:
                pass
            return {"status": "alert", "pct_used": round(pct, 2), **status}

        return {"status": "ok", "pct_used": round(pct, 2), **status}

    def emergency_response(self, query: str) -> str:
        """Zero-connectivity response — local lookup only."""
        q = query.lower()
        for key, fn in EMERGENCY_RESPONSES.items():
            if key in q:
                return fn()
        return "Running in emergency mode, boss. Limited to time, date, and status queries."

    def get_range_report(self) -> dict:
        return {
            "range_level": self.range_level.value,
            "coverage": self.coverage_start is not None,
            "coverage_start": self.coverage_start.isoformat() if self.coverage_start else None,
            "reconnects": self.reconnect_count,
            "protocols": list(FRIDAY_PROTOCOLS.keys()),
        }

    def _check_groq(self) -> bool:
        # Previously a live GET to .../v1/models on every check_range() call
        # (every 30s from server.py's JARVIS monitor loop, forever) — real
        # API traffic that had nothing to do with whether FRIDAY was
        # actually being used, and it was burning Groq's rate limit on its
        # own. FRIDAY already learns whether Groq/Anthropic are working
        # from every real chat call; reusing that instead of polling
        # separately.
        from core.friday_brain import is_groq_healthy
        return is_groq_healthy()

    def _check_anthropic(self) -> bool:
        from core.friday_brain import is_anthropic_healthy
        return is_anthropic_healthy()

    def _log_event(self, entry: dict):
        entry["ts"] = datetime.now().isoformat()
        try:
            PROTOCOL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(PROTOCOL_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


friday_protocols = FridayProtocols()
