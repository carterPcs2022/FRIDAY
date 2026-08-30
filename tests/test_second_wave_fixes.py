"""tests/test_second_wave_fixes.py — bugs found running a broader live
test batch (weather/news/goals/medicine/cross_check/second_brain/capability
map) after the first round of fixes was deployed.

Six things this pins down:

1. Goals had no Turso mirror -- a goal added mid-session was completely
   gone ("No goals tracked yet") after the container restarted, with no
   redeploy involved. Same bug class already fixed for Spotify/Gmail/
   Calendar tokens, never applied here.
2. Same bug, same fix, for medicine tracking: a medicine added and even
   logged as taken was gone after the same restart.
3. services/second_brain.py's ingest() surfaced raw, truncated JSON as
   the "summary" whenever the LLM extraction failed to parse -- confirmed
   live: "Stored: {\\"insights\\":[\\"User has an anniversary on June
   3rd\\",\\"User explicitly requests the system" (cut off mid-string).
4. services/cross_check.py's _judge() fed a placeholder error string
   ("(JARVIS returned 503)") to the model as if it were JARVIS's real
   answer and asked it to judge agreement -- confirmed live: scored
   "AGREE Both advise obtaining an independent specialist's opinion,"
   inventing an opinion JARVIS never gave.
5. core/friday_brain.py's _clean() turned an empty LLM completion into
   "Give me a second, boss." -- which reads as "still working on it,"
   but nothing was in flight and no follow-up was ever coming. Confirmed
   live on _cmd_travel.
6. core/friday_capabilities.py's LLM-backed "scan"/"detection" functions
   had no grounding instruction at all -- confirmed live: "run a critical
   scan" invented a fully specific, alarming fake medical emergency (SpO2
   84%, lactate 4.2, septic shock risk, recommend ICU transfer) with zero
   real data behind it. Also: CAPABILITY_MAP's "emergency contact" key
   was ordinary English with a real side effect (a genuine critical
   Pushover alert, no confirmation gate) -- renamed to a phrase nobody
   would type by accident.
"""
import time
from unittest import mock

import pytest

import server


class TestGoalsSurviveARestart:
    @pytest.fixture
    def configured(self, monkeypatch, tmp_path):
        import services.friday_goals as goals_mod
        monkeypatch.setattr(goals_mod, "GOALS_FILE", tmp_path / "goals.json")
        monkeypatch.setattr(goals_mod.turso, "is_configured", lambda: False)
        return goals_mod

    def test_a_new_goal_is_mirrored_to_turso_on_save(self, configured, monkeypatch):
        written = {}
        monkeypatch.setattr(configured.turso, "is_configured", lambda: True)
        monkeypatch.setattr(configured.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            configured.turso, "kv_set",
            lambda table, key, data: written.update({"table": table, "key": key, "data": data}),
        )
        monkeypatch.setattr(configured.turso, "kv_get", lambda table, key: None)

        tracker = configured.GoalTracker()
        tracker.add_goal("Read 12 books this year")

        assert written["data"]
        assert any(g["name"] == "Read 12 books this year" for g in written["data"].values())

    def test_a_goal_survives_when_local_disk_is_gone(self, configured, monkeypatch):
        """The actual scenario: process restarts, local file is gone
        (confirmed live -- no redeploy involved), but the goal was
        mirrored to Turso before the restart."""
        stored = {
            "goal_1": {"id": "goal_1", "name": "Read 12 books this year",
                       "status": "active", "sessions": 0}
        }
        monkeypatch.setattr(configured.turso, "is_configured", lambda: True)
        monkeypatch.setattr(configured.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(configured.turso, "kv_get", lambda table, key: stored)

        tracker = configured.GoalTracker()
        assert [g["name"] for g in tracker.get_active_goals()] == ["Read 12 books this year"]


class TestMedicineSurvivesARestart:
    @pytest.fixture
    def configured(self, monkeypatch, tmp_path):
        import services.friday_medicine as med_mod
        monkeypatch.setattr(med_mod, "MEDICINE_FILE", tmp_path / "medicine.json")
        monkeypatch.setattr(med_mod.turso, "is_configured", lambda: False)
        return med_mod

    def test_a_new_medicine_is_mirrored_to_turso_on_save(self, configured, monkeypatch):
        written = {}
        monkeypatch.setattr(configured.turso, "is_configured", lambda: True)
        monkeypatch.setattr(configured.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            configured.turso, "kv_set",
            lambda table, key, data: written.update({"data": data}),
        )
        monkeypatch.setattr(configured.turso, "kv_get", lambda table, key: None)

        tracker = configured.MedicineTracker()
        tracker.add_medicine("vitamin d", ["08:00"])

        assert any(m["name"] == "vitamin d" for m in written["data"].values())

    def test_a_medicine_survives_when_local_disk_is_gone(self, configured, monkeypatch):
        stored = {
            "med_1": {"id": "med_1", "name": "vitamin d", "times": ["08:00"],
                      "active": True, "log": []}
        }
        monkeypatch.setattr(configured.turso, "is_configured", lambda: True)
        monkeypatch.setattr(configured.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(configured.turso, "kv_get", lambda table, key: stored)

        tracker = configured.MedicineTracker()
        assert [m["name"] for m in tracker.get_active_medicines()] == ["vitamin d"]


class TestSecondBrainDoesNotLeakRawJson:
    def test_a_parse_failure_does_not_surface_broken_json_as_the_summary(self, monkeypatch):
        import services.second_brain as sb_mod

        brain = sb_mod.SecondBrain()
        monkeypatch.setattr(brain, "_entries", {})
        monkeypatch.setattr(brain, "_save", lambda entry_id: None)

        fake_brain = mock.Mock()
        # Truncated mid-string -- exactly the shape confirmed live.
        fake_brain.think.return_value = {
            "response": '{"insights":["User has an anniversary on June 3rd","User explicitly requests the system'
        }
        with mock.patch("core.friday_brain.friday_brain", fake_brain):
            result = brain.ingest("remember this: my anniversary is june 3rd")

        assert result["summary"] == ""
        assert "insights" not in result["summary"]


class TestCrossCheckDoesNotFabricateAgreement:
    @pytest.mark.parametrize("jarvis_answer", [
        "(JARVIS returned 503)",
        "(JARVIS isn't reachable — no JARVIS_API_TOKEN configured)",
        "(Couldn't reach JARVIS: timeout)",
        "(JARVIS returned no response)",
    ])
    def test_an_error_placeholder_is_not_judged_as_a_real_answer(self, jarvis_answer):
        from services.cross_check import cross_check

        with mock.patch("core.friday_brain.friday_brain") as fake_brain:
            result = cross_check._judge("get a second opinion", "seek a specialist", jarvis_answer)

        fake_brain.think.assert_not_called()
        assert result["aligned"] is None

    def test_two_real_answers_are_still_judged_normally(self):
        from services.cross_check import cross_check

        fake_brain = mock.Mock()
        fake_brain.think.return_value = {"response": "AGREE both say yes"}
        with mock.patch("core.friday_brain.friday_brain", fake_brain):
            result = cross_check._judge("q", "yes", "yes indeed")

        assert result["aligned"] is True

    def test_command_dispatcher_does_not_claim_alignment_it_never_checked(self, app):
        p = "get a second opinion"
        fake_cross_check = mock.Mock()
        fake_cross_check.ask_both.return_value = {
            "question": p, "friday": "seek a specialist",
            "jarvis": "(JARVIS returned 503)",
            "agreement": {"aligned": None, "note": "Couldn't compare"},
        }
        with app.test_request_context(), mock.patch("server.cross_check", fake_cross_check):
            result = server._cmd_cross_check(p, p.lower())

        response = result.get_json()["response"]
        assert "aligned" not in response.lower()
        assert "don't agree" not in response.lower()
        assert "couldn't reach jarvis" in response.lower()


class TestEmptyBrainResponseIsHonest:
    def test_an_empty_completion_does_not_promise_a_follow_up(self, app):
        from core.friday_brain import friday_brain

        response = friday_brain._clean("")
        assert response != "Give me a second, boss."
        assert "boss" in response.lower()


class TestCapabilityScansDoNotFabricateData:
    def test_critical_scan_tells_the_model_it_has_no_real_data(self):
        from core.friday_capabilities import friday_caps
        fake_brain = mock.Mock()
        fake_brain.think.return_value = {"response": "stable, boss"}
        with mock.patch("core.friday_brain.friday_brain", fake_brain), \
             mock.patch("services.friday_voice.speak", lambda *a, **k: None):
            friday_caps.critical_scan("current situation")
        prompt = fake_brain.think.call_args[0][0]
        assert "no real sensors" in prompt.lower()

    def test_emergency_contact_no_longer_fires_on_the_bare_phrase(self):
        from core.friday_capabilities import CAPABILITY_MAP
        assert "emergency contact" not in CAPABILITY_MAP
        assert "emergency contact protocol" in CAPABILITY_MAP

    def test_an_ordinary_question_about_an_emergency_contact_does_not_match(self):
        from core.friday_capabilities import CAPABILITY_MAP
        p = "who is my emergency contact"
        assert not any(t in p for t in CAPABILITY_MAP if "emergency" in t)
