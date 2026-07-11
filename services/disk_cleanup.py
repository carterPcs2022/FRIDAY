"""services/disk_cleanup.py — Render's disk isn't infinite, and nothing
in this repo ever deletes what it writes: voice mp3s pile up in static/,
logs/ grows without bound, and every dedup flag file
(logs/.{key}, e.g. core/autonomous_agent.py's hydration/movement
touch-files) sticks around forever once written. This periodically
clears out what's old enough to be safely gone.
"""
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
LOGS_DIR = BASE_DIR / "logs"

_HOUR = 3600
_DAY = 86400


def _age_seconds(path: Path) -> float:
    return time.time() - path.stat().st_mtime


def clean() -> dict:
    """Returns {"freed_bytes": int, "removed": [str, ...]}. Never raises —
    a cleanup sweep failing must not take down the monitor thread calling
    it."""
    freed = 0
    removed = []

    # Voice mp3s older than 1 hour — friday_voice.py's own naming
    # (friday_voice_<epoch_ms>.mp3), matched by prefix so this doesn't
    # sweep up anything else that might land in static/.
    try:
        for path in STATIC_DIR.glob("friday_voice_*.mp3"):
            try:
                if _age_seconds(path) > _HOUR:
                    size = path.stat().st_size
                    path.unlink()
                    freed += size
                    removed.append(str(path.relative_to(BASE_DIR)))
            except Exception:
                pass
    except Exception:
        pass

    # Logs older than 7 days — only real log files (jsonl etc.), not the
    # dedup flag files below (those are handled on their own, longer
    # retention since they're tiny and their age itself carries meaning
    # for anyone debugging why a monitor didn't fire).
    try:
        for path in LOGS_DIR.glob("*"):
            if path.is_dir() or path.name.startswith("."):
                continue
            try:
                if _age_seconds(path) > 7 * _DAY:
                    size = path.stat().st_size
                    path.unlink()
                    freed += size
                    removed.append(str(path.relative_to(BASE_DIR)))
            except Exception:
                pass
    except Exception:
        pass

    # Daily dedup flag files (logs/.hydration_2026-07-11_7,
    # logs/.move_2026-07-11_3, logs/.meal_breakfast_2026-07-11, etc.) —
    # empty touch files, harmless individually but they accumulate one
    # per monitor per day/hour forever with nothing else ever cleaning
    # them up.
    try:
        for path in LOGS_DIR.glob(".*"):
            if not path.is_file():
                continue
            try:
                if _age_seconds(path) > 30 * _DAY:
                    size = path.stat().st_size
                    path.unlink()
                    freed += size
                    removed.append(str(path.relative_to(BASE_DIR)))
            except Exception:
                pass
    except Exception:
        pass

    return {"freed_bytes": freed, "removed": removed}
