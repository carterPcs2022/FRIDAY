"""tests/test_offline.py — routes/offline.py's server-side surface for
offline mode: serving the service worker from root scope, telling the
client where (if anywhere) the local model is configured, and the
aggregated read-only snapshot the client caches for offline lookup.

The actual offline experience (wllama running in a browser tab, the
service worker's cache-first/network-first logic, IndexedDB/localStorage
persistence) lives in static/js/ and can't be exercised by pytest --
no browser, no WASM runtime, no service worker environment here. What's
tested is the part that can be: the three Flask routes those scripts
depend on.
"""
from unittest import mock


class TestServiceWorkerRoute:
    def test_served_from_root_not_static(self, client):
        """Scope matters: a service worker served from /static/js/... only
        controls fetches under that path, which would never see navigation
        requests to /hud. Root-scoped is what makes the offline shell work
        at all."""
        resp = client.get('/service-worker.js')
        assert resp.status_code == 200

    def test_correct_mime_type(self, client):
        resp = client.get('/service-worker.js')
        assert 'javascript' in resp.content_type

    def test_sets_service_worker_allowed_header(self, client):
        resp = client.get('/service-worker.js')
        assert resp.headers.get('Service-Worker-Allowed') == '/'

    def test_body_matches_the_real_file_on_disk(self, client):
        import core.app_state as app_state
        on_disk = (app_state.BASE_DIR / 'static' / 'js' / 'service-worker.js').read_text()
        resp = client.get('/service-worker.js')
        assert resp.get_data(as_text=True) == on_disk


class TestOfflineConfig:
    def test_disabled_when_no_model_url_configured(self, client, monkeypatch):
        monkeypatch.setattr('routes.offline.OFFLINE_MODEL_URL', '')
        resp = client.get('/friday/offline/config')
        body = resp.get_json()
        assert body['enabled'] is False
        assert body['model_url'] == ''

    def test_enabled_when_model_url_configured(self, client, monkeypatch):
        monkeypatch.setattr('routes.offline.OFFLINE_MODEL_URL', 'https://example.com/friday.gguf')
        resp = client.get('/friday/offline/config')
        body = resp.get_json()
        assert body['enabled'] is True
        assert body['model_url'] == 'https://example.com/friday.gguf'

    def test_system_prompt_matches_the_finetune_training_data(self, client):
        """The model was fine-tuned on a specific system message (see
        friday_training_data.jsonl) -- drifting from it here would mean
        every offline reply runs against a prompt the model never saw
        during training."""
        resp = client.get('/friday/offline/config')
        body = resp.get_json()
        assert "You are FRIDAY, Tony Stark's autonomous Irish-accented AI assistant." in body['system_prompt']


class TestOfflineSnapshot:
    def test_aggregates_tasks_notes_events(self, client):
        with mock.patch('routes.offline.get_tasks', return_value=[{"task": "buy milk", "done": False}]), \
             mock.patch('core.friday_memory.get_notes', return_value=[{"content": "note one"}]), \
             mock.patch('routes.offline.friday_calendar') as cal:
            cal.get_upcoming.return_value = [{"title": "dentist", "start": "2026-01-01T10:00:00"}]
            resp = client.get('/friday/offline/snapshot')

        body = resp.get_json()
        assert body['tasks'] == [{"task": "buy milk", "done": False}]
        assert body['notes'] == [{"content": "note one"}]
        assert body['events'] == [{"title": "dentist", "start": "2026-01-01T10:00:00"}]

    def test_empty_events_when_calendar_unconfigured(self, client):
        with mock.patch('routes.offline.friday_calendar', None):
            resp = client.get('/friday/offline/snapshot')
        assert resp.get_json()['events'] == []

    def test_calls_calendar_with_a_wider_window_than_the_live_route_default(self, client):
        """/friday/calendar/upcoming defaults to 24h for a live lookup;
        the offline snapshot deliberately asks for more (48h) since it
        might not get synced again for a while."""
        with mock.patch('routes.offline.get_tasks', return_value=[]), \
             mock.patch('core.friday_memory.get_notes', return_value=[]), \
             mock.patch('routes.offline.friday_calendar') as cal:
            cal.get_upcoming.return_value = []
            client.get('/friday/offline/snapshot')
        cal.get_upcoming.assert_called_once_with(48)
