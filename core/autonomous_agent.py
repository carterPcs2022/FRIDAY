"""core/autonomous_agent.py — FRIDAY acts without being asked. Monitors
run on their own schedules and alert (voice + push) when something
actually needs attention, deduped so the same thing doesn't repeat
within an hour."""
import os
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path

TASK_FILE = Path("memory/friday_tasks.json")
BILLS_FILE = Path("memory/friday_bills.json")


class AutonomousAgent:

    def __init__(self):
        self._running = False
        self._actions_taken = []

    def start(self):
        """Start all autonomous monitors."""
        self._running = True

        monitors = [
            ("battery_watch", self._battery_monitor, 60),
            ("task_staleness", self._task_staleness, 3600),
            ("relationship", self._relationship_check, 86400),
            ("meal_reminder", self._meal_reminder, 3600),
            ("sunday_brief", self._sunday_brief, 3600),
            ("weather_alert", self._weather_alert, 1800),
            ("news_spike", self._news_spike, 3600),
            ("hydration", self._hydration_check, 1800),
            ("movement", self._movement_reminder, 5400),
            ("bill_check", self._bill_check, 3600),
        ]

        for name, fn, interval in monitors:
            t = threading.Thread(
                target=self._run_monitor,
                args=(name, fn, interval),
                daemon=True
            )
            t.start()
            time.sleep(2)  # Stagger starts

        print("[FRIDAY Autonomous] All monitors started")

    def _run_monitor(self, name: str, fn, interval: int):
        """Run a monitor on its schedule."""
        time.sleep(30)  # Initial delay
        while self._running:
            try:
                fn()
            except Exception as e:
                print(f"[Autonomous:{name}] {e}")
            time.sleep(interval)

    # ── Battery monitor ──────────────────────────────────────────────────────
    def _battery_monitor(self):
        """FRIDAY notices your battery before you do. Alerts at 20% and 10%."""
        mac_url = os.getenv("MAC_BRIDGE_URL", "")
        if not mac_url:
            return
        try:
            import httpx
            r = httpx.get(f"{mac_url}/mac/battery", timeout=3)
            data = r.json()
            pct = int(data.get("battery", 100))

            if pct <= 10:
                self._alert("Boss, Mac battery at 10%. Plug in now.", priority="high")
            elif pct <= 20:
                self._alert(f"Mac battery at {pct}%, boss.", priority="normal")
        except Exception:
            pass

    # ── Task staleness ───────────────────────────────────────────────────────
    def _task_staleness(self):
        """FRIDAY flags tasks that have been sitting for 7+ days without progress."""
        try:
            import json
            if not TASK_FILE.exists():
                return
            tasks = json.loads(TASK_FILE.read_text())

            now = datetime.now()
            old_tasks = []
            for task in tasks:
                if task.get("done"):
                    continue
                added = task.get("added", "")
                if not added:
                    continue
                try:
                    age = (now - datetime.fromisoformat(added)).days
                    if age >= 7:
                        old_tasks.append(task)
                except Exception:
                    pass

            if old_tasks:
                names = ", ".join(t["task"][:30] for t in old_tasks[:3])
                self._alert(
                    f"Boss, {len(old_tasks)} tasks have been sitting for a week: {names}",
                    priority="normal"
                )
        except Exception:
            pass

    # ── Relationship check ───────────────────────────────────────────────────
    def _relationship_check(self):
        """FRIDAY notices when you haven't talked to important people in
        too long. Only runs once per day (interval=86400)."""
        try:
            from services.friday_relationships import relationships
            overdue = relationships.who_needs_attention()
            if not overdue:
                return

            worst = overdue[0]
            if worst["days_since"] >= 30:
                self._alert(
                    f"Boss, you haven't talked to {worst['name']} in {worst['days_since']} days.",
                    priority="normal"
                )
        except Exception:
            pass

    # ── Meal reminder ────────────────────────────────────────────────────────
    def _meal_reminder(self):
        """FRIDAY notices when it's mealtime and you haven't mentioned eating."""
        hour = datetime.now().hour
        MEAL_HOURS = {8: "breakfast", 13: "lunch", 19: "dinner"}

        if hour not in MEAL_HOURS:
            return

        meal = MEAL_HOURS[hour]
        key = f"meal_{meal}_{datetime.now().date()}"
        flag = Path(f"logs/.{key}")
        if flag.exists():
            return
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()

        self._alert(f"It's {meal} time, boss. Have you eaten?", priority="low")

    # ── Sunday weekly brief ──────────────────────────────────────────────────
    def _sunday_brief(self):
        """Every Sunday night FRIDAY auto-generates a week ahead brief and sends it."""
        now = datetime.now()
        if now.weekday() != 6:  # Not Sunday
            return
        if now.hour != 20:  # 8pm
            return

        key = f"sunday_brief_{now.date()}"
        flag = Path(f"logs/.{key}")
        if flag.exists():
            return
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()

        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Generate a Sunday evening week-ahead brief.\n"
            f"Today is {now.strftime('%A %B %d')}.\n\n"
            f"Include:\n"
            f"1. Mindset for the week\n"
            f"2. Top 3 priorities to focus on\n"
            f"3. One thing to let go of from last week\n\n"
            f"FRIDAY style. Warm but focused. Under 80 words."
        )
        brief = result.get("response", "")
        if brief:
            self._alert(brief, priority="normal", title="FRIDAY — Week Ahead")

    # ── Weather alert ────────────────────────────────────────────────────────
    def _weather_alert(self):
        """FRIDAY checks weather and alerts about significant changes."""
        try:
            import httpx
            r = httpx.get("https://wttr.in/?format=j1", timeout=5)
            data = r.json()
            current = data.get("current_condition", [{}])[0]
            feels = current.get("FeelsLikeF", "")
            desc = current.get("weatherDesc", [{}])[0].get("value", "")
            precip = float(current.get("precipMM", "0"))

            if precip > 5:
                self._alert(
                    f"Rain coming, boss. Currently {desc}, feels like {feels}°F.",
                    priority="low"
                )
        except Exception:
            pass

    # ── News spike detection ─────────────────────────────────────────────────
    def _news_spike(self):
        """FRIDAY alerts when something big happens in areas you care about.
        Only fires if truly significant."""
        try:
            from core.friday_brain import friday_brain
            from core.tools.web import search

            results = search("breaking major news AI technology", 3)
            if not results:
                return

            result = friday_brain.think(
                f"News check:\n"
                + "\n".join(f"- {r.get('title', '')}" for r in results[:3])
                + "\n\nIs any of this significant enough to interrupt the user? "
                  "Reply YES or NO and why in under 10 words."
            )
            response = result.get("response", "NO")
            if response.upper().startswith("YES"):
                title = results[0].get("title", "")
                self._alert(f"Boss, significant news: {title[:80]}", priority="normal")
        except Exception:
            pass

    # ── Hydration reminder ───────────────────────────────────────────────────
    def _hydration_check(self):
        """Every ~2 hours between 8am-10pm, nudge about water."""
        hour = datetime.now().hour
        if 8 <= hour <= 22:
            key = f"hydration_{datetime.now().date()}_{hour // 2}"
            flag = Path(f"logs/.{key}")
            if not flag.exists():
                flag.parent.mkdir(parents=True, exist_ok=True)
                flag.touch()
                self._alert("Don't forget to drink water, boss.", priority="low")

    # ── Movement reminder ────────────────────────────────────────────────────
    def _movement_reminder(self):
        """Remind to move roughly every 90 minutes (interval=5400)."""
        key = f"move_{datetime.now().date()}_{datetime.now().hour}"
        flag = Path(f"logs/.{key}")
        if flag.exists():
            return
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
        self._alert("You've been sitting a while, boss. Take a quick break.", priority="low")

    # ── Bill/subscription reminder ───────────────────────────────────────────
    def _bill_check(self):
        """Alerts within a few days of a bill's monthly due_day. _alert()'s
        own hour-based dedup keeps this from repeating more than once an
        hour even though this window can span several days."""
        try:
            import json
            if not BILLS_FILE.exists():
                return
            bills = json.loads(BILLS_FILE.read_text())
            today = datetime.now().day
            for bill in bills:
                if abs(bill.get("due_day", 0) - today) <= 2:
                    self._alert(
                        f"Boss, {bill['name']} is due soon. ${bill.get('amount', 0):.0f}",
                        priority="normal"
                    )
        except Exception:
            pass

    # ── Alert dispatcher ─────────────────────────────────────────────────────
    def _alert(self, message: str, priority: str = "normal", title: str = "FRIDAY"):
        """Send alert through all channels."""
        # Dedupe — don't repeat same alert within the hour.
        msg_key = message[:50]
        recent = [
            a for a in self._actions_taken
            if a.get("msg", "")[:50] == msg_key and time.time() - a.get("ts", 0) < 3600
        ]
        if recent:
            return

        self._actions_taken.append({"msg": message, "ts": time.time()})
        self._actions_taken = self._actions_taken[-100:]

        print(f"[FRIDAY Autonomous] {title}: {message}")

        try:
            from services.friday_voice import speak
            speak(message)
        except Exception:
            pass

        pushover_user = os.getenv("PUSHOVER_USER_KEY", "")
        pushover_token = os.getenv("PUSHOVER_APP_TOKEN", "")
        if pushover_user and pushover_token:
            try:
                import httpx
                httpx.post(
                    "https://api.pushover.net/1/messages.json",
                    data={
                        "token": pushover_token, "user": pushover_user,
                        "title": title, "message": message,
                        "priority": 1 if priority == "high" else 0,
                    }, timeout=5
                )
            except Exception:
                pass


autonomous = AutonomousAgent()
