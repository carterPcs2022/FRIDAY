"""tests/test_self_repair_background.py — a repair run must not block the
request that starts it.

Confirmed live on the deploy, and the reason "run a self repair" never
worked there: attempt_repair() runs the whole test suite, gunicorn kills
any worker still busy after its timeout, and every attempt ended as

    [CRITICAL] WORKER TIMEOUT (pid:197)
    [ERROR] Error handling request POST /command
      ... self_repair.attempt_repair() -> diagnose() -> _run_pytest()

with the worker killed mid-run and the HUD dropping to offline mode. The
run itself was fine; it just can't be something a web request waits on.

Exercised with a real slow function and real threads rather than mocks,
since "does this return before the work finishes" is precisely the
property that mocking away would erase.
"""
import time
from unittest import mock

import core.self_repair as sr


class TestItReturnsBeforeTheWorkFinishes:

    def test_start_returns_immediately(self):
        sr.clear_run_state()
        with mock.patch.object(sr, "attempt_repair",
                               side_effect=lambda: (time.sleep(0.6),
                                                    {"status": "nothing_to_repair"})[1]):
            t0 = time.time()
            started = sr.start_background_repair()
            elapsed = time.time() - t0

            assert started["started"] is True
            # The whole point: the caller is free long before the work ends.
            assert elapsed < 0.2, f"start blocked for {elapsed:.2f}s"
            assert sr.run_state()["running"] is True

            for _ in range(40):
                time.sleep(0.05)
                if not sr.run_state()["running"]:
                    break
            state = sr.run_state()

        assert state["running"] is False
        assert state["result"]["status"] == "nothing_to_repair"
        sr.clear_run_state()

    def test_a_second_start_is_refused_while_one_is_running(self):
        """Two concurrent runs would fight over the same sandbox and the
        same staged fix."""
        sr.clear_run_state()
        with mock.patch.object(sr, "attempt_repair",
                               side_effect=lambda: (time.sleep(0.4), {"status": "x"})[1]):
            first = sr.start_background_repair()
            second = sr.start_background_repair()

            assert first["started"] is True
            assert second["started"] is False
            assert second["already_running"] is True

            for _ in range(40):
                time.sleep(0.05)
                if not sr.run_state()["running"]:
                    break
        sr.clear_run_state()

    def test_a_crash_is_captured_rather_than_lost_in_the_thread(self):
        """An exception in a daemon thread would otherwise vanish, leaving
        the run permanently "running" and the boss with no answer."""
        sr.clear_run_state()
        with mock.patch.object(sr, "attempt_repair",
                               side_effect=RuntimeError("pytest exploded")):
            sr.start_background_repair()
            for _ in range(40):
                time.sleep(0.05)
                if not sr.run_state()["running"]:
                    break
            state = sr.run_state()

        assert state["running"] is False, "a crash left the run stuck as running"
        assert state["result"]["status"] == "crashed"
        assert "pytest exploded" in state["result"]["reason"]
        sr.clear_run_state()


class TestClearing:

    def test_clearing_drops_a_reported_result(self):
        sr.clear_run_state()
        with mock.patch.object(sr, "attempt_repair", return_value={"status": "ok"}):
            sr.start_background_repair()
            for _ in range(40):
                time.sleep(0.05)
                if not sr.run_state()["running"]:
                    break
        assert sr.run_state()["result"] is not None
        sr.clear_run_state()
        assert sr.run_state()["result"] is None

    def test_clearing_will_not_discard_a_run_in_flight(self):
        sr.clear_run_state()
        with mock.patch.object(sr, "attempt_repair",
                               side_effect=lambda: (time.sleep(0.4), {"status": "x"})[1]):
            sr.start_background_repair()
            sr.clear_run_state()
            assert sr.run_state()["running"] is True, "cleared a run that was still going"
            for _ in range(40):
                time.sleep(0.05)
                if not sr.run_state()["running"]:
                    break
        sr.clear_run_state()
