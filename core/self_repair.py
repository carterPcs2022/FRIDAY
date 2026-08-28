"""core/self_repair.py — FRIDAY diagnosing and fixing her own bugs.

Complements core/veronica.py's backup-restore (for a file that's missing
or won't compile) with the case that can't handle: a component with a
genuine logic bug, still valid Python, still present. This runs the real
test suite, localizes a failing test to one of Veronica's watched
components, asks the LLM for a *minimal, localized* patch (not a
from-scratch rewrite of the whole file — see veronica.py's docstring for
why that's a real way to make an outage worse), proves the patch against
the real test suite inside an isolated sandbox copy of the repo, and only
if it passes there, stages it. The live file is never touched without a
human confirming — same ConfirmationGate token pattern already used for
HulkBuster deployment (core/permissions.py), chosen deliberately over
full autonomy for exactly the reason veronica.py already documents:
an unattended write to a core file is high blast radius and hard to
undo cleanly if the fix is subtly wrong.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from datetime import datetime

from core.permissions import ConfirmationGate
from core.veronica import FRIDAY_COMPONENTS, BASE_DIR

SELF_REPAIR_LOG = BASE_DIR / "logs" / "self_repair.jsonl"
SNIPPET_WINDOW = 15  # lines of context on each side of the failing frame

_gate = ConfirmationGate("Self-repair fix apply", window_seconds=600)
# ConfirmationGate itself only tracks yes/no tokens, not payloads (see
# core/permissions.py) -- the actual proposed fix has to live somewhere
# between "sandbox-tested" and "confirmed", so it's kept here, pruned in
# step with the gate's own token expiry.
_pending_fixes: dict = {}
_last_token: str | None = None


def _run_pytest(cwd: Path) -> dict:
    """Run the full suite inside cwd, stopping at the first failure --
    one bug fixed and verified at a time, not a batch of simultaneous
    speculative patches.

    `ran` distinguishes "the suite executed and something failed" from
    "the suite never executed at all". Confirmed live and the reason this
    exists: render.yaml installs requirements.txt, pytest lives in
    requirements-dev.txt, so on the deploy `python -m pytest` exits
    non-zero with "No module named pytest". That looked identical to a
    failing test, and since the ImportError traceback contains no watched
    component, every self-repair run on the deploy reported "Found a
    failing test but couldn't trace it back to one of my watched files"
    -- a phantom bug that doesn't exist, reported forever."""
    args = [sys.executable, "-m", "pytest", "-x", "--tb=short", "-q"]
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=180)
        output = (result.stdout + "\n" + result.stderr)[-8000:]
        # pytest itself exits 0 (pass) or 1 (tests failed); anything else,
        # or a missing module, means the run never really happened.
        ran = ("No module named pytest" not in output
               and result.returncode in (0, 1))
        return {
            "passed": result.returncode == 0,
            "ran": ran,
            "returncode": result.returncode,
            "output": output,
        }
    except Exception as e:
        return {"passed": False, "ran": False, "returncode": -1, "output": str(e)}


def diagnose() -> dict:
    """Run the full suite against the live repo. passed=True means
    nothing to repair right now."""
    return _run_pytest(BASE_DIR)


def _localize(output: str) -> tuple[str, int] | None:
    """Find the deepest traceback frame that lands in one of Veronica's
    watched components. pytest's --tb=short prints one 'path:lineno: in
    func' line per stack frame, outermost first -- the LAST match against
    a watched file is the frame closest to the actual bug. Returns
    (rel_path, lineno) or None if the failure isn't in a watched file
    (e.g. a bug purely inside the test itself)."""
    watched = set(FRIDAY_COMPONENTS.values())
    frames = re.findall(r"^(\S+\.py):(\d+): in \S+", output, re.MULTILINE)
    hit = None
    for path, lineno in frames:
        if path in watched:
            hit = (path, int(lineno))
    return hit


def _extract_snippet(path: Path, lineno: int, window: int = SNIPPET_WINDOW) -> tuple[str, int, int]:
    lines = path.read_text().split("\n")
    start = max(1, lineno - window)
    end = min(len(lines), lineno + window)
    snippet = "\n".join(lines[start - 1:end])
    return snippet, start, end


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip("\n")


def propose_fix(rel_path: str, lineno: int, error_output: str) -> dict:
    """Ask the LLM for a minimal fix to the snippet around the failing
    frame -- never the whole file. Returns the snippet to replace and its
    proposed replacement; nothing is written anywhere yet."""
    from core.friday_brain import friday_brain, is_anthropic_healthy, is_groq_healthy, MODELS

    path = BASE_DIR / rel_path
    if not path.exists():
        return {"ok": False, "reason": f"{rel_path} does not exist"}

    snippet, start, end = _extract_snippet(path, lineno)
    system = (
        "You are fixing a bug in FRIDAY's own source code. You will be given "
        "a failing pytest traceback and one snippet of the file it points "
        "into. Return ONLY the corrected version of that exact snippet -- "
        "same scope, same surrounding structure, preserving exact "
        "indentation. Make the smallest change that fixes the failure. No "
        "markdown fences, no explanation, no line numbers, no extra text."
    )
    user = (
        f"Failing pytest output:\n{error_output[-4000:]}\n\n"
        f"Snippet from {rel_path}, lines {start}-{end}:\n\n{snippet}"
    )
    messages = [{"role": "user", "content": user}]

    result = None
    if is_anthropic_healthy():
        result = friday_brain._call_anthropic(messages, system, MODELS["deep"], max_tokens=2000)
    if not result and is_groq_healthy():
        result = friday_brain._call_groq(messages, system, MODELS["smart"], max_tokens=2000)
    if not result:
        return {"ok": False, "reason": "no LLM provider available"}

    fixed_snippet = _strip_fences(result["content"])
    if not fixed_snippet or fixed_snippet == snippet:
        return {"ok": False, "reason": "model returned no usable change"}

    return {
        "ok": True, "rel_path": rel_path, "snippet": snippet,
        "fixed_snippet": fixed_snippet, "start": start, "end": end,
        "model": result["model"],
    }


def _make_sandbox() -> Path:
    """A throwaway full copy of the repo so a proposed fix can be proven
    by actually running the test suite against it, with zero risk to the
    live process."""
    sandbox_dir = Path(tempfile.mkdtemp(prefix="friday_self_repair_"))
    shutil.copytree(
        BASE_DIR, sandbox_dir, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", "veronica_backups", "logs",
            "node_modules", ".pytest_cache", "*.db", "*.sqlite3",
        ),
    )
    return sandbox_dir


# A repair run takes as long as the whole test suite -- twice, when a fix
# reaches the sandbox stage. Gunicorn kills any worker still busy after
# its timeout (30s by default), so calling attempt_repair() straight from
# the request handler could never work on the deploy: confirmed live,
# every attempt ended in "[CRITICAL] WORKER TIMEOUT ... Error handling
# request POST /command", the worker was killed mid-run, and the HUD lost
# the connection and fell back to offline mode.
#
# The run itself was fine. It just can't be something a web request waits
# on, so it happens in a thread and the answer is collected afterwards.
_run_lock = threading.Lock()
_run_state: dict = {"running": False, "started_at": None, "result": None,
                    "finished_at": None}


def run_state() -> dict:
    """Snapshot of the background run, for the caller to report."""
    with _run_lock:
        return dict(_run_state)


def clear_run_state():
    """Drop a finished result once it's been reported, so the next ask
    starts a fresh run instead of replaying a stale answer. Deliberately
    won't discard a run that's still in flight."""
    with _run_lock:
        if not _run_state["running"]:
            _run_state.update(result=None, finished_at=None, started_at=None)


def start_background_repair() -> dict:
    """Kick off attempt_repair() off-request. Returns immediately with
    {"started": bool} -- False when one is already in flight, since two
    concurrent runs would fight over the same sandbox and staged fix."""
    with _run_lock:
        if _run_state["running"]:
            return {"started": False, "already_running": True,
                    "started_at": _run_state["started_at"]}
        _run_state.update(running=True, started_at=datetime.now().isoformat(),
                          result=None, finished_at=None)

    def _work():
        try:
            result = attempt_repair()
        except Exception as e:
            result = {"status": "crashed", "reason": repr(e)}
            _log({"type": "repair_crashed", "error": repr(e),
                  "ts": datetime.now().isoformat()})
        with _run_lock:
            _run_state.update(running=False, result=result,
                              finished_at=datetime.now().isoformat())

    threading.Thread(target=_work, daemon=True, name="friday-self-repair").start()
    return {"started": True}


def attempt_repair() -> dict:
    """Full pipeline: diagnose -> localize -> propose a minimal patch ->
    prove it in an isolated sandbox -> stage a confirmation request. Never
    touches the live file itself -- see confirm_repair().

    Blocking and slow by nature (it runs the suite). Call it via
    start_background_repair() from anything request-shaped."""
    diag = diagnose()
    if diag["passed"]:
        return {"status": "nothing_to_repair", "diagnose": diag}

    # Checked before localizing: a suite that never ran has no traceback
    # to localize, so this would otherwise fall through to
    # "cannot_localize" and blame a bug that doesn't exist.
    if not diag.get("ran", True):
        return {"status": "cannot_run_tests", "diagnose": diag}

    hit = _localize(diag["output"])
    if not hit:
        return {"status": "cannot_localize", "diagnose": diag}
    rel_path, lineno = hit

    proposal = propose_fix(rel_path, lineno, diag["output"])
    if not proposal["ok"]:
        return {"status": "propose_failed", "reason": proposal["reason"],
                "target": rel_path, "diagnose": diag}

    live_content = (BASE_DIR / rel_path).read_text()
    if live_content.count(proposal["snippet"]) != 1:
        return {"status": "cannot_apply_safely", "target": rel_path,
                "reason": "snippet is not uniquely present in the live file "
                          "(it may have changed since diagnosis)", "diagnose": diag}
    sandbox_content = live_content.replace(proposal["snippet"], proposal["fixed_snippet"], 1)

    sandbox_dir = _make_sandbox()
    try:
        (sandbox_dir / rel_path).write_text(sandbox_content)

        compile_check = subprocess.run(
            [sys.executable, "-m", "py_compile", str(sandbox_dir / rel_path)],
            capture_output=True, text=True, timeout=10,
        )
        if compile_check.returncode != 0:
            return {"status": "sandbox_fix_invalid", "target": rel_path,
                    "compile_error": compile_check.stderr, "diagnose": diag}

        sandbox_test = _run_pytest(sandbox_dir)
        if not sandbox_test["passed"]:
            return {"status": "sandbox_fix_failed", "target": rel_path,
                    "sandbox_test": sandbox_test, "diagnose": diag}

        result = _gate.request()
        token = result["confirm_token"]
        _pending_fixes[token] = {
            "rel_path": rel_path, "live_content": live_content,
            "fixed_content": sandbox_content,
            "snippet": proposal["snippet"], "fixed_snippet": proposal["fixed_snippet"],
        }
        global _last_token
        _last_token = token

        _log({"type": "repair_proposed", "target": rel_path, "token": token,
              "ts": datetime.now().isoformat()})
        return {
            "status": "awaiting_confirmation", "target": rel_path,
            "confirm_token": token, "expires_seconds": result["expires_seconds"],
            "fixed_snippet": proposal["fixed_snippet"], "model": proposal["model"],
            "diagnose": diag, "sandbox_test": sandbox_test,
        }
    finally:
        shutil.rmtree(sandbox_dir, ignore_errors=True)


def confirm_repair(token: str = None) -> dict:
    """Apply a previously sandbox-tested fix to the live file. token
    defaults to the most recently staged one so a voice/chat 'apply it'
    doesn't require reciting a hex string -- the token still exists to
    force an explicit second step and prevent replay, not as a secret
    (the whole route is already behind the normal auth gate)."""
    token = token or _last_token
    if not token:
        return {"applied": False, "reason": "no pending self-repair fix"}
    if not _gate.confirm(token):
        return {"applied": False, "reason": "invalid or expired confirmation token"}

    payload = _pending_fixes.pop(token, None)
    if payload is None:
        return {"applied": False, "reason": "confirmation token had no matching staged fix"}

    path = BASE_DIR / payload["rel_path"]
    try:
        current = path.read_text()
        if current != payload["live_content"]:
            return {"applied": False, "reason": "live file changed since the fix was staged — "
                                                   "run self-repair again"}
        path.write_text(payload["fixed_content"])
    except Exception as e:
        return {"applied": False, "reason": str(e)}

    # V3 Phase 13: writing without an exception isn't proof the write
    # landed correctly -- re-read the file and re-compile it. A mismatch
    # here (partial write, disk issue) rolls back to the pre-fix content
    # automatically rather than leaving a live core file in an unknown
    # state, same "never claim success solely because a call returned"
    # principle as everywhere else in this module.
    from core.verification_engine import verify_self_repair_apply

    verification = verify_self_repair_apply(path, payload["fixed_content"])
    if not verification.ok:
        try:
            path.write_text(payload["live_content"])
            rollback = "rolled back to the pre-fix content"
        except Exception as e:
            rollback = f"ROLLBACK ALSO FAILED: {e} — {payload['rel_path']} may be in a broken state, needs manual attention"
        _log({"type": "repair_verification_failed", "target": payload["rel_path"],
              "detail": verification.detail, "rollback": rollback, "ts": datetime.now().isoformat()})
        return {"applied": False, "verified": False,
                "reason": f"post-write verification failed: {verification.detail} ({rollback})"}

    _log({"type": "repair_applied", "target": payload["rel_path"], "ts": datetime.now().isoformat()})
    return {"applied": True, "verified": True, "target": payload["rel_path"]}


def _log(entry: dict):
    try:
        SELF_REPAIR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SELF_REPAIR_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
