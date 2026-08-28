"""tests/test_suite_is_hermetic.py — the suite's result must not depend
on the environment it runs in.

core/self_repair.py runs this suite on the live deploy to diagnose
FRIDAY's own bugs, and the deploy has real credentials set. That broke
it in two ways at once:

  - With FRIDAY_ACCESS_TOKEN present, access_auth's gate returned 401
    before any /command test reached its handler, so
    test_lockdown_checked_before_mayday failed with KeyError: 'mode' --
    a test that passes on every developer machine and in CI.
  - With real-looking API keys present, other tests attempted real
    network calls and the run hung rather than finishing.

So "run a self repair" on the deploy reported "Found a failing test but
couldn't trace it back to one of my watched files" -- correct, honest,
and useless: the failing test was an artifact of the environment, not a
bug in FRIDAY.

A suite whose result depends on where it runs cannot be used to diagnose
anything. conftest.py now clears those variables before server.py is
imported; this file guards that it keeps doing so.
"""
import os

import pytest

import tests.conftest as conftest


class TestCredentialsAreClearedBeforeImport:

    @pytest.mark.parametrize("var", [
        "FRIDAY_ACCESS_TOKEN",   # the one that actually broke it
        "EMAIL_ADDRESS", "EMAIL_PASSWORD",
        "GOOGLE_GMAIL_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_ID",
        "GROQ_API_KEY", "ANTHROPIC_API_KEY",
        "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN",
    ])
    def test_credential_is_not_set_during_the_run(self, var):
        """If this fails, the suite is running against real credentials
        and its result no longer means what it says."""
        assert os.environ.get(var) in (None, ""), (
            f"{var} is set during the test run -- results are now "
            f"environment-dependent, which is what broke self-repair"
        )

    def test_the_access_gate_is_inactive(self):
        """The specific mechanism behind the original failure: with a
        token configured, every /command test gets 401 instead of
        reaching its handler."""
        import core.access_auth as access_auth
        assert access_auth.is_configured() is False, (
            "the access gate is live during tests -- /command tests will "
            "get 401 rather than reaching their handlers"
        )


class TestTheClearListStaysComplete:
    """The list is only useful if it keeps pace with the config the app
    actually reads."""

    def test_every_paired_credential_in_config_validator_is_cleared(self):
        """core/config_validator.py already enumerates the credentials
        this app treats as real config. Anything it pairs up but conftest
        doesn't clear is a future environment-dependent failure."""
        import core.config_validator as cv

        paired = {name for pair in cv._PAIRED_KEYS for name in pair}
        cleared = set(conftest._ENV_TO_CLEAR)
        missing = sorted(paired - cleared)

        assert not missing, (
            "config_validator treats these as real credentials but "
            f"conftest.py doesn't clear them: {missing}"
        )
