"""services/second_brain.py — stores ingested content with an
LLM-extracted summary/insights, recallable by keyword later.

Turso is the source of truth (Render's disk is ephemeral — see
db/turso_client.py's module docstring). Cache is hydrated from Turso
once at process start, then kept in sync write-through: every ingest()
updates the in-memory cache AND Turso immediately. The old local-JSON
path stays as a fallback for both hydrate and write — if Turso is
unconfigured or a call fails, this falls back to it rather than
hard-crashing ingestion."""
import json
import re
import hashlib
from pathlib import Path
from datetime import datetime

from db import turso_client

BRAIN_FILE = Path("memory/second_brain.json")
TURSO_TABLE = "second_brain"


class SecondBrain:

    def __init__(self):
        self._entries = self._hydrate()

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
        self._write_through(entry_id)
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

    # ── Turso (source of truth) with local-JSON fallback ────────────────────

    def _hydrate(self) -> dict:
        if turso_client.is_configured():
            try:
                return turso_client.kv_all(TURSO_TABLE)
            except Exception as e:
                print(f"[FRIDAY] Turso hydrate failed for second_brain, falling back to local JSON: {e}")
        return self._load_local()

    def _write_through(self, entry_id: str):
        if turso_client.is_configured():
            try:
                turso_client.kv_set(TURSO_TABLE, entry_id, self._entries[entry_id])
                return
            except Exception as e:
                print(f"[FRIDAY] Turso write failed for second_brain, falling back to local JSON: {e}")
        self._save_local()

    def _load_local(self) -> dict:
        if BRAIN_FILE.exists():
            try:
                return json.loads(BRAIN_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_local(self):
        BRAIN_FILE.parent.mkdir(parents=True, exist_ok=True)
        BRAIN_FILE.write_text(json.dumps(self._entries, indent=2))


second_brain = SecondBrain()
