"""tests/test_hud_status.py — core/app_state.py's overall_status().

Confirmed live via a HUD screenshot: a fully healthy system (0 threats,
normal CPU/RAM, friday_brain up, uptime 34m) still showed a red
"DEGRADED" status pill. Root cause: overall_status() returned "ONLINE"
(uppercase) while static/js/hud.js's pollState() does a case-sensitive
`d.status === 'online'` check -- which could never match, so the pill
fell through to "DEGRADED" on every single healthy poll, permanently.
CORE_STATUS two lines above already uses lowercase ("online"/"degraded");
overall_status() was the one outlier.
"""
from unittest import mock

import core.app_state as app_state


class TestOverallStatusIsLowercase:
    """static/js/hud.js compares d.status against the literal lowercase
    strings below -- these must match exactly, or the HUD's status pill
    silently breaks again."""

    def test_healthy_brain_reports_lowercase_online(self):
        fake_brain = mock.Mock()
        fake_brain.status.return_value = {"groq": True, "anthropic": False}
        with mock.patch.object(app_state, "friday_brain", fake_brain):
            assert app_state.overall_status() == "online"

    def test_no_llm_configured_is_lowercase(self):
        fake_brain = mock.Mock()
        fake_brain.status.return_value = {"groq": False, "anthropic": False}
        with mock.patch.object(app_state, "friday_brain", fake_brain):
            assert app_state.overall_status() == "no-llm"

    def test_no_brain_at_all_is_lowercase(self):
        with mock.patch.object(app_state, "friday_brain", None):
            assert app_state.overall_status() == "emergency"

    def test_never_returns_the_old_uppercase_strings(self):
        """The exact regression: the HUD's `d.status === 'online'` check
        is case-sensitive, so anything but a bare lowercase "online"
        permanently shows the red DEGRADED pill regardless of real
        health."""
        fake_brain = mock.Mock()
        fake_brain.status.return_value = {"groq": True, "anthropic": True}
        with mock.patch.object(app_state, "friday_brain", fake_brain):
            assert app_state.overall_status() not in ("ONLINE", "NO-LLM", "EMERGENCY")
