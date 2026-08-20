"""tests/test_hulkbuster.py — regression coverage for the HulkBuster
manual-deploy persistence bug found in today's review pass.

services/friday_security.py's automatic 3-threats-in-10-minutes
escalation path already persists a block via _persist_block() before
calling hulkbuster.deploy(). But deploy() itself -- reachable directly
via the /friday/hulkbuster/deploy route, or from core/veronica.py
detecting a tampered security file -- only added the IP to
friday_security's in-memory set, skipping persistence. A manually
deployed block would silently un-block itself on the next redeploy.
"""
from unittest import mock

from services.hulkbuster import hulkbuster
from services.friday_security import friday_security


def test_deploy_persists_the_ip_block():
    with mock.patch.object(friday_security, "_persist_block") as persist, \
         mock.patch("services.suit_lockdown.suit_lockdown"):
        hulkbuster.deploy("manual test", ip="9.9.9.9")

    persist.assert_called_once_with("9.9.9.9", "hulkbuster: manual test")


def test_deploy_without_ip_does_not_call_persist():
    with mock.patch.object(friday_security, "_persist_block") as persist, \
         mock.patch("services.suit_lockdown.suit_lockdown"):
        hulkbuster.deploy("manual test, no ip")

    assert not persist.called
