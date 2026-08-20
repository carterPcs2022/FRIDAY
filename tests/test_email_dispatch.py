"""tests/test_email_dispatch.py — regression coverage for the
/friday/email/send partial-override dispatch bug found in today's
review pass.

send_draft(to=, body=) exists specifically so a caller can redirect or
tweak the pending draft without repeating the whole thing -- it fills in
whatever's missing from the stored draft. The route's original
`if to or body:` sent any partial input (just a new "to", or just a new
"body") straight to send_email() instead, which then failed on the half
that was never supplied rather than falling back to the draft. Fixed to
`if to and body:` -- only a fully-specified new email skips the draft.
"""
from unittest import mock

import pytest

from services.friday_gmail import friday_gmail


@pytest.fixture()
def mocked_send_methods():
    with mock.patch.object(friday_gmail, "send_draft", return_value={"ok": True, "via": "draft"}) as md, \
         mock.patch.object(friday_gmail, "send_email", return_value={"ok": True, "via": "direct"}) as me:
        yield md, me


def test_to_only_override_uses_pending_draft(client, mocked_send_methods):
    send_draft, send_email = mocked_send_methods
    resp = client.post("/friday/email/send", json={"to": "redirected@example.com"})
    assert resp.status_code == 200
    assert send_draft.called
    assert not send_email.called


def test_body_only_override_uses_pending_draft(client, mocked_send_methods):
    send_draft, send_email = mocked_send_methods
    resp = client.post("/friday/email/send", json={"body": "new body text"})
    assert resp.status_code == 200
    assert send_draft.called
    assert not send_email.called


def test_neither_field_uses_pending_draft(client, mocked_send_methods):
    send_draft, send_email = mocked_send_methods
    resp = client.post("/friday/email/send", json={})
    assert resp.status_code == 200
    assert send_draft.called
    assert not send_email.called


def test_fully_specified_email_sends_directly(client, mocked_send_methods):
    send_draft, send_email = mocked_send_methods
    resp = client.post(
        "/friday/email/send",
        json={"to": "a@b.com", "body": "full new email"},
    )
    assert resp.status_code == 200
    assert send_email.called
    assert not send_draft.called
