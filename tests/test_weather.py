"""tests/test_weather.py — get_weather_brief() gaining a location
(core/app_state.py) and the new _cmd_weather chat trigger (server.py)
that actually calls it. Previously "what's the weather" wasn't wired
into /command at all -- it fell through to the LLM, which just guessed
a plausible-sounding generic answer instead of a real one (confirmed on
the live deploy: asking about Florida's weather got a made-up seasonal
average, not real data). The old get_weather_brief() also had no way to
take a location -- it only ever geolocated the SERVER's own IP (Render's
datacenter), which is why a bare weather request was never wired up in
the first place: there was nothing honest to say without a place.
"""
from unittest import mock

import core.app_state as app_state
import server


class TestGetWeatherBrief:
    def test_explicit_location_is_used_in_the_url(self, monkeypatch):
        captured = {}

        def fake_get(url, **kwargs):
            captured['url'] = url
            return mock.Mock(status_code=200, text="Sunny +75F")

        monkeypatch.delenv("FRIDAY_HOME_LOCATION", raising=False)
        with mock.patch("httpx.get", fake_get):
            result = app_state.get_weather_brief("Miami")

        assert "Miami" in captured['url']
        assert result == "Sunny +75F"

    def test_falls_back_to_home_location_env_var(self, monkeypatch):
        captured = {}

        def fake_get(url, **kwargs):
            captured['url'] = url
            return mock.Mock(status_code=200, text="Clear +60F")

        monkeypatch.setenv("FRIDAY_HOME_LOCATION", "Malibu")
        with mock.patch("httpx.get", fake_get):
            result = app_state.get_weather_brief()

        assert "Malibu" in captured['url']
        assert result == "Clear +60F"

    def test_explicit_location_overrides_home_location_env_var(self, monkeypatch):
        captured = {}

        def fake_get(url, **kwargs):
            captured['url'] = url
            return mock.Mock(status_code=200, text="ok")

        monkeypatch.setenv("FRIDAY_HOME_LOCATION", "Malibu")
        with mock.patch("httpx.get", fake_get):
            app_state.get_weather_brief("Tokyo")

        assert "Tokyo" in captured['url']
        assert "Malibu" not in captured['url']

    def test_no_location_and_no_env_var_falls_back_to_bare_ip_lookup(self, monkeypatch):
        captured = {}

        def fake_get(url, **kwargs):
            captured['url'] = url
            return mock.Mock(status_code=200, text="ok")

        monkeypatch.delenv("FRIDAY_HOME_LOCATION", raising=False)
        with mock.patch("httpx.get", fake_get):
            app_state.get_weather_brief()

        assert captured['url'] == "https://wttr.in/?format=3"

    def test_non_200_returns_empty_string(self, monkeypatch):
        monkeypatch.delenv("FRIDAY_HOME_LOCATION", raising=False)
        with mock.patch("httpx.get", return_value=mock.Mock(status_code=503, text="")):
            assert app_state.get_weather_brief("Miami") == ""

    def test_request_failure_returns_empty_string_not_an_exception(self, monkeypatch):
        monkeypatch.delenv("FRIDAY_HOME_LOCATION", raising=False)
        with mock.patch("httpx.get", side_effect=RuntimeError("network down")):
            assert app_state.get_weather_brief("Miami") == ""


class TestCmdWeatherTrigger:
    def test_bare_weather_request_calls_with_no_location(self, app):
        with app.test_request_context(), \
             mock.patch("server.get_weather_brief", return_value="Sunny +75F") as brief, \
             mock.patch("server.VOICE_OK", False):
            result = server._cmd_weather("what's the weather", "what's the weather")
        assert result is not None
        assert result.get_json()["response"] == "Sunny +75F"
        brief.assert_called_once_with("")

    def test_weather_in_location_extracts_the_place(self, app):
        with app.test_request_context(), \
             mock.patch("server.get_weather_brief", return_value="Hot") as brief, \
             mock.patch("server.VOICE_OK", False):
            server._cmd_weather("friday what is the weather in florida", "friday what is the weather in florida")
        brief.assert_called_once_with("florida")

    def test_weather_for_location_extracts_the_place(self, app):
        with app.test_request_context(), \
             mock.patch("server.get_weather_brief", return_value="Cold") as brief, \
             mock.patch("server.VOICE_OK", False):
            server._cmd_weather("weather for new york", "weather for new york")
        brief.assert_called_once_with("new york")

    def test_strips_trailing_punctuation_from_extracted_location(self, app):
        with app.test_request_context(), \
             mock.patch("server.get_weather_brief", return_value="ok") as brief, \
             mock.patch("server.VOICE_OK", False):
            server._cmd_weather("weather in miami?", "weather in miami?")
        brief.assert_called_once_with("miami")

    def test_service_unreachable_gives_an_honest_answer_not_a_guess(self, app):
        with app.test_request_context(), \
             mock.patch("server.get_weather_brief", return_value=""), \
             mock.patch("server.VOICE_OK", False):
            result = server._cmd_weather("weather in miami", "weather in miami")
        body = result.get_json()
        assert "couldn't reach" in body["response"].lower()

    def test_returns_none_when_no_weather_trigger(self, app):
        with app.test_request_context(), mock.patch("server.get_weather_brief") as brief:
            result = server._cmd_weather("what time is it", "what time is it")
        assert result is None
        brief.assert_not_called()


class TestWeatherRoute:
    def test_route_passes_location_query_param_through(self, client):
        with mock.patch("routes.knowledge.get_weather_brief", return_value="Sunny") as brief:
            resp = client.get("/friday/weather?location=Miami")
        assert resp.get_json() == {"weather": "Sunny"}
        brief.assert_called_once_with("Miami")

    def test_route_defaults_to_empty_location(self, client):
        with mock.patch("routes.knowledge.get_weather_brief", return_value="") as brief:
            client.get("/friday/weather")
        brief.assert_called_once_with("")
