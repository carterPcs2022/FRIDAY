"""services/second_brain.py — stores ingested content with an
LLM-extracted summary/insights, recallable by keyword later.

Turso is the read source of truth (dict keyed by entry id); local JSON
stays a write-through cache and fallback, matching
services/friday_habits.py and services/friday_relationships.py."""
import json
import re
import hashlib
from pathlib import Path
from datetime import datetime

from db import turso_http_client as turso

BRAIN_FILE = Path("memory/second_brain.json")
BRAIN_TABLE = "second_brain"


class SecondBrain:

    def __init__(self):
        self._entries = self._load()

    def ingest(self, content: str, source: str = "", tags: list | None = None) -> dict:
        from core.friday_brain import friday_brain

        tags = tags or []
        extraction = friday_brain.think(
            f"Extract from this content:\n{content[:3000]}\n\n"
            f"1. Key insights (3-5 points)\n"
            f"2. Action items\n"
            f"3. Key concepts\n"
            f"4. One sentence summary\n\n"
            f"Reply as JSON: {{insights, actions, concepts, summary}}",
        )["response"]

        try:
            clean = re.sub(r"```json|```", "", extraction).strip()
            data = json.loads(clean)
        except Exception:
            data = {"summary": extraction[:200], "insights": []}

        entry_id = hashlib.md5(content[:100].encode()).hexdigest()[:12]
        entry = {
            "id": entry_id, "content": content[:500], "source": source, "tags": tags,
            "summary": data.get("summary", ""), "insights": data.get("insights", []),
            "actions": data.get("actions", []), "concepts": data.get("concepts", []),
            "ts": datetime.now().isoformat(),
        }

        self._entries[entry_id] = entry
        self._save(entry_id)
        return {"id": entry_id, "summary": entry["summary"], "stored": True}

    def recall(self, query: str, limit: int = 5) -> list:
        q_words = set(query.lower().split())
        scored = []
        for entry in self._entries.values():
            score = 0
            text = (entry.get("summary", "") + " " + " ".join(entry.get("concepts", []))).lower()
            for word in q_words:
                if len(word) > 3 and word in text:
                    score += 1
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def recall_semantic(self, query: str, limit: int = 5) -> list:
        """Semantic variant of recall() — one LLM call over the last 30
        entries' summaries instead of keyword overlap, for queries that
        don't share literal words with what was stored (e.g. "that thing
        about scaling databases" matching an entry summarized as "Postgres
        read replicas"). recall() stays the fast keyword fallback since
        this costs a real LLM call and can't run for every lookup."""
        from core.friday_brain import friday_brain

        recent = list(self._entries.values())[-30:]
        if not recent:
            return []

        numbered = "\n".join(
            f"{i + 1}. {e.get('summary', '') or e.get('content', '')[:100]}"
            for i, e in enumerate(recent)
        )
        result = friday_brain.think(
            f"Here are numbered stored entries:\n{numbered}\n\n"
            f"Query: {query}\n\n"
            f"Which entry numbers are relevant to this query? Reply with "
            f"ONLY comma-separated numbers, most relevant first (e.g. "
            f"'3,1,7'). If none are relevant, reply 'none'."
        )["response"]

        numbers = [int(n) for n in re.findall(r"\d+", result)]
        matched = []
        seen = set()
        for n in numbers:
            idx = n - 1
            if 0 <= idx < len(recent) and idx not in seen:
                seen.add(idx)
                matched.append(recent[idx])
            if len(matched) >= limit:
                break
        return matched

    def get_actions(self, limit: int = 10) -> list:
        """Flattened action items pulled off recent entries — each
        returned as {"action": str, "source": entry id}, newest entries
        first."""
        actions = []
        for entry in sorted(self._entries.values(), key=lambda e: e.get("ts", ""), reverse=True):
            for action in entry.get("actions", []):
                actions.append({"action": action, "source": entry.get("id", "")})
                if len(actions) >= limit:
                    return actions
        return actions

    def daily_digest(self) -> str:
        from core.friday_brain import friday_brain

        recent = list(self._entries.values())[-10:]
        if not recent:
            return ""
        result = friday_brain.think(
            f"Daily digest from stored knowledge:\n"
            + "\n".join(f"- {e.get('summary', '')}" for e in recent)
            + "\n\nMost relevant today? Under 60 words. FRIDAY style."
        )
        return result["response"]

    def stats(self) -> dict:
        return {"entries": len(self._entries)}

    def _load(self) -> dict:
        if turso.is_configured():
            rows = None
            try:
                turso.ensure_kv_table(BRAIN_TABLE)
                rows = turso.kv_all(BRAIN_TABLE)
            except Exception as e:
                print(f"[Turso] second_brain read failed, falling back to local JSON: {e}")
            if rows:
                return rows
            if rows is not None:
                local = self._read_local()
                for entry_id, entry in local.items():
                    try:
                        turso.kv_set(BRAIN_TABLE, entry_id, entry)
                    except Exception as e:
                        print(f"[Turso] second_brain seed failed: {e}")
                return local
        return self._read_local()

    def _read_local(self) -> dict:
        if BRAIN_FILE.exists():
            try:
                return json.loads(BRAIN_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self, entry_id: str):
        BRAIN_FILE.parent.mkdir(parents=True, exist_ok=True)
        BRAIN_FILE.write_text(json.dumps(self._entries, indent=2))

        if turso.is_configured():
            try:
                turso.ensure_kv_table(BRAIN_TABLE)
                turso.kv_set(BRAIN_TABLE, entry_id, self._entries[entry_id])
            except Exception as e:
                print(f"[Turso] second_brain write failed, local JSON already has it: {e}")


second_brain = SecondBrain()
