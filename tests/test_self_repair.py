"""tests/test_self_repair.py — core/self_repair.py's diagnose -> propose
-> sandbox-test -> confirm-gated-apply pipeline.

attempt_repair()/confirm_repair() are tested with subprocess/LLM calls
mocked out at the seams (diagnose, propose_fix, _run_pytest,
subprocess.run) -- actually running the real test suite as a subprocess
from inside a test of that same suite would be slow, and self-referential
in a way that makes failures hard to reason about. The pure text-
processing helpers (_localize, _extract_snippet, _strip_fences) are
exercised directly against real sample text instead.

The single property every attempt_repair() test ultimately checks is the
one the whole module exists to guarantee: the live file is never written
to except through confirm_repair(), and confirm_repair() itself refuses
unless the live file still matches what was staged.
"""
import pytest
from unittest import mock

import core.self_repair as self_repair


@pytest.fixture(autouse=True)
def _reset_self_repair_state():
    """Module-level singletons (_gate, _pending_fixes, _last_token) mirror
    production's process-lifetime state -- reset around every test so
    none of them leak a token or a staged fix into the next test."""
    self_repair._pending_fixes.clear()
    self_repair._last_token = None
    self_repair._gate._pending.clear()
    yield
    self_repair._pending_fixes.clear()
    self_repair._last_token = None
    self_repair._gate._pending.clear()


SAMPLE_TRACEBACK = """\
============================= FAILURES =============================
_________________________ test_something ____________________________

    def test_something():
        result = friday_brain.think("hi")
>       assert result["response"] == "hi there"
E       AssertionError: assert 'hi' == 'hi there'

tests/test_brain.py:12: in test_something
    assert result["response"] == "hi there"
core/friday_brain.py:150: in think
    return self._instant_response(query)
E   AssertionError
"""


class TestLocalize:
    def test_finds_watched_component_frame(self):
        assert self_repair._localize(SAMPLE_TRACEBACK) == ("core/friday_brain.py", 150)

    def test_returns_none_when_no_watched_component_in_traceback(self):
        output = "tests/test_brain.py:12: in test_something\nE   AssertionError\n"
        assert self_repair._localize(output) is None

    def test_picks_deepest_matching_frame_when_multiple(self):
        output = (
            "core/friday_brain.py:10: in outer\n"
            "core/friday_brain.py:200: in inner\n"
            "E   AssertionError\n"
        )
        assert self_repair._localize(output) == ("core/friday_brain.py", 200)


class TestExtractSnippet:
    def test_extracts_window_around_line(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("\n".join(f"line {i}" for i in range(1, 51)))
        snippet, start, end = self_repair._extract_snippet(f, 25, window=5)
        assert (start, end) == (20, 30)
        assert "line 25" in snippet
        assert "line 19" not in snippet
        assert "line 31" not in snippet

    def test_clamps_window_at_file_boundaries(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("\n".join(f"line {i}" for i in range(1, 6)))
        snippet, start, end = self_repair._extract_snippet(f, 2, window=10)
        assert (start, end) == (1, 5)


class TestStripFences:
    def test_strips_markdown_fences(self):
        assert self_repair._strip_fences("```python\nx = 1\n```") == "x = 1"

    def test_leaves_plain_text_untouched(self):
        assert self_repair._strip_fences("x = 1") == "x = 1"


class TestDiagnose:
    def test_delegates_to_run_pytest_against_base_dir(self):
        with mock.patch("core.self_repair._run_pytest", return_value={"passed": True, "output": ""}) as run:
            result = self_repair.diagnose()
        run.assert_called_once_with(self_repair.BASE_DIR)
        assert result["passed"] is True


class TestAttemptRepair:
    def test_nothing_to_repair_when_suite_passes(self):
        with mock.patch("core.self_repair.diagnose", return_value={"passed": True, "output": ""}):
            result = self_repair.attempt_repair()
        assert result["status"] == "nothing_to_repair"

    def test_cannot_localize_when_failure_is_outside_watched_files(self):
        with mock.patch("core.self_repair.diagnose", return_value={
            "passed": False, "output": "tests/test_x.py:5: in test_x\nE   AssertionError",
        }):
            result = self_repair.attempt_repair()
        assert result["status"] == "cannot_localize"

    def test_propose_failed_is_surfaced_with_target_and_reason(self):
        with mock.patch("core.self_repair.diagnose", return_value={
                 "passed": False, "output": "core/friday_brain.py:10: in x\nE   Boom",
             }), \
             mock.patch("core.self_repair.propose_fix",
                         return_value={"ok": False, "reason": "no LLM provider available"}):
            result = self_repair.attempt_repair()
        assert result["status"] == "propose_failed"
        assert result["target"] == "core/friday_brain.py"
        assert result["reason"] == "no LLM provider available"

    def test_cannot_apply_safely_when_snippet_not_unique_in_live_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_repair, "BASE_DIR", tmp_path)
        (tmp_path / "core").mkdir()
        live_file = tmp_path / "core" / "friday_brain.py"
        live_file.write_text("dup\ndup\n")
        with mock.patch("core.self_repair.diagnose", return_value={
                 "passed": False, "output": "core/friday_brain.py:1: in x\nE   Boom",
             }), \
             mock.patch("core.self_repair.propose_fix", return_value={
                 "ok": True, "rel_path": "core/friday_brain.py",
                 "snippet": "dup", "fixed_snippet": "fixed", "start": 1, "end": 1, "model": "test",
             }):
            result = self_repair.attempt_repair()
        assert result["status"] == "cannot_apply_safely"
        assert live_file.read_text() == "dup\ndup\n"

    def test_sandbox_compile_failure_is_reported_and_live_file_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_repair, "BASE_DIR", tmp_path)
        (tmp_path / "core").mkdir()
        live_file = tmp_path / "core" / "friday_brain.py"
        live_file.write_text("return 1 / 0\n")

        with mock.patch("core.self_repair.diagnose", return_value={
                 "passed": False, "output": "core/friday_brain.py:1: in x\nE   Boom",
             }), \
             mock.patch("core.self_repair.propose_fix", return_value={
                 "ok": True, "rel_path": "core/friday_brain.py",
                 "snippet": "return 1 / 0", "fixed_snippet": "def(((invalid",
                 "start": 1, "end": 1, "model": "test",
             }):
            result = self_repair.attempt_repair()

        assert result["status"] == "sandbox_fix_invalid"
        assert live_file.read_text() == "return 1 / 0\n"

    def test_full_pipeline_stages_confirmation_when_sandbox_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_repair, "BASE_DIR", tmp_path)
        (tmp_path / "core").mkdir()
        live_file = tmp_path / "core" / "friday_brain.py"
        original = "def broken():\n    return 1 / 0\n"
        live_file.write_text(original)

        with mock.patch("core.self_repair.diagnose", return_value={
                 "passed": False, "output": "core/friday_brain.py:2: in broken\nE   ZeroDivisionError",
             }), \
             mock.patch("core.self_repair.propose_fix", return_value={
                 "ok": True, "rel_path": "core/friday_brain.py",
                 "snippet": "return 1 / 0", "fixed_snippet": "return 1",
                 "start": 2, "end": 2, "model": "test",
             }), \
             mock.patch("core.self_repair._run_pytest", return_value={"passed": True, "output": ""}), \
             mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stderr="")):
            result = self_repair.attempt_repair()

        assert result["status"] == "awaiting_confirmation"
        assert result["target"] == "core/friday_brain.py"
        assert result["confirm_token"]
        # The whole point: proving the fix in a sandbox never touches the live file.
        assert live_file.read_text() == original

    def test_sandbox_test_failure_is_reported_and_live_file_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_repair, "BASE_DIR", tmp_path)
        (tmp_path / "core").mkdir()
        live_file = tmp_path / "core" / "friday_brain.py"
        original = "return 1 / 0\n"
        live_file.write_text(original)

        with mock.patch("core.self_repair.diagnose", return_value={
                 "passed": False, "output": "core/friday_brain.py:1: in x\nE   Boom",
             }), \
             mock.patch("core.self_repair.propose_fix", return_value={
                 "ok": True, "rel_path": "core/friday_brain.py",
                 "snippet": "return 1 / 0", "fixed_snippet": "return 1 / 1",
                 "start": 1, "end": 1, "model": "test",
             }), \
             mock.patch("core.self_repair._run_pytest",
                         return_value={"passed": False, "output": "still broken"}), \
             mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stderr="")):
            result = self_repair.attempt_repair()

        assert result["status"] == "sandbox_fix_failed"
        assert live_file.read_text() == original


class TestConfirmRepair:
    def _stage_fix(self, rel_path="core/friday_memory.py", live_content="old", fixed_content="new"):
        token = self_repair._gate.request()["confirm_token"]
        self_repair._pending_fixes[token] = {
            "rel_path": rel_path, "live_content": live_content,
            "fixed_content": fixed_content, "snippet": live_content, "fixed_snippet": fixed_content,
        }
        self_repair._last_token = token
        return token

    def test_applies_fix_when_live_file_matches_staged_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_repair, "BASE_DIR", tmp_path)
        (tmp_path / "core").mkdir()
        live_file = tmp_path / "core" / "friday_memory.py"
        live_file.write_text("old")
        token = self._stage_fix(live_content="old", fixed_content="new")

        result = self_repair.confirm_repair(token)

        assert result == {"applied": True, "target": "core/friday_memory.py"}
        assert live_file.read_text() == "new"

    def test_defaults_to_most_recently_staged_token_when_none_given(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_repair, "BASE_DIR", tmp_path)
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "friday_memory.py").write_text("old")
        self._stage_fix(live_content="old", fixed_content="new")

        result = self_repair.confirm_repair()

        assert result["applied"] is True

    def test_rejects_unknown_or_expired_token(self):
        result = self_repair.confirm_repair("not-a-real-token")
        assert result == {"applied": False, "reason": "invalid or expired confirmation token"}

    def test_token_is_one_shot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_repair, "BASE_DIR", tmp_path)
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "friday_memory.py").write_text("old")
        token = self._stage_fix(live_content="old", fixed_content="new")

        first = self_repair.confirm_repair(token)
        second = self_repair.confirm_repair(token)

        assert first["applied"] is True
        assert second["applied"] is False

    def test_refuses_to_apply_if_live_file_changed_since_staging(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_repair, "BASE_DIR", tmp_path)
        (tmp_path / "core").mkdir()
        live_file = tmp_path / "core" / "friday_memory.py"
        live_file.write_text("changed by something else")
        token = self._stage_fix(live_content="old", fixed_content="new")

        result = self_repair.confirm_repair(token)

        assert result["applied"] is False
        assert "changed" in result["reason"]
        assert live_file.read_text() == "changed by something else"

    def test_no_pending_fix_reports_clearly(self):
        result = self_repair.confirm_repair()
        assert result == {"applied": False, "reason": "no pending self-repair fix"}
