"""core/veronica.py — V.E.R.O.N.I.C.A., FRIDAY's self-repair monitor.

In Age of Ultron, Veronica was Tony's orbital satellite: she watched the
battle from above and, when a Hulkbuster part was destroyed, jettisoned
it and deployed a stored replacement. For FRIDAY: watches her own core
files, and if one goes missing or stops compiling, restores it from a
saved backup.

Deliberately does NOT do what the source spec for this asked for next:
asking an LLM to regenerate a broken file from scratch (with only ~2000
characters of the original as context) and writing the result straight
to the live file, unattended, every 5 minutes. That's the same
autonomous-self-modification risk already gated behind mandatory human
approval in JARVIS's self-programming sandbox (core/sandbox.py /
core/self_improvement.py over there) — a "repair" that's actually an LLM
guessing at a replacement for a file it can't see all of, deployed with
zero review, is a real way to make an outage worse, not better. If a
component breaks and there's no backup to restore, this alerts instead
of improvising one.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
VERONICA_DIR = BASE_DIR / "veronica_backups"
VERONICA_LOG = BASE_DIR / "logs" / "veronica.jsonl"
BASELINE_FILE = VERONICA_DIR / "baseline_hashes.json"

FRIDAY_COMPONENTS = {
    "brain": "core/friday_brain.py",
    "memory": "core/friday_memory.py",
    "personality": "config/friday_personality.py",
    "protocols": "core/friday_protocols.py",
    "emotional": "core/emotional_intel.py",
    "server": "server.py",
}


class Veronica:

    def __init__(self):
        self._baselines = self._load_baselines()
        self._health = {}
        self._repairs = []

    # ── Orbital monitoring ───────────────────────────────────────────────

    def monitor(self) -> dict:
        """Check every watched component; restore from backup anything
        that's missing or fails to compile. No backup available means an
        alert, not an improvised replacement."""
        status = {}
        damaged = []

        for name, rel_path in FRIDAY_COMPONENTS.items():
            path = BASE_DIR / rel_path

            if not path.exists():
                status[name] = "MISSING"
                damaged.append((name, "missing"))
                continue

            if not self._check_syntax(rel_path):
                status[name] = "SYNTAX_ERROR"
                damaged.append((name, "syntax_error"))
                continue

            current_hash = self._hash_file(rel_path)
            baseline = self._baselines.get(name)
            status[name] = "MODIFIED" if (baseline and current_hash != baseline) else "NOMINAL"

        repairs = []
        alerts = []
        for name, damage_type in damaged:
            result = self.deploy_replacement(name, damage_type)
            if result.get("repaired"):
                repairs.append(result)
            else:
                alerts.append(f"{name} ({damage_type}): {result.get('reason', 'repair failed')}")

        self._health = {
            "status": status, "damaged": len(damaged), "repaired": len(repairs),
            "ts": datetime.now().isoformat(),
        }
        self._log_health()

        if repairs:
            self._alert(f"{len(repairs)} component(s) restored from backup: "
                        f"{', '.join(r['component'] for r in repairs)}.")
        if alerts:
            self._alert(f"{len(alerts)} component(s) damaged with no backup available — "
                        f"needs manual attention: {'; '.join(alerts)}.")

        return self._health

    # ── Restore from backup ─────────────────────────────────────────────

    def deploy_replacement(self, component: str, damage_type: str) -> dict:
        """Restore a damaged component from its saved backup. Returns
        repaired=False (never attempts a generated replacement) if no
        backup exists — that case needs a human, not a guess."""
        rel_path = FRIDAY_COMPONENTS.get(component)
        if not rel_path:
            return {"repaired": False, "reason": "unknown component"}

        backup_path = VERONICA_DIR / f"{component}_backup.py"
        if not backup_path.exists():
            return {"repaired": False, "reason": "no backup available — needs manual repair"}

        try:
            (BASE_DIR / rel_path).write_text(backup_path.read_text())
        except Exception as e:
            return {"repaired": False, "reason": str(e)}

        self._log_repair({
            "component": component, "damage_type": damage_type,
            "action": "restored_from_backup", "ts": datetime.now().isoformat(),
        })
        return {"repaired": True, "component": component, "method": "backup_restore"}

    # ── Save baselines ───────────────────────────────────────────────────

    def save_baselines(self) -> dict:
        """Save current file hashes + backup copies as the known-good
        state. Call after confirming FRIDAY is working correctly."""
        VERONICA_DIR.mkdir(parents=True, exist_ok=True)
        baselines = {}

        for name, rel_path in FRIDAY_COMPONENTS.items():
            path = BASE_DIR / rel_path
            if not path.exists():
                continue
            try:
                content = path.read_text()
                (VERONICA_DIR / f"{name}_backup.py").write_text(content)
                baselines[name] = self._hash_file(rel_path)
            except Exception:
                pass

        self._baselines = baselines
        BASELINE_FILE.write_text(json.dumps({"baselines": baselines, "saved_at": datetime.now().isoformat()}, indent=2))
        print(f"[Veronica] Baselines saved: {len(baselines)} component(s) backed up.")
        return {"saved": len(baselines), "components": list(baselines.keys())}

    # ── Containment (manual only — safe stub swap, no AI involved) ──────

    def contain_failing_component(self, component: str) -> dict:
        """Swap a failing component's file for a harmless no-op stub so
        it can't take the rest of the process down — the original is
        backed up first. Manual-only; monitor() never calls this."""
        rel_path = FRIDAY_COMPONENTS.get(component)
        if not rel_path:
            return {"contained": False, "reason": "unknown component"}

        path = BASE_DIR / rel_path
        stub = (
            f'"""VERONICA CONTAINMENT STUB — {component} ({rel_path})\n'
            f'Contained at {datetime.now().isoformat()}. Original backed up alongside.\n"""\n\n'
            'class _Contained:\n'
            '    def __getattr__(self, name):\n'
            '        def _stub(*a, **k):\n'
            '            return {"error": "Component contained by Veronica. Repair in progress."}\n'
            '        return _stub\n\n'
            'friday_brain = _Contained()\n'
            'emotional_intel = _Contained()\n'
        )
        try:
            VERONICA_DIR.mkdir(parents=True, exist_ok=True)
            backup = VERONICA_DIR / f"{component}_pre_containment.py"
            if path.exists():
                backup.write_text(path.read_text())
            path.write_text(stub)
            return {"contained": True, "component": component, "backup": str(backup)}
        except Exception as e:
            return {"contained": False, "reason": str(e)}

    # ── Self-test ─────────────────────────────────────────────────────────

    def self_test(self) -> dict:
        tests = {}
        for name, rel_path in FRIDAY_COMPONENTS.items():
            path = BASE_DIR / rel_path
            tests[name] = {
                "exists": path.exists(),
                "size": path.stat().st_size if path.exists() else 0,
                "syntax": self._check_syntax(rel_path) if path.exists() else False,
                "backed_up": (VERONICA_DIR / f"{name}_backup.py").exists(),
            }

        all_ok = all(t["exists"] and t["syntax"] for t in tests.values())
        return {"all_systems": "NOMINAL" if all_ok else "DEGRADED", "components": tests,
                "ts": datetime.now().isoformat()}

    # ── Helpers ───────────────────────────────────────────────────────────

    def _hash_file(self, rel_path: str) -> str:
        try:
            return hashlib.sha256((BASE_DIR / rel_path).read_bytes()).hexdigest()[:16]
        except Exception:
            return ""

    def _check_syntax(self, rel_path: str) -> bool:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(BASE_DIR / rel_path)],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _alert(self, message: str):
        try:
            from services.friday_voice import speak
            speak(f"Veronica: {message}")
        except Exception:
            pass
        print(f"[Veronica] {message}")

    def _log_repair(self, entry: dict):
        self._repairs.append(entry)
        self._append_log({"type": "repair", **entry})

    def _log_health(self):
        self._append_log({"type": "health", **self._health})

    def _append_log(self, entry: dict):
        try:
            VERONICA_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(VERONICA_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def _load_baselines(self) -> dict:
        if BASELINE_FILE.exists():
            try:
                return json.loads(BASELINE_FILE.read_text()).get("baselines", {})
            except Exception:
                return {}
        return {}

    def get_status(self) -> dict:
        return {
            "baselines_saved": bool(self._baselines),
            "components_backed_up": sum(1 for name in FRIDAY_COMPONENTS if (VERONICA_DIR / f"{name}_backup.py").exists()),
            "repairs_performed": len(self._repairs),
            "last_health": self._health,
        }


veronica = Veronica()
