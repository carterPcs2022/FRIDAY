"""core/scatter.py — the Scatter Protocol.

In Age of Ultron, JARVIS scattered his consciousness across the internet
so Ultron couldn't find and destroy the nuclear launch codes he was
protecting — encrypted, split, spread across places no single attack
could reach all of. FRIDAY's version protects a different payload: not
codes, but her own core state — memory, personality, and protocol status
("certain protocols and herself", per the boss). Same mechanism: AES-256-
GCM encryption, then Shamir's Secret Sharing splits the encrypted blob
into shards where any `threshold`-many (not all) are enough to
reconstruct it, spread across independent storage backends (see
services/scatter_nodes.py) so no single compromised or seized node can
recover anything on its own.

Deliberately does NOT include live credentials (API keys, passphrases) in
the scattered payload. JARVIS_V5's version does — a disaster-recovery
tradeoff made and reviewed there already. Starting that same tradeoff
fresh here, on a new codebase, without the same review, isn't a call this
should make unilaterally; if you want credential recovery folded in later,
that's a deliberate follow-up, not a default.

Scatter is destructive-ish (not easily reversible without the passphrase
and enough recovered shards) and irreversible in effect if reassembly
later fails, so it requires two steps: request_scatter() issues a
confirm_token and alerts the boss; scatter() only executes given that
token, the matching passphrase, and inside the confirmation window.
Reassemble is the recovery action, not the destructive one, so it stays
single-step — friction there works against you, not for you.
"""
from __future__ import annotations
import os
import json
import time
import secrets
import hashlib
import logging
from pathlib import Path
from typing import List, Tuple, Optional

from core.sharding import ShamirSharding

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from core.crypto import derive_key as _derive_key_obj, encrypt as _crypto_encrypt, decrypt as _crypto_decrypt
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False
    log.warning("core.crypto unavailable (cryptography package missing) — scatter disabled")

CONFIRM_WINDOW_SECONDS = 600


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return _derive_key_obj(passphrase, salt=salt).key


class ScatterEngine:

    def __init__(self):
        # Computed here, not as class attributes bound once at class-
        # definition time — a class attribute referencing the module-level
        # BASE_DIR would freeze to whatever BASE_DIR was when this module
        # was first imported, silently ignoring any later override (e.g.
        # a test patching core.scatter.BASE_DIR).
        self.SCATTER_DIR = BASE_DIR / "memory" / "scatter"
        self.MANIFEST = self.SCATTER_DIR / "manifest.enc"
        self.shards_total = int(os.getenv("SCATTER_SHARDS", "5"))
        self.shards_thresh = int(os.getenv("SCATTER_THRESHOLD", "3"))
        self.shamir = ShamirSharding(self.shards_thresh, self.shards_total)
        self.SCATTER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._pending: dict[str, dict] = {}

    # ── Two-step confirmation ────────────────────────────────────────────

    def request_scatter(self, passphrase: str) -> dict:
        if not passphrase:
            return {"ok": False, "error": "passphrase required"}
        self._prune_pending()
        token = secrets.token_hex(16)
        self._pending[token] = {
            "hash": hashlib.sha256(passphrase.encode()).hexdigest(),
            "expires": time.time() + CONFIRM_WINDOW_SECONDS,
        }
        self._alert(
            "Scatter Protocol requested. This disperses your core state across "
            "nodes and isn't easily reversible. Send the same passphrase back "
            "with the confirm token within 10 minutes to proceed, or ignore to "
            "leave it unexecuted."
        )
        return {
            "status": "awaiting_confirmation", "confirm_token": token,
            "expires_seconds": CONFIRM_WINDOW_SECONDS,
            "warning": "Scatter disperses your core state across nodes. Not easily reversible.",
        }

    def _prune_pending(self):
        now = time.time()
        self._pending = {t: v for t, v in self._pending.items() if v["expires"] > now}

    # ── Public API ────────────────────────────────────────────────────────

    def scatter(self, passphrase: str, confirm_token: str) -> dict:
        """Encrypt FRIDAY's core state, split into shards, distribute to
        nodes. Requires a valid, unexpired confirm_token from a prior
        request_scatter() call for the same passphrase."""
        if not _CRYPTO_OK:
            return {"ok": False, "error": "cryptography package missing"}

        self._prune_pending()
        pending = self._pending.pop(confirm_token, None)
        if not pending:
            return {"ok": False, "error": "confirmation missing or expired — request again"}
        if hashlib.sha256(passphrase.encode()).hexdigest() != pending["hash"]:
            return {"ok": False, "error": "passphrase doesn't match the request that issued this token"}

        from services import scatter_nodes
        log.info("Scatter Protocol: dispersal initiated")

        payload = self._build_payload()
        raw = json.dumps(payload).encode()
        salt = secrets.token_bytes(32)
        key = _derive_key(passphrase, salt)
        enc_data = _crypto_encrypt(raw, key)
        del key

        shards = self.shamir.split(salt + enc_data)

        nodes = scatter_nodes.get_nodes()
        manifest = {"ts": time.time(), "shards_total": self.shards_total, "threshold": self.shards_thresh, "placements": []}
        results = []

        for i, (x, shard_bytes) in enumerate(shards):
            node = nodes[i % len(nodes)]
            ref = node.upload(x, shard_bytes)
            manifest["placements"].append({"node": node.name, "index": x, "ref": ref})
            results.append({"node": node.name, "ok": ref is not None})

        m_salt = secrets.token_bytes(32)
        m_key = _derive_key(passphrase, m_salt)
        m_enc = _crypto_encrypt(json.dumps(manifest).encode(), m_key)
        del m_key
        self.MANIFEST.write_bytes(m_salt + m_enc)
        self.MANIFEST.chmod(0o600)

        ok_count = sum(1 for r in results if r["ok"])
        ok = ok_count >= self.shards_thresh
        log.info("Scatter complete: %d/%d shards placed", ok_count, self.shards_total)
        self._alert(
            f"Scatter {'complete' if ok else 'incomplete'}: {ok_count}/{self.shards_total} "
            f"shard(s) placed (need {self.shards_thresh} to reassemble)."
        )
        return {"ok": ok, "placed": ok_count, "total": self.shards_total, "results": results}

    def reassemble(self, passphrase: str) -> dict:
        if not _CRYPTO_OK:
            return {"ok": False, "error": "cryptography package missing"}
        if not self.MANIFEST.exists():
            return {"ok": False, "error": "No scatter manifest found. Run scatter first."}

        from services import scatter_nodes

        m_blob = self.MANIFEST.read_bytes()
        m_salt = m_blob[:32]
        m_key = _derive_key(passphrase, m_salt)
        try:
            manifest = json.loads(_crypto_decrypt(m_blob[32:], m_key))
        except Exception:
            return {"ok": False, "error": "Wrong passphrase or corrupt manifest"}
        finally:
            del m_key

        nodes_by_name = {n.name: n for n in scatter_nodes.get_nodes()}
        collected: List[Tuple[int, bytes]] = []

        for placement in manifest["placements"]:
            if not placement.get("ref"):
                continue
            node = nodes_by_name.get(placement["node"])
            if node is None:
                continue
            data = node.download(placement["ref"])
            if data is not None:
                collected.append((placement["index"], data))

        if len(collected) < manifest["threshold"]:
            return {"ok": False, "error": f"Only {len(collected)}/{manifest['threshold']} shards recovered"}

        combined = self.shamir.reconstruct(collected)
        salt, enc_data = combined[:32], combined[32:]
        key = _derive_key(passphrase, salt)
        try:
            payload = json.loads(_crypto_decrypt(enc_data, key))
        except Exception:
            return {"ok": False, "error": "Decryption failed — wrong passphrase?"}
        finally:
            del key

        return {"ok": True, "payload": payload, "shards_recovered": len(collected)}

    def status(self) -> dict:
        from services import scatter_nodes
        nodes = scatter_nodes.get_nodes()
        return {
            "manifest_exists": self.MANIFEST.exists(),
            "shards_total": self.shards_total,
            "threshold": self.shards_thresh,
            "nodes": [{"name": n.name, "available": n.available()} for n in nodes],
            "pending_confirmations": len(self._pending),
        }

    # ── Internals ─────────────────────────────────────────────────────────

    def _build_payload(self) -> dict:
        """'Certain protocols and herself': memory, personality, and
        protocol/range status. No live credentials — see module docstring."""
        payload: dict = {"ts": time.time(), "version": "scatter-v1"}
        try:
            from core.friday_memory import get_facts, get_recent_turns, get_profile
            payload["facts"] = get_facts(1000)
            payload["recent_turns"] = get_recent_turns(50)
            payload["profile"] = get_profile()
        except Exception:
            pass
        try:
            personality_path = BASE_DIR / "config" / "friday_personality.py"
            if personality_path.exists():
                payload["personality_source"] = personality_path.read_text()
        except Exception:
            pass
        try:
            from core.friday_protocols import friday_protocols
            payload["protocol_state"] = friday_protocols.get_range_report()
        except Exception:
            pass
        return payload

    def _alert(self, message: str):
        try:
            from services.friday_voice import speak
            speak(f"Veronica: {message}")
        except Exception:
            pass
        try:
            import httpx
            httpx.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": os.getenv("PUSHOVER_APP_TOKEN", ""),
                    "user": os.getenv("PUSHOVER_USER_KEY", ""),
                    "title": "FRIDAY — Scatter Protocol",
                    "message": message,
                    "priority": 1,
                }, timeout=5,
            )
        except Exception:
            pass
        print(f"[Scatter] {message}")


_engine: Optional[ScatterEngine] = None


def get_engine() -> ScatterEngine:
    global _engine
    if _engine is None:
        _engine = ScatterEngine()
    return _engine
