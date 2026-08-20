"""tests/test_vad_js.py — runs tests/js/test_vad.js (a Node harness for
static/js/hud.js's Voice Activity Detection logic) as part of the regular
pytest suite. The VAD state machine itself (speech-start debouncing,
trailing-silence stop, no-speech give-up, max-duration cap) is pure JS
logic and genuinely testable outside a browser; real mic/speaker behavior
is not and needs hands-on testing in an actual browser.

Skips (doesn't fail) if node isn't on PATH, rather than blocking the rest
of the suite on an environment gap -- CI installs node explicitly (see
.github/workflows/tests.yml) so it runs there for real.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_hud_vad_state_machine():
    result = subprocess.run(
        ["node", str(REPO_ROOT / "tests" / "js" / "test_vad.js")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "ALL VAD TESTS PASSED" in result.stdout
