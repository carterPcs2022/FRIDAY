"""services/hierarchical_planning.py — vision-to-next-action goal
decomposition. Ported from JARVIS_V5's core/hierarchical_planning.py; a
real gap FRIDAY didn't have — services/friday_goals.py tracks progress on
goals that already have milestones, but nothing turned a vague goal
("get in shape", "become a doctor") into those milestones in the first
place.

Calls friday_brain._call_anthropic() directly rather than think() — see
services/legal.py's docstring for why (think() truncates past ~400 chars,
which would mutilate a real hierarchy breakdown).
"""
from core.friday_brain import friday_brain, MODELS

_SYSTEM = "You are FRIDAY, a sharp, structured planning assistant."

LEVELS = ["vision", "annual", "monthly", "weekly", "daily", "next_action"]


def _call(prompt: str, max_tokens: int = 400) -> str:
    result = friday_brain._call_anthropic(
        [{"role": "user", "content": prompt}], _SYSTEM, MODELS["nuanced"], max_tokens=max_tokens,
    )
    if not result:
        return "Couldn't reach the model for this right now, boss — try again in a bit."
    return result["content"]


class HierarchicalPlanner:

    def plan(self, goal: str, depth: int = 4) -> dict:
        depth = max(1, min(depth, len(LEVELS)))
        hierarchy = {}
        context = f"Goal: {goal}"
        for level in LEVELS[:depth]:
            result = _call(
                f"{context}\n\nWhat are the {level} actions/goals? "
                f"Be specific. Each must serve the level above."
            )
            hierarchy[level] = result
            context += f"\n{level}: {result[:150]}"

        next_action = _call(
            f"Goal: {goal}\nPlan: {str(hierarchy)[:400]}\n\n"
            f"Single next physical action to take RIGHT NOW? One sentence.",
            max_tokens=100,
        )
        hierarchy["next_action"] = next_action
        return {"goal": goal, "hierarchy": hierarchy, "next_action": next_action}

    def plan_and_track(self, goal: str, depth: int = 4) -> dict:
        """plan() plus actually creating a tracked goal in
        services/friday_goals.py, seeded with milestones pulled from the
        weekly-level breakdown — the bridge between "what should the plan
        be" and "track my progress on it" that neither service alone
        provides."""
        result = self.plan(goal, depth)

        milestones = []
        for line in result["hierarchy"].get("weekly", "").split("\n"):
            item = line.strip("-• ").strip()
            if item:
                milestones.append(item)

        from services.friday_goals import goals
        tracked = goals.add_goal(
            name=goal, description=result["hierarchy"].get("vision", ""),
            milestones=milestones[:6],
        )
        result["tracked_goal_id"] = tracked["id"]
        return result

    def should_use(self, query: str) -> bool:
        return any(t in query.lower() for t in [
            "plan for", "how do i achieve", "roadmap", "break down my goal",
        ])


hierarchical = HierarchicalPlanner()
