"""tests/test_config_validator_severity.py — config that is *off* isn't
config that is *broken*.

FRIDAY emailed a HIGH-priority "Config Check Failed" over a leftover
MAC_BRIDGE_TOKEN with no MAC_BRIDGE_URL. Nothing was wrong: with no URL
there is nothing to call, so the Mac bridge is simply disabled, which is
indistinguishable from never having set it up. That alert fired at every
boot -- and once the service stopped being spun down between requests,
every 30 minutes.

The two halves of a pair aren't equally broken:

  URL without token -> she calls it and fails to authenticate. Broken.
  token without URL -> nothing calls it. Off.

The second is worth seeing, not worth waking anyone for. An alert nobody
can act on is one they learn to ignore, which costs more than it's worth
the day a real one arrives.
"""
import importlib

import pytest

import core.config_validator as cv


@pytest.fixture
def env(monkeypatch):
    """Clean slate -- conftest clears credentials globally, and an access
    token so the unrelated FRIDAY_ACCESS_TOKEN issue doesn't mask the
    thing under test."""
    monkeypatch.setenv("FRIDAY_ACCESS_TOKEN", "test-token")
    for name in ("MAC_BRIDGE_URL", "MAC_BRIDGE_TOKEN", "HA_URL", "HA_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class TestAsymmetry:

    def test_token_without_url_is_a_note_not_an_issue(self, env):
        env.setenv("MAC_BRIDGE_TOKEN", "leftover-token")
        result = cv.check()

        assert result["ok"] is True, "a disabled integration failed the config check"
        assert not any("MAC_BRIDGE" in i for i in result["issues"])
        assert any("MAC_BRIDGE_TOKEN" in n for n in result["notes"]), (
            "the stray credential vanished entirely -- it should still be visible"
        )

    def test_url_without_token_is_still_a_real_issue(self, env):
        """The genuinely broken direction must keep alerting: she'll call
        the bridge and fail to authenticate."""
        env.setenv("MAC_BRIDGE_URL", "https://bridge.example.com")
        result = cv.check()

        assert result["ok"] is False
        assert any("MAC_BRIDGE_TOKEN isn't" in i for i in result["issues"])

    def test_both_set_is_clean(self, env):
        env.setenv("MAC_BRIDGE_URL", "https://bridge.example.com")
        env.setenv("MAC_BRIDGE_TOKEN", "real-token")
        result = cv.check()

        assert result["ok"] is True
        assert not any("MAC_BRIDGE" in n for n in result["notes"])

    def test_the_asymmetry_holds_for_every_pair(self, env):
        """Not special-cased to the Mac bridge -- the reasoning applies to
        every pair, so the behavior should too."""
        for url_key, token_key in cv._PAIRED_KEYS:
            env.delenv(url_key, raising=False)
            env.setenv(token_key, "some-value")
            result = cv.check()
            env.delenv(token_key, raising=False)

            assert not any(token_key in i for i in result["issues"]), (
                f"{token_key} without {url_key} alerted; it should only be a note"
            )


class TestAlertingKeysOffIssuesOnly:

    def test_a_note_alone_sends_no_alert(self, env, monkeypatch):
        env.setenv("MAC_BRIDGE_TOKEN", "leftover-token")
        sent = []
        import services.notifications as notif
        monkeypatch.setattr(notif, "alert", lambda *a, **k: sent.append(a))

        cv.check_and_alert()
        assert sent == [], "a note triggered an alert"

    def test_a_real_issue_still_alerts(self, env, monkeypatch):
        env.setenv("MAC_BRIDGE_URL", "https://bridge.example.com")
        sent = []
        import services.notifications as notif
        monkeypatch.setattr(notif, "alert", lambda *a, **k: sent.append(a))

        cv.check_and_alert()
        assert sent, "a genuinely broken config stopped alerting"


class TestShape:
    def test_check_returns_both_lists(self, env):
        result = cv.check()
        assert isinstance(result["issues"], list)
        assert isinstance(result["notes"], list)
