"""tests/test_self_repair_cannot_run.py — "I couldn't run my tests" must
not be reported as "I found a failing test".

Confirmed live: "run a self repair" on the deploy answered "Found a
failing test but couldn't trace it back to one of my watched files."
Nothing was actually failing. render.yaml installs requirements.txt,
pytest lived only in requirements-dev.txt, so `python -m pytest` exited
non-zero with "No module named pytest" -- which _run_pytest read as a
test failure, and since an ImportError traceback contains no watched
component, _localize() found nothing and every run reported the same
phantom bug.

Two fixes, both covered here: `ran` distinguishes the two cases, and
pytest moved into requirements.txt so self-repair can actually work on
the one deploy that exists.
"""
from pathlib import Path
from unittest import mock

import core.self_repair as sr


class TestMissingPytestIsNotAFailingTest:

    def _fake_run(self, output, returncode):
        return mock.Mock(stdout=output, stderr="", returncode=returncode)

    def test_missing_pytest_is_reported_as_cannot_run(self):
        with mock.patch.object(sr.subprocess, "run",
                               return_value=self._fake_run("No module named pytest", 1)):
            result = sr._run_pytest(Path("."))

        assert result["passed"] is False
        assert result["ran"] is False

    def test_attempt_repair_says_cannot_run_not_cannot_localize(self):
        """The distinction that matters to the boss: one means "something
        is broken and I need help", the other means "I couldn't even
        look"."""
        with mock.patch.object(
            sr, "diagnose",
            return_value={"passed": False, "ran": False, "returncode": 1,
                          "output": "No module named pytest"},
        ):
            result = sr.attempt_repair()

        assert result["status"] == "cannot_run_tests"

    def test_a_genuine_failure_still_reports_normally(self):
        """The guard must not mask real failures -- a suite that ran and
        failed still goes down the localize path."""
        traceback = "server.py:42: in handler\n    assert False\nE  AssertionError"
        with mock.patch.object(sr.subprocess, "run",
                               return_value=self._fake_run(traceback, 1)):
            result = sr._run_pytest(Path("."))

        assert result["ran"] is True
        assert result["passed"] is False

    def test_a_passing_suite_is_still_a_passing_suite(self):
        with mock.patch.object(sr.subprocess, "run",
                               return_value=self._fake_run("342 passed", 0)):
            result = sr._run_pytest(Path("."))

        assert result["passed"] is True and result["ran"] is True


class TestSelfRepairCanActuallyRunOnTheDeploy:
    def test_pytest_is_a_production_dependency(self):
        """core/self_repair.py shells out to pytest, and render.yaml
        installs only requirements.txt -- without this the feature is
        permanently inert in the only environment it ships to."""
        reqs = Path(__file__).resolve().parent.parent / "requirements.txt"
        assert "pytest" in reqs.read_text()
