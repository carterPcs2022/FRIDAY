"""services/friday_goals.py — every task, every session, every piece of
work feeds into the goals FRIDAY tracks. She reports progress and
notices when you're drifting."""
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

from db import turso_http_client as turso

GOALS_FILE = Path("memory/friday_goals.json")
GOALS_TABLE = "friday_goals"
GOALS_KEY = "goals"


class GoalTracker:

    def __init__(self):
        self._goals = self._load()

    def add_goal(self, name: str, description: str = "",
                 target_date: str = "", milestones: list | None = None) -> dict:
        """Add a major goal FRIDAY will track. milestones defaults to
        None (not []) — a mutable default shared across every call that
        omits it would mean every such goal's "milestones" list is
        literally the same object; any future in-place mutation of one
        would silently corrupt all the others."""
        milestones = list(milestones) if milestones else []
        goal_id = f"goal_{len(self._goals) + 1}_{int(time.time())}"
        goal = {
            "id": goal_id, "name": name, "description": description,
            "target_date": target_date, "milestones": milestones,
            "completed_milestones": [], "progress_log": [],
            "created": datetime.now().isoformat(), "status": "active",
            "sessions": 0, "last_worked": None,
        }
        self._goals[goal_id] = goal
        self._save()
        return goal

    def log_progress(self, goal_id: str = "", work_done: str = "", auto_detect: bool = False) -> dict:
        if not goal_id and auto_detect:
            goal_id = self._auto_detect_goal(work_done)

        goal = self._goals.get(goal_id)
        if not goal:
            return {"error": "Goal not found"}

        entry = {
            "ts": datetime.now().isoformat(), "work": work_done[:200],
            "date": datetime.now().date().isoformat(),
        }
        goal.setdefault("progress_log", []).append(entry)
        goal["progress_log"] = goal["progress_log"][-100:]
        goal["sessions"] = goal.get("sessions", 0) + 1
        goal["last_worked"] = datetime.now().isoformat()
        self._save()

        return {"logged": True, "goal": goal["name"], "sessions": goal["sessions"]}

    def complete_milestone(self, goal_id: str, milestone: str) -> dict:
        goal = self._goals.get(goal_id)
        if not goal:
            return {"error": "Goal not found"}

        goal.setdefault("completed_milestones", []).append({
            "milestone": milestone, "completed": datetime.now().isoformat(),
        })
        self._save()

        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Celebrate this milestone completion:\n"
            f"Goal: {goal['name']}\nMilestone: {milestone}\n\n"
            f"One energetic sentence. FRIDAY style."
        )
        return {"celebrated": True, "message": result["response"]}

    def weekly_progress_report(self) -> str:
        from core.friday_brain import friday_brain
        active = {k: v for k, v in self._goals.items() if v.get("status") == "active"}
        if not active:
            return "No active goals tracked yet, boss."

        now = datetime.now()
        this_week = now - timedelta(days=7)

        goal_summaries = []
        for goal in active.values():
            recent_sessions = [
                p for p in goal.get("progress_log", [])
                if datetime.fromisoformat(p["ts"]) > this_week
            ]
            last_worked = goal.get("last_worked")
            if last_worked:
                days_since = (now - datetime.fromisoformat(last_worked)).days
                last_str = ("today" if days_since == 0 else
                           "yesterday" if days_since == 1 else f"{days_since} days ago")
            else:
                last_str = "never"

            goal_summaries.append(
                f"Goal: {goal['name']}\n"
                f"Sessions this week: {len(recent_sessions)}\n"
                f"Last worked: {last_str}\n"
                f"Total sessions: {goal.get('sessions', 0)}\n"
                f"Milestones done: {len(goal.get('completed_milestones', []))}"
            )

        result = friday_brain.think(
            f"Weekly goal progress report:\n\n"
            + "\n\n".join(goal_summaries)
            + "\n\nHonest assessment. What's on track? What's being neglected? "
              "One priority for next week.\nUnder 80 words. FRIDAY Sunday review style."
        )
        return result["response"]

    def get_active_goals(self) -> list:
        return [v for v in self._goals.values() if v.get("status") == "active"]

    def nudge_neglected(self) -> str:
        now = datetime.now()
        nudges = []
        for goal in self._goals.values():
            if goal.get("status") != "active":
                continue
            last = goal.get("last_worked")
            if not last:
                nudges.append(goal["name"])
                continue
            if (now - datetime.fromisoformat(last)).days >= 7:
                nudges.append(goal["name"])

        if not nudges:
            return ""

        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"These goals haven't been worked on this week:\n"
            + "\n".join(f"- {n}" for n in nudges[:3])
            + "\n\nGentle nudge. Not nagging. FRIDAY style. Under 20 words."
        )
        return result["response"]

    def _auto_detect_goal(self, text: str) -> str:
        """Detect which goal work relates to, matching against both name
        and description words (the source spec computed `desc` but never
        actually checked it — name-only matching means "worked on the
        HUD rendering" would never match a goal whose name is "JARVIS V5
        Complete" but whose description mentions "HUD")."""
        text_lower = text.lower()
        for goal_id, goal in self._goals.items():
            name = goal.get("name", "").lower()
            desc = goal.get("description", "").lower()
            words = [w for w in (name.split() + desc.split()) if len(w) > 3]
            if any(w in text_lower for w in words):
                return goal_id
        return ""

    def _load(self) -> dict:
        if turso.is_configured():
            row, query_ok = None, False
            try:
                turso.ensure_kv_table(GOALS_TABLE)
                row = turso.kv_get(GOALS_TABLE, GOALS_KEY)
                query_ok = True
            except Exception as e:
                print(f"[Turso] goals read failed, falling back to local JSON: {e}")

            if row is not None:
                return row
            if query_ok:
                local = self._read_local()
                if local:
                    try:
                        turso.kv_set(GOALS_TABLE, GOALS_KEY, local)
                    except Exception as e:
                        print(f"[Turso] goals seed failed: {e}")
                return local

        return self._read_local()

    def _read_local(self) -> dict:
        if GOALS_FILE.exists():
            try:
                return json.loads(GOALS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        GOALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        GOALS_FILE.write_text(json.dumps(self._goals, indent=2))

        if turso.is_configured():
            try:
                turso.ensure_kv_table(GOALS_TABLE)
                turso.kv_set(GOALS_TABLE, GOALS_KEY, self._goals)
            except Exception as e:
                print(f"[Turso] goals write failed, local JSON already has it: {e}")


goals = GoalTracker()


def init_default_goals():
    """Seeds the three starting goals on first run only — never
    overwrites/duplicates if goals already exist."""
    if not goals.get_active_goals():
        suit_goal = goals.add_goal(
            name="Iron Man Suit",
            description="Build a real Iron Man suit with JARVIS as the AI backbone",
            milestones=[
                "Arc reactor prop build (in progress)",
                "OBD-II driving training system",
                "Mac Bridge operational",
                "Biometric baseline complete",
                "First wearable component",
                "Full suit integration",
            ]
        )
        # Mac Bridge is genuinely done already — record it directly rather
        # than through complete_milestone() (that method also fires an LLM
        # "celebrate this" call, which is the wrong side effect for a
        # cold-start seed running at import time, not a real just-now event).
        goals._goals[suit_goal["id"]]["completed_milestones"].append({
            "milestone": "Mac Bridge operational", "completed": datetime.now().isoformat(),
        })
        goals._save()
        goals.add_goal(
            name="JARVIS V5 Complete",
            description="All JARVIS features operational and stable",
            milestones=[
                "Gmail connected", "Calendar connected",
                "Voice reactive globe", "Fine-tuning dataset complete",
            ]
        )
        goals.add_goal(
            name="FRIDAY Complete",
            description="FRIDAY fully operational as personal assistant",
            milestones=[
                "All features deployed", "Autonomous agent stable",
                "Gmail integrated", "Mac Bridge connected",
            ]
        )


init_default_goals()
