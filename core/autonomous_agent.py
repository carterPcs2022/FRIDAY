"""core/autonomous_agent.py — FRIDAY acts without being asked. Monitors
run on their own schedules and alert (voice + push) when something
actually needs attention, deduped so the same thing doesn't repeat
within an hour."""
import os
import time
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

TASK_FILE = Path("memory/friday_tasks.json")
BILLS_FILE = Path("memory/friday_bills.json")


class AutonomousAgent:

    def __init__(self):
        self._running = False
        self._actions_taken = []
        # 10 independent monitor threads all call _alert() on their own
        # schedules and can genuinely overlap in real time — without this,
        # two concurrent alerts racing on the read-slice-reassign below
        # could silently drop one's dedup entry.
        self._actions_lock = threading.Lock()
        self._mac_bridge_failures = 0

    def start(self):
        """Start all autonomous monitors."""
        self._running = True

        monitors = [
            ("battery_watch", self._battery_monitor, 300),
            ("task_staleness", self._task_staleness, 3600),
            ("relationship", self._relationship_check, 86400),
            ("meal_reminder", self._meal_reminder, 3600),
            ("sunday_brief", self._sunday_brief, 3600),
            ("weather_alert", self._weather_alert, 3600),
            ("news_spike", self._news_spike, 7200),
            ("hydration", self._hydration_check, 1800),
            ("movement", self._movement_reminder, 5400),
            ("bill_check", self._bill_check, 3600),
            ("email_check", self._email_check, 3600),
            ("meeting_prep", self._meeting_prep, 300),
            ("emotional_check", self._morning_emotional_check, 3600),
            ("goal_nudge", self._goal_nudge, 86400),
            ("calibration_check", self._calibration_check, 86400),
            ("mac_bridge_check", self._mac_bridge_check, 1800),
            ("disk_cleanup", self._disk_cleanup, 43200),
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
            # bridge.py's before_request auth reads the token from the
            # request body OR the Authorization header for every /mac/*
            # route uniformly — this was a bare GET with neither, so it
            # 401'd correctly (bridge.py wasn't inconsistent; this call
            # just never sent credentials at all).
            r = httpx.get(
                f"{mac_url}/mac/battery", timeout=3,
                headers={"Authorization": f"Bearer {os.getenv('MAC_BRIDGE_TOKEN', '')}"},
            )
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
        """Every Sunday night FRIDAY auto-generates a full weekly review
        (tasks completed/pending, journal entries, habit streaks) and
        sends it."""
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

        import json

        def _get_tasks() -> list:
            if not TASK_FILE.exists():
                return []
            try:
                return json.loads(TASK_FILE.read_text())
            except Exception:
                return []

        tasks = _get_tasks()
        week_tasks = []
        for t in tasks:
            if not t.get("done"):
                continue
            try:
                if (now - datetime.fromisoformat(t.get("completed", "1970-01-01"))).days < 7:
                    week_tasks.append(t)
            except Exception:
                pass
        pending_tasks = [t for t in tasks if not t.get("done")]

        journal_count = 0
        try:
            from services.friday_journal import journal
            journal_count = len(journal.recent_entries(7))
        except Exception:
            pass

        streaks = {}
        try:
            from services.friday_habits import habits
            streaks = habits.all_streaks()
        except Exception:
            pass

        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Weekly review — Sunday {now.strftime('%B %d')}:\n"
            f"Tasks completed this week: {len(week_tasks)}\n"
            f"Tasks still pending: {len(pending_tasks)}\n"
            f"Journal entries: {journal_count}\n"
            f"Active habit streaks: {streaks}\n\n"
            f"Generate a warm, honest weekly review. What went well? "
            f"What's pending? One thing to focus on next week?\n"
            f"Under 100 words. FRIDAY Sunday tone."
        )
        brief = result.get("response", "")
        if brief:
            self._alert(brief, priority="normal", title="FRIDAY — Weekly Review")

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

    # ── Quiet hours ───────────────────────────────────────────────────────────
    def _is_quiet_hours(self) -> bool:
        """Routine wellness nudges (hydration, movement) shouldn't wake the
        boss up or buzz his phone overnight — only these two opt in to this
        check, not every monitor, since health/security escalations (Mayday,
        critical health, lockdown alerts) are deliberately never silenced."""
        hour = datetime.now().hour
        return hour >= 23 or hour < 7

    # ── Hydration reminder ───────────────────────────────────────────────────
    def _hydration_check(self):
        """Every ~2 hours between 8am-10pm, nudge about water."""
        if self._is_quiet_hours():
            return
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
        if self._is_quiet_hours():
            return
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

    # ── Urgent email check ───────────────────────────────────────────────────
    def _email_check(self):
        try:
            from services.friday_gmail import friday_gmail
            if not friday_gmail:
                return
            urgent = friday_gmail.get_urgent()
            if urgent:
                subjects = ", ".join(e["subject"][:30] for e in urgent[:2])
                self._alert(f"Boss, urgent email: {subjects}", priority="normal")
        except Exception:
            pass

    # ── Meeting prep ─────────────────────────────────────────────────────────
    def _meeting_prep(self):
        """Real calendar-based prep when Google Calendar is connected —
        briefs on anything starting within 30 minutes, deduped per event
        (not just per message) so a 5-minute poll interval doesn't refire
        for the same meeting repeatedly during its prep window. Falls
        back to guessing off the task list when there's no calendar."""
        try:
            from services.friday_calendar import friday_calendar
            if friday_calendar and friday_calendar.is_connected():
                self._meeting_prep_from_calendar(friday_calendar)
                return
        except Exception:
            pass
        self._meeting_prep_from_tasks()

    def _meeting_prep_from_calendar(self, friday_calendar):
        upcoming = friday_calendar.get_upcoming(hours=1)
        now = datetime.now(timezone.utc)
        for event in upcoming:
            start_raw = event.get("start", "")
            if not start_raw:
                continue
            try:
                start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            except Exception:
                continue
            minutes_until = (start - now).total_seconds() / 60
            if not (0 <= minutes_until <= 30):
                continue

            key = f"meeting_prep_{event.get('id', event.get('title', ''))}"
            flag = Path(f"logs/.{key}")
            if flag.exists():
                continue
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.touch()

            from core.friday_brain import friday_brain
            result = friday_brain.think(
                f"Pre-meeting brief for: {event.get('title', 'meeting')}\n"
                f"Starting in {int(minutes_until)} minutes.\n\n"
                f"What should boss know going in? Under 20 words. FRIDAY briefing style."
            )
            if result.get("response"):
                self._alert(result["response"], title="FRIDAY — Meeting Prep", priority="normal")

            # Recognizance auto-trigger — only for meetings with attendees
            # (a solo blocked-off hold has no one to recon). Reuses the same
            # per-event flag file above rather than a second dedup key, so
            # the 5-minute poll can't refire this any more than the prep
            # brief itself can.
            attendees = event.get("attendees") or []
            if attendees:
                try:
                    from services.recognizance import recognizance
                    names = ", ".join(a.get("email", "") for a in attendees[:5] if a.get("email"))
                    recon = recognizance.scout(
                        f"Upcoming meeting '{event.get('title', 'meeting')}' with {names or 'attendees'}"
                    )
                    if recon.get("brief"):
                        self._alert(recon["brief"], title="FRIDAY — Recon", priority="normal")
                except Exception:
                    pass

    def _meeting_prep_from_tasks(self):
        """No calendar connected — best-effort guess off the task list.
        _alert()'s hour-based dedup keeps this from repeating more than
        once an hour."""
        try:
            import json
            if not TASK_FILE.exists():
                return
            tasks = json.loads(TASK_FILE.read_text())
            meeting_tasks = [
                t for t in tasks
                if any(w in t.get("task", "").lower()
                      for w in ["meeting", "call", "interview", "standup", "review", "sync"])
                and not t.get("done")
            ]
            if not meeting_tasks:
                return

            task = meeting_tasks[0]
            from core.friday_brain import friday_brain
            result = friday_brain.think(
                f"Pre-meeting brief for: {task['task']}\n\n"
                f"What should boss know going in? Under 20 words. FRIDAY briefing style."
            )
            if result.get("response"):
                self._alert(result["response"], title="FRIDAY — Meeting Prep", priority="normal")
        except Exception:
            pass

    # ── Morning emotional check-in ───────────────────────────────────────────
    def _morning_emotional_check(self):
        """Only at 8am, once per day."""
        if datetime.now().hour != 8:
            return
        key = f"emotional_check_{datetime.now().date()}"
        flag = Path(f"logs/.{key}")
        if flag.exists():
            return
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()

        try:
            from services.friday_continuity import continuity
            from server import _log
            followup = continuity.morning_emotional_check()
            if followup:
                _log("FRIDAY", followup, "emotional_followup")
        except Exception:
            pass

    # ── Weekly goal nudge ─────────────────────────────────────────────────────
    def _goal_nudge(self):
        """Only on Wednesdays, once per day."""
        if datetime.now().weekday() != 2:
            return
        key = f"goal_nudge_{datetime.now().date()}"
        flag = Path(f"logs/.{key}")
        if flag.exists():
            return
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()

        try:
            from services.friday_goals import goals
            nudge = goals.nudge_neglected()
            if nudge:
                self._alert(nudge, title="FRIDAY — Goals")
        except Exception:
            pass

    # ── Weekly calibration nudge ─────────────────────────────────────────────
    def _calibration_check(self):
        """Only on Mondays, once per day — surfaces the single oldest
        unresolved probability call (see PROBABILITY_TRIGGERS in
        server.py) so it actually gets checked against reality instead of
        accumulating unresolved forever."""
        if datetime.now().weekday() != 0:  # Not Monday
            return
        key = f"calibration_check_{datetime.now().date()}"
        flag = Path(f"logs/.{key}")
        if flag.exists():
            return
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()

        try:
            from services.friday_calibration import calibration
            unresolved = calibration.get_unresolved(days_old=7)
            if not unresolved:
                return
            oldest = unresolved[0]
            self._alert(
                f"Boss, you called {oldest['probability']}% on \"{oldest['question'][:60]}\" "
                f"a week ago — how'd that turn out?",
                title="FRIDAY — Calibration", priority="low"
            )
        except Exception:
            pass

    # ── Mac Bridge health ─────────────────────────────────────────────────────
    def _mac_bridge_check(self):
        """Same /mac/battery ping _battery_monitor already uses (the only
        Mac Bridge route this repo is known to poll) — a real GET/response
        cycle rather than just checking whether the URL is configured.
        Debounced to 2 consecutive failures before alerting so a single
        dropped request on an otherwise-fine bridge doesn't page anyone."""
        mac_url = os.getenv("MAC_BRIDGE_URL", "")
        if not mac_url:
            return
        try:
            import httpx
            r = httpx.get(
                f"{mac_url}/mac/battery", timeout=5,
                headers={"Authorization": f"Bearer {os.getenv('MAC_BRIDGE_TOKEN', '')}"},
            )
            ok = r.status_code == 200
        except Exception:
            ok = False

        if ok:
            self._mac_bridge_failures = 0
            return

        self._mac_bridge_failures += 1
        if self._mac_bridge_failures >= 2:
            self._alert("Boss, Mac Bridge isn't responding — checked twice now.", priority="high")
            self._mac_bridge_failures = 0  # avoid re-alerting every 30 min while still down

    # ── Disk cleanup ──────────────────────────────────────────────────────────
    def _disk_cleanup(self):
        """Old voice mp3s/logs/dedup flag files pile up on Render's disk
        with nothing else ever clearing them — see services/disk_cleanup.py.
        Only worth a log line if it actually freed something meaningful."""
        try:
            from services import disk_cleanup
            result = disk_cleanup.clean()
            if result.get("freed_bytes", 0) > 1_000_000:
                print(f"[FRIDAY Autonomous] disk_cleanup freed {result['freed_bytes'] / 1024 / 1024:.1f}MB "
                      f"({len(result.get('removed', []))} files)")
        except Exception:
            pass

    # ── Alert dispatcher ─────────────────────────────────────────────────────
    def _alert(self, message: str, priority: str = "normal", title: str = "FRIDAY"):
        """Send alert through all channels."""
        # Hold non-urgent alerts during an active focus session — server.py
        # owns _FOCUS_SESSION; imported at call time (not at module load)
        # since server.py starts this agent's thread from inside its own
        # startup code, so importing it back at module scope would be
        # circular.
        try:
            from server import _FOCUS_SESSION
            if _FOCUS_SESSION.get("active") and priority != "high":
                return
        except Exception:
            pass

        # Dedupe — don't repeat same alert within the hour. Check-then-
        # record has to be one atomic step: two monitor threads racing
        # through this with only the append protected (not the check)
        # could both pass the dedup test for the same message and both
        # alert.
        msg_key = message[:50]
        with self._actions_lock:
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
