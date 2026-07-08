"""core/friday_training.py — FRIDAY learns from JARVIS's knowledge base.
Not a copy — she absorbs what he knows about the user (facts, profile,
recent conversation shape) into her own memory, so she isn't starting
from zero the first time she has to cover for him.

Facts are stored directly rather than round-tripped through an LLM call
per fact (the source spec did this to phrase each one "in her own
words") — with no Groq key configured and a budget-capped Anthropic tier
(see budget_2.py), rephrasing every synced fact would burn real spend for
a purely cosmetic transform. The value here is having the knowledge at
all, not prose style on facts nobody reads directly.
"""
import json
import os
from pathlib import Path
from datetime import datetime

import httpx

JARVIS_URL = os.getenv("JARVIS_URL", "")
JARVIS_TOKEN = os.getenv("JARVIS_API_TOKEN", "")

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
FRIDAY_KNOWLEDGE_FILE = MEMORY_DIR / "friday_knowledge.json"
FRIDAY_PATTERNS_FILE = MEMORY_DIR / "friday_patterns.json"


class FridayTrainer:

    def __init__(self):
        self.knowledge = self._load_knowledge()
        self.patterns = self._load_patterns()

    def sync_from_jarvis(self) -> dict:
        """Pull facts/profile/recent-conversation-shape from JARVIS into
        FRIDAY's own knowledge base."""
        if not JARVIS_URL or not JARVIS_TOKEN:
            return {"error": "JARVIS not configured"}

        synced = {"facts": 0, "patterns": 0, "profile": False, "ts": datetime.now().isoformat()}
        headers = {"Authorization": f"Bearer {JARVIS_TOKEN}"}

        try:
            r = httpx.get(f"{JARVIS_URL}/stark/memory/facts", headers=headers, timeout=10)
            if r.status_code == 200:
                jarvis_facts = r.json().get("facts", [])
                self._absorb_facts(jarvis_facts)
                synced["facts"] = len(jarvis_facts)
        except Exception as e:
            print(f"[FridayTrainer] Facts sync failed: {e}")

        try:
            r = httpx.get(f"{JARVIS_URL}/stark/memory/profile", headers=headers, timeout=10)
            if r.status_code == 200:
                self._absorb_profile(r.json())
                synced["profile"] = True
        except Exception as e:
            print(f"[FridayTrainer] Profile sync failed: {e}")

        try:
            # Real shape: a bare list of {"user": ..., "ai": ...} dicts —
            # not {"conversations": [...]} with a "response" key.
            r = httpx.get(f"{JARVIS_URL}/stark/memory/recent", params={"n": 50}, headers=headers, timeout=10)
            if r.status_code == 200:
                convos = r.json()
                if isinstance(convos, list):
                    patterns = self._extract_patterns(convos)
                    synced["patterns"] = len(patterns)
        except Exception as e:
            print(f"[FridayTrainer] Patterns sync failed: {e}")

        self._save_knowledge()
        self._save_patterns()

        print(f"[FridayTrainer] Synced: {synced}")
        return synced

    def _absorb_facts(self, jarvis_facts: list):
        """Absorb JARVIS facts directly — dedup only, no LLM call per fact."""
        known = self.knowledge.setdefault("facts", [])
        known_originals = {f["original"] for f in known}

        for fact in jarvis_facts:
            if not fact or fact in known_originals:
                continue
            known.append({"original": fact, "ts": datetime.now().isoformat(), "source": "jarvis"})
            known_originals.add(fact)

        self.knowledge["facts"] = known[-1000:]

    def _absorb_profile(self, profile: dict):
        if not profile:
            return
        known_profile = self.knowledge.setdefault("profile", {})
        known_profile.update(profile)
        known_profile["synced_from_jarvis"] = True
        known_profile["sync_ts"] = datetime.now().isoformat()

        try:
            from core.friday_memory import update_profile
            for key, value in profile.items():
                if isinstance(value, (str, int, float, bool)):
                    update_profile(key, value)
        except Exception:
            pass

    def _extract_patterns(self, convos: list) -> list:
        """Extract (trigger, approach) pairs from JARVIS conversation shape
        ({"user": ..., "ai": ...}) so FRIDAY has a rough sense of how he
        handled similar requests before."""
        patterns = []
        for convo in convos[-50:]:
            query = convo.get("user", "")
            response = convo.get("ai", "")
            if not query or not response:
                continue
            patterns.append({"trigger": query[:100], "approach": response[:200], "ts": convo.get("ts", "")})

        self.patterns["jarvis_learned"] = patterns
        return patterns

    def get_context_brief(self, query: str) -> str:
        """Brief, relevant context from what FRIDAY has learned — cheap
        string matching, no LLM call."""
        facts = self.knowledge.get("facts", [])
        profile = self.knowledge.get("profile", {})
        patterns = self.patterns.get("jarvis_learned", [])

        if not facts and not profile:
            return ""

        q_words = {w for w in query.lower().split() if len(w) > 3}
        relevant = []
        for fact in facts[-100:]:
            text = fact.get("original", "").lower()
            if any(w in text for w in q_words):
                relevant.append(fact.get("original", ""))

        for p in patterns[-20:]:
            if any(w in p.get("trigger", "").lower() for w in q_words):
                relevant.append(f"Similar query handled before: {p['approach'][:100]}")

        profile_bits = []
        name = profile.get("name", "") or profile.get("preferred_name", "")
        if name:
            profile_bits.append(f"User: {name}")
        job = profile.get("job", "") or profile.get("role", "")
        if job:
            profile_bits.append(f"Role: {job}")

        parts = []
        if profile_bits:
            parts.append("Profile: " + ", ".join(profile_bits[:3]))
        if relevant:
            parts.append("Relevant knowledge: " + " | ".join(relevant[:3]))
        return "\n".join(parts)

    def _load_knowledge(self) -> dict:
        if FRIDAY_KNOWLEDGE_FILE.exists():
            try:
                return json.loads(FRIDAY_KNOWLEDGE_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _load_patterns(self) -> dict:
        if FRIDAY_PATTERNS_FILE.exists():
            try:
                return json.loads(FRIDAY_PATTERNS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_knowledge(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        FRIDAY_KNOWLEDGE_FILE.write_text(json.dumps(self.knowledge, indent=2))

    def _save_patterns(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        FRIDAY_PATTERNS_FILE.write_text(json.dumps(self.patterns, indent=2))

    def status(self) -> dict:
        return {
            "facts_learned": len(self.knowledge.get("facts", [])),
            "patterns_learned": len(self.patterns.get("jarvis_learned", [])),
            "profile_synced": self.knowledge.get("profile", {}).get("synced_from_jarvis", False),
            "last_sync": self.knowledge.get("profile", {}).get("sync_ts", "never"),
        }


friday_trainer = FridayTrainer()
