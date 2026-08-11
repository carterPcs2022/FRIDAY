"""services/backup.py — FRIDAY has no backup system for her own memory at
all today (confirmed: nothing beyond .gitignore touches memory/*.json).
A corrupted write or a bad deploy wiping the disk currently means losing
facts/conversations/profile/personal-memory/notes/trust history with no
way back. This periodically snapshots them and prunes old snapshots so
the backup directory itself doesn't grow unbounded.

Ported from JARVIS_V5's services/backup.py, generalized from JARVIS's
fixed 3-file list to FRIDAY's actual memory file set.
"""
import shutil
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
BACKUP_DIR = MEMORY_DIR / "backups"

# Every memory/*.json file FRIDAY actually writes to, across
# core/friday_memory.py, core/friday_training.py, and
# services/training_wheels.py. Missing files are skipped, not errors —
# a fresh install won't have friday_knowledge.json yet, for instance.
BACKED_UP_FILES = [
    "facts.json", "conversations.json", "emotional_log.json", "profile.json",
    "friday_personal.json", "friday_notes.json", "friday_knowledge.json",
    "friday_patterns.json", "training_wheels.json",
]


def backup_all() -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    # Microsecond resolution — second-only timestamps collide (and silently
    # overwrite each other) if backup_all() is ever called twice within the
    # same second, e.g. a manual trigger racing the daily autonomous one.
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    saved = []
    for name in BACKED_UP_FILES:
        src = MEMORY_DIR / name
        if src.exists():
            dst = BACKUP_DIR / f"{ts}_{name}"
            shutil.copy2(src, dst)
            saved.append(str(dst.relative_to(BASE_DIR)))
    prune()
    return {"backed_up": saved, "ts": ts}


def prune(keep: int = 10):
    """Keep the most recent `keep` snapshots per file, drop the rest."""
    if not BACKUP_DIR.exists():
        return
    for name in BACKED_UP_FILES:
        pattern = f"*_{name}"
        files = sorted(BACKUP_DIR.glob(pattern), reverse=True)
        for old in files[keep:]:
            old.unlink()


def restore(ts: str) -> dict:
    """Restore every memory/*.json file that has a snapshot at the given
    timestamp (as returned by backup_all()'s "ts"). Files with no
    matching snapshot are left untouched, not treated as an error —
    the caller may only want the timestamp that exists for some of them."""
    restored = []
    for name in BACKED_UP_FILES:
        src = BACKUP_DIR / f"{ts}_{name}"
        if src.exists():
            shutil.copy2(src, MEMORY_DIR / name)
            restored.append(name)
    return {"restored": restored, "ts": ts}


def status() -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    files = list(BACKUP_DIR.glob("*.json"))
    return {
        "backup_dir": str(BACKUP_DIR.relative_to(BASE_DIR)),
        "total_snapshots": len(files),
        "latest_ts": max((f.stat().st_mtime for f in files), default=0),
    }
