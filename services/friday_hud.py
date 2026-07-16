"""services/friday_hud.py — AR widget queue for the FRIDAY HUD.

Backend code calls spawn_widget() whenever it wants the HUD to pop up an
overlay (a diagnostic readout, a vision-identify result, a data table).
The HUD frontend has no persistent connection to this Flask process (no
WebSocket — see server.py's polling comment), so widgets sit in an
in-memory queue until the page's poll loop picks them up via
GET /friday/hud/poll, which drains the queue on every call. Each widget
is delivered at most once; a widget nobody's HUD tab is open to receive
just expires unclaimed (MAX_AGE_SECONDS) rather than piling up forever.
"""
import itertools
import threading
import time

MAX_QUEUE = 20
MAX_AGE_SECONDS = 30  # a widget nobody polled for in 30s is stale, not queued forever

_lock = threading.Lock()
_queue: list[dict] = []
_id_counter = itertools.count(1)


def spawn_widget(widget_type: str, content: dict, audio_file: str | None = None) -> dict:
    """widget_type: 'text' | 'data' | 'image'. content is type-specific —
    see hud.html's renderWidget() for the exact shape each type expects."""
    widget = {
        "id": next(_id_counter),
        "type": widget_type,
        "content": content,
        "audio_file": audio_file,
        "ts": time.time(),
    }
    with _lock:
        _queue.append(widget)
        del _queue[:-MAX_QUEUE]  # drop oldest if the queue backs up unclaimed
    return widget


def drain_widgets() -> list[dict]:
    """Pops every currently-queued widget (delivered-once semantics) and
    drops anything past MAX_AGE_SECONDS as stale."""
    now = time.time()
    with _lock:
        pending, _queue[:] = _queue[:], []
    return [w for w in pending if now - w["ts"] <= MAX_AGE_SECONDS]
