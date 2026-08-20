"""tests/test_env_wiring.py — regression coverage for four previously-
unused env vars (FRIDAY_NAME, FRIDAY_VERSION, FRIDAY_NEWS_INTERESTS,
FRIDAY_COVERAGE_VOICE_ID) that got wired in after the user noticed they
were declared but never read anywhere in the code.
"""
import importlib
from unittest import mock


class TestFridayNameAndVersion:
    def test_home_route_reflects_env_overrides(self, client, monkeypatch):
        monkeypatch.setattr("server.FRIDAY_NAME", "TONY")
        monkeypatch.setattr("server.FRIDAY_VERSION", "9.9")
        resp = client.get("/")
        assert resp.get_json()["status"] == "TONY V9.9 ONLINE"

    def test_home_route_default_unchanged(self, client, monkeypatch):
        monkeypatch.setattr("server.FRIDAY_NAME", "FRIDAY")
        monkeypatch.setattr("server.FRIDAY_VERSION", "2.0")
        resp = client.get("/")
        assert resp.get_json()["status"] == "FRIDAY V2.0 ONLINE"


class TestFridayNewsInterests:
    def test_env_override_is_parsed_and_trimmed(self, monkeypatch):
        monkeypatch.setenv("FRIDAY_NEWS_INTERESTS", "quantum computing, biotech ,  space travel")
        import services.friday_news as news
        importlib.reload(news)
        try:
            assert news.DEFAULT_INTERESTS == ["quantum computing", "biotech", "space travel"]
        finally:
            monkeypatch.delenv("FRIDAY_NEWS_INTERESTS", raising=False)
            importlib.reload(news)

    def test_unset_env_keeps_original_default_list(self, monkeypatch):
        monkeypatch.delenv("FRIDAY_NEWS_INTERESTS", raising=False)
        import services.friday_news as news
        importlib.reload(news)
        assert news.DEFAULT_INTERESTS == [
            "artificial intelligence", "Iron Man technology", "exoskeleton",
            "wearable tech", "robotics", "Anthropic", "tech startups", "SpaceX",
        ]


class TestNotificationsEmailUsesFridayName:
    def test_email_subject_uses_configured_name(self, monkeypatch):
        monkeypatch.setattr("services.notifications.FRIDAY_NAME", "TONY")
        with mock.patch("services.friday_gmail.friday_gmail.send_email", return_value={"ok": True}) as send, \
             mock.patch("services.friday_gmail.GMAIL_USER", "boss@example.com"):
            from services.notifications import _email
            _email("Battery critical", "5 percent remaining")
        send.assert_called_once_with(to="boss@example.com", subject="TONY: Battery critical", body="5 percent remaining")


class TestPhoneGreetingsUseFridayName:
    def test_incoming_call_greeting(self, monkeypatch):
        monkeypatch.setattr("services.friday_phone.FRIDAY_NAME", "TONY")
        from services.friday_phone import FridayPhone
        twiml = FridayPhone().handle_incoming_call()
        assert "it's TONY" in twiml
        assert "it's FRIDAY" not in twiml

    def test_alert_call_greeting(self, monkeypatch):
        monkeypatch.setattr("services.friday_phone.FRIDAY_NAME", "TONY")
        monkeypatch.setattr("services.friday_phone.TWILIO_SID", "sid")
        monkeypatch.setattr("services.friday_phone.TWILIO_TOKEN", "tok")
        monkeypatch.setattr("services.friday_phone.TWILIO_FROM", "+15550000000")

        captured = {}

        class FakeCalls:
            def create(self, **kw):
                captured.update(kw)
                class R:
                    sid = "CA123"
                    status = "queued"
                return R()

        class FakeClient:
            def __init__(self, *a, **k):
                self.calls = FakeCalls()

        with mock.patch("twilio.rest.Client", FakeClient, create=True):
            from services.friday_phone import FridayPhone
            FridayPhone().send_alert_call("battery is low", "+15551234567")

        assert "TONY here" in captured["twiml"]


class TestCoverageVoiceId:
    def test_coverage_mode_uses_coverage_voice_id(self, monkeypatch, tmp_path):
        import services.friday_voice as voice
        monkeypatch.setattr(voice, "ELEVENLABS_KEY", "fake-key")
        monkeypatch.setattr(voice, "FRIDAY_VOICE_ID", "normal-voice-id")
        monkeypatch.setattr(voice, "FRIDAY_COVERAGE_VOICE_ID", "coverage-voice-id")
        monkeypatch.setattr(voice, "STATIC_DIR", tmp_path)

        requested_urls = []

        class FakeResponse:
            status_code = 200
            content = b"fake-mp3-bytes"

        def fake_post(url, **kwargs):
            requested_urls.append(url)
            return FakeResponse()

        with mock.patch("httpx.post", fake_post):
            voice.speak("we're covering for JARVIS", mode="coverage")

        assert "coverage-voice-id" in requested_urls[0]
        assert "normal-voice-id" not in requested_urls[0]

    def test_normal_mode_uses_normal_voice_id(self, monkeypatch, tmp_path):
        import services.friday_voice as voice
        monkeypatch.setattr(voice, "ELEVENLABS_KEY", "fake-key")
        monkeypatch.setattr(voice, "FRIDAY_VOICE_ID", "normal-voice-id")
        monkeypatch.setattr(voice, "FRIDAY_COVERAGE_VOICE_ID", "coverage-voice-id")
        monkeypatch.setattr(voice, "STATIC_DIR", tmp_path)

        requested_urls = []

        class FakeResponse:
            status_code = 200
            content = b"fake-mp3-bytes"

        def fake_post(url, **kwargs):
            requested_urls.append(url)
            return FakeResponse()

        with mock.patch("httpx.post", fake_post):
            voice.speak("just a normal reply", mode="normal")

        assert "normal-voice-id" in requested_urls[0]

    def test_falls_back_to_normal_voice_when_coverage_id_unset(self, monkeypatch):
        monkeypatch.delenv("FRIDAY_COVERAGE_VOICE_ID", raising=False)
        monkeypatch.setenv("FRIDAY_VOICE_ID", "only-voice-id")
        import services.friday_voice as voice
        importlib.reload(voice)
        try:
            assert voice.FRIDAY_COVERAGE_VOICE_ID == "only-voice-id"
        finally:
            monkeypatch.delenv("FRIDAY_VOICE_ID", raising=False)
            importlib.reload(voice)
