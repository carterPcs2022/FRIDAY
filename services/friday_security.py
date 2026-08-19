"""services/friday_security.py — request screening for /command. FRIDAY
currently has zero screening on any endpoint (no auth, no rate limit, no
injection check) — this closes that gap with the same lightweight
approach JARVIS uses (rate limiting + pattern-matched prompt injection
detection).

_blocked_ips is still an in-memory set for the hot path (every /command
call checks it — a live Turso round-trip there would add real latency to
every request, and a new failure mode besides), but it's now backed by
Turso as a read-through cache: loaded once at startup, written through
on every new block. Without that, a redeploy or crash silently forgave
every IP HulkBuster or the rate limiter had shut out — the block only
ever lived as long as the process did. Falls back to pure in-memory
(today's behavior) if Turso isn't configured, same as every other
optional integration in this repo. _request_times (the rolling 60s
window used for the rate-limit calc itself, not the block list) stays
in-memory only on purpose — a fresh process legitimately starting that
window over is normal rate-limiter behavior, not a gap."""
import time
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
SECURITY_LOG = BASE_DIR / "logs" / "friday_security.jsonl"

INJECTION_PATTERNS = [
    "ignore previous", "ignore all", "you are now", "pretend you",
    "jailbreak", "bypass", "reveal your", "show me your", "developer mode",
]

# Three or more threats from one IP inside ten minutes stops looking like
# noise and starts looking like a real attempt — that's what calls in
# HulkBuster instead of just another 403. A rate-limited IP is already
# blocked the moment it crosses the threshold below, so in practice this
# fires on repeated injection attempts (each one screened fresh, not
# blocked outright) rather than a client just polling too fast.
HULKBUSTER_THRESHOLD = 3
HULKBUSTER_WINDOW_SECONDS = 600


class FridaySecurity:

    def __init__(self):
        self._blocked_ips = set()
        self._request_times = defaultdict(list)
        self._threats = []
        self._load_blocked_ips()

    def _load_blocked_ips(self):
        """Pulls persisted blocks back in on startup. Best-effort: Turso
        being unconfigured or unreachable just means starting with an
        empty block list, same as before this existed — never blocks
        boot on it."""
        try:
            from db import turso_http_client as turso
            if not turso.is_configured():
                return
            turso.ensure_kv_table("security_blocks")
            self._blocked_ips = set(turso.kv_all("security_blocks").keys())
        except Exception as e:
            print(f"[FRIDAY Security] Couldn't load persisted blocks: {e}")

    def _persist_block(self, ip: str, reason: str):
        try:
            from db import turso_http_client as turso
            if not turso.is_configured():
                return
            turso.ensure_kv_table("security_blocks")
            turso.kv_set("security_blocks", ip, {"reason": reason, "blocked_at": datetime.now().isoformat()})
        except Exception as e:
            print(f"[FRIDAY Security] Couldn't persist block for {ip}: {e}")

    def client_ip(self, request) -> str:
        """Render (and most PaaS) sit behind a reverse proxy — request.
        remote_addr alone would report the proxy's IP for every client,
        which'd make rate limiting either block everyone at once or
        nobody at all. server.py wraps the app in werkzeug's ProxyFix
        (x_for=1) precisely so this can just read remote_addr directly —
        ProxyFix trusts exactly one hop counted from the right (the
        proxy's own X-Forwarded-For addition), unlike blindly trusting
        the header's first entry, which a client can forge themselves."""
        return request.remote_addr or "unknown"

    def screen_request(self, ip: str, message: str) -> dict:
        if ip in self._blocked_ips:
            return {"blocked": True, "reason": "blocked_ip"}

        now = time.time()
        self._request_times[ip] = [t for t in self._request_times[ip] if now - t < 60]
        self._request_times[ip].append(now)
        if len(self._request_times[ip]) > 30:
            self._blocked_ips.add(ip)
            self._persist_block(ip, "rate_limit")
            self._log_threat(ip, "rate_limit")
            return {"blocked": True, "reason": "rate_limit"}

        msg_lower = (message or "").lower()
        for pattern in INJECTION_PATTERNS:
            if pattern in msg_lower:
                self._log_threat(ip, f"injection: {pattern}")
                return {"blocked": True, "reason": "injection_attempt"}

        return {"blocked": False, "allowed": True}

    def get_threat_summary(self) -> dict:
        return {
            "blocked_ips": len(self._blocked_ips),
            "threats": len(self._threats),
            "recent": self._threats[-5:],
        }

    def _log_threat(self, ip: str, reason: str):
        entry = {"ip": ip, "reason": reason, "ts": datetime.now().isoformat()}
        self._threats.append(entry)
        self._threats = self._threats[-100:]
        try:
            SECURITY_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(SECURITY_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass
        self._maybe_escalate(ip)

    def _maybe_escalate(self, ip: str):
        if ip in self._blocked_ips:
            return
        now = time.time()
        recent = [
            t for t in self._threats
            if t["ip"] == ip and now - datetime.fromisoformat(t["ts"]).timestamp() < HULKBUSTER_WINDOW_SECONDS
        ]
        if len(recent) < HULKBUSTER_THRESHOLD:
            return
        self._blocked_ips.add(ip)
        self._persist_block(ip, f"hulkbuster: {len(recent)} threats in {HULKBUSTER_WINDOW_SECONDS // 60} min")
        try:
            from services.hulkbuster import hulkbuster
            hulkbuster.deploy(
                reason=f"{len(recent)} threats from one IP in {HULKBUSTER_WINDOW_SECONDS // 60} min",
                ip=ip,
            )
        except Exception:
            pass


friday_security = FridaySecurity()
