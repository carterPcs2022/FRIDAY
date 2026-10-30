"""Regression tests for signed Twilio phone callbacks.

These tests use Twilio's local RequestValidator only; they never contact
Twilio or send a real call/SMS.
"""
from flask import Flask, request
from twilio.request_validator import RequestValidator

from core import access_auth


def _signature(url, params, token):
    return RequestValidator(token).compute_signature(url, params)


def test_valid_twilio_signature_is_accepted(monkeypatch):
    token = "test-twilio-auth-token"
    public_url = "https://friday.example.com"
    path = "/friday/phone/sms"
    params = {"From": "+15551234567", "Body": "hello"}
    url = public_url + path
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", token)
    monkeypatch.setenv("PUBLIC_URL", public_url)

    app = Flask(__name__)
    with app.test_request_context(path, method="POST", data=params):
        signature = _signature(url, params, token)
        request.headers.environ["HTTP_X_TWILIO_SIGNATURE"] = signature
        assert access_auth.validate_twilio_webhook(request) is True


def test_missing_signature_is_rejected(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("PUBLIC_URL", "https://friday.example.com")
    app = Flask(__name__)
    with app.test_request_context("/friday/phone/call", method="POST"):
        assert access_auth.validate_twilio_webhook(request) is False


def test_invalid_signature_is_rejected(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("PUBLIC_URL", "https://friday.example.com")
    app = Flask(__name__)
    with app.test_request_context("/friday/phone/respond", method="POST"):
        request.headers.environ["HTTP_X_TWILIO_SIGNATURE"] = "not-a-valid-signature"
        assert access_auth.validate_twilio_webhook(request) is False


def test_missing_twilio_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("PUBLIC_URL", "https://friday.example.com")
    app = Flask(__name__)
    with app.test_request_context("/friday/phone/transcribed", method="POST"):
        request.headers.environ["HTTP_X_TWILIO_SIGNATURE"] = "anything"
        assert access_auth.validate_twilio_webhook(request) is False


def test_non_https_public_url_is_rejected(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("PUBLIC_URL", "http://friday.example.com")
    app = Flask(__name__)
    with app.test_request_context("/friday/phone/call", method="POST"):
        request.headers.environ["HTTP_X_TWILIO_SIGNATURE"] = "anything"
        assert access_auth.validate_twilio_webhook(request) is False


def test_query_string_is_included_in_signed_url(monkeypatch):
    token = "test-twilio-auth-token"
    public_url = "https://friday.example.com"
    path = "/friday/phone/call?source=twilio"
    params = {}
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", token)
    monkeypatch.setenv("PUBLIC_URL", public_url)
    app = Flask(__name__)
    with app.test_request_context(path, method="POST"):
        signature = _signature(public_url + path, params, token)
        request.headers.environ["HTTP_X_TWILIO_SIGNATURE"] = signature
        assert access_auth.validate_twilio_webhook(request) is True


def test_twilio_paths_are_not_normal_auth_exemptions():
    for path in access_auth.TWILIO_WEBHOOK_PATHS:
        assert access_auth.is_twilio_webhook(path)
        assert not access_auth.is_exempt(path)
