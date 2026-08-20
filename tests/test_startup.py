"""tests/test_startup.py — regression coverage for the BASE_DIR/
_ensure_memory() ordering bug found in today's review pass.

The blueprint split moved BASE_DIR into core/app_state.py, imported into
server.py via `from core.app_state import *`. _ensure_memory() was
briefly called *before* that import ran, so every directory it creates
silently failed with a caught NameError instead of actually being
created -- the failure was swallowed by _ensure_memory()'s own
try/except, so nothing about it looked wrong short of checking the
filesystem or the warning log.
"""
import os

from core.app_state import BASE_DIR

EXPECTED_DIRS = ("memory", "logs", "static", "veronica_backups", "logs/backups")


def test_base_dir_resolves_to_repo_root():
    assert BASE_DIR.name == "FRIDAY" or (BASE_DIR / "server.py").exists()


def test_startup_directories_exist_after_import(app):
    """`app` fixture forces server.py's import (and therefore its
    startup code, including _ensure_memory()) to have already run."""
    missing = [d for d in EXPECTED_DIRS if not (BASE_DIR / d).is_dir()]
    assert not missing, f"_ensure_memory() failed to create: {missing}"
