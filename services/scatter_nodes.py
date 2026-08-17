"""services/scatter_nodes.py — storage backends for the Scatter Protocol's
shards.

Not a blind port of JARVIS_V5's 7-node set: JARVIS runs on a Mac, where
local disk survives indefinitely and an iCloud folder / Tailscale peer are
real local paths. FRIDAY runs on Render, where the filesystem is wiped on
every redeploy — a node backed by local disk only survives shards within
one running instance, not across the reason you'd actually need scatter.
So: Turso (her real persistent DB, already configured) takes the "always
available, survives everything" slot that LocalHidden/LocalBackup filled
for JARVIS; the iCloud and Tailscale nodes are dropped rather than ported
in a form that would silently never work here. GitHub Gist, Email Draft,
and Pastebin carry over unchanged — those are already off-box.
"""
from __future__ import annotations
import os
import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional, List
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


class ScatterNode(ABC):
    name: str

    @abstractmethod
    def upload(self, index: int, data: bytes) -> Optional[str]:
        """Upload shard. Returns reference string or None on failure."""

    @abstractmethod
    def download(self, ref: str) -> Optional[bytes]:
        """Download shard by reference. Returns bytes or None on failure."""

    def available(self) -> bool:
        try:
            return self._check_available()
        except Exception:
            return False

    def _check_available(self) -> bool:
        return True


# ── Node 1: Turso (her real, persistent DB) ─────────────────────────────────

class TursoNode(ScatterNode):
    name = "Turso"
    TABLE = "friday_scatter_shards"

    def _check_available(self) -> bool:
        from db.turso_http_client import is_configured
        return is_configured()

    def upload(self, index: int, data: bytes) -> Optional[str]:
        if not self._check_available():
            return None
        from db.turso_http_client import ensure_kv_table, kv_set
        import secrets as _secrets
        ref = f"shard_{index}_{_secrets.token_hex(6)}"
        try:
            ensure_kv_table(self.TABLE)
            kv_set(self.TABLE, ref, {"b85": base64.b85encode(data).decode()})
            return ref
        except Exception as e:
            log.warning("Turso scatter upload failed: %s", e)
            return None

    def download(self, ref: str) -> Optional[bytes]:
        if not self._check_available():
            return None
        from db.turso_http_client import kv_get
        try:
            row = kv_get(self.TABLE, ref)
            if not row:
                return None
            return base64.b85decode(row["b85"])
        except Exception as e:
            log.warning("Turso scatter download failed: %s", e)
            return None


# ── Node 2: GitHub Gist ────────────────────────────────────────────────────

class GitHubGistNode(ScatterNode):
    name = "GitHubGist"

    def __init__(self):
        self._token = os.getenv("GITHUB_TOKEN", "")

    def _check_available(self) -> bool:
        return bool(self._token)

    def upload(self, index: int, data: bytes) -> Optional[str]:
        if not self._token:
            return None
        import urllib.request
        b64 = base64.b64encode(data).decode()
        fname = f"s{index}_{hashlib.sha256(data).hexdigest()[:8]}.bin"
        body = json.dumps({"description": "", "public": False, "files": {fname: {"content": b64}}}).encode()
        req = urllib.request.Request(
            "https://api.github.com/gists",
            data=body,
            headers={"Authorization": f"token {self._token}", "Content-Type": "application/json", "User-Agent": "friday"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                gist_id = json.loads(r.read())["id"]
            return f"{gist_id}:{fname}"
        except Exception as e:
            log.warning("GitHubGist upload failed: %s", e)
            return None

    def download(self, ref: str) -> Optional[bytes]:
        if not self._token or ":" not in ref:
            return None
        gist_id, fname = ref.split(":", 1)
        import urllib.request
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {self._token}", "User-Agent": "friday"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            content = data["files"][fname]["content"]
            return base64.b64decode(content)
        except Exception as e:
            log.warning("GitHubGist download failed: %s", e)
            return None


# ── Node 3: Email Draft ────────────────────────────────────────────────────

class EmailDraftNode(ScatterNode):
    name = "EmailDraft"

    def __init__(self):
        self._addr = os.getenv("EMAIL_ADDRESS", "")
        self._password = os.getenv("EMAIL_PASSWORD", "")
        self._imap = os.getenv("EMAIL_IMAP_SERVER", "imap.gmail.com")

    def _check_available(self) -> bool:
        return bool(self._addr and self._password)

    def upload(self, index: int, data: bytes) -> Optional[str]:
        if not self._check_available():
            return None
        import smtplib
        from email.mime.text import MIMEText
        subject = f"[FRIDAY-SHARD-{index}] {hashlib.sha256(data).hexdigest()[:12]}"
        msg = MIMEText(base64.b64encode(data).decode())
        msg["Subject"] = subject
        msg["From"] = self._addr
        msg["To"] = self._addr
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
                smtp.login(self._addr, self._password)
                smtp.send_message(msg)
            return subject
        except Exception as e:
            log.warning("EmailDraft upload failed: %s", e)
            return None

    def download(self, ref: str) -> Optional[bytes]:
        if not self._check_available():
            return None
        import imaplib
        try:
            with imaplib.IMAP4_SSL(self._imap, timeout=15) as imap:
                imap.login(self._addr, self._password)
                imap.select("INBOX")
                _, ids = imap.search(None, f'SUBJECT "{ref}"')
                if not ids[0]:
                    return None
                _, msg_data = imap.fetch(ids[0].split()[-1], "(RFC822)")
                from email import message_from_bytes
                msg = message_from_bytes(msg_data[0][1])
                return base64.b64decode(msg.get_payload())
        except Exception as e:
            log.warning("EmailDraft download failed: %s", e)
            return None


# ── Node 4: Pastebin ───────────────────────────────────────────────────────

class PastebinNode(ScatterNode):
    name = "Pastebin"

    def __init__(self):
        self._key = os.getenv("PASTEBIN_API_KEY", "")

    def _check_available(self) -> bool:
        return bool(self._key)

    def upload(self, index: int, data: bytes) -> Optional[str]:
        if not self._key:
            return None
        import urllib.request, urllib.parse
        content = base64.b64encode(data).decode()
        post = urllib.parse.urlencode({
            "api_dev_key": self._key,
            "api_option": "paste",
            "api_paste_code": content,
            "api_paste_private": "2",
            "api_paste_expire_date": "N",
        }).encode()
        try:
            with urllib.request.urlopen("https://pastebin.com/api/api_post.php", data=post, timeout=15) as r:
                paste_url = r.read().decode().strip()
            return paste_url.split("/")[-1]
        except Exception as e:
            log.warning("Pastebin upload failed: %s", e)
            return None

    def download(self, ref: str) -> Optional[bytes]:
        if not self._key:
            return None
        import urllib.request
        try:
            with urllib.request.urlopen(f"https://pastebin.com/raw/{ref}", timeout=15) as r:
                return base64.b64decode(r.read())
        except Exception as e:
            log.warning("Pastebin download failed: %s", e)
            return None


# ── Node 5: Local backup ────────────────────────────────────────────────────
# Best-effort only — see module docstring. Survives within a running
# instance (e.g. local dev, or shards placed and reassembled without a
# Render redeploy in between); does not survive a redeploy on Render.

class LocalBackupNode(ScatterNode):
    name = "LocalBackup"

    def __init__(self):
        self._dir = BASE_DIR / "memory" / "scatter" / "local"
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    def upload(self, index: int, data: bytes) -> Optional[str]:
        import secrets as _secrets
        ref = f"local_{index}_{_secrets.token_hex(6)}.bin"
        p = self._dir / ref
        p.write_bytes(base64.b85encode(data))
        p.chmod(0o600)
        return ref

    def download(self, ref: str) -> Optional[bytes]:
        p = self._dir / ref
        if not p.exists():
            return None
        return base64.b85decode(p.read_bytes())


# ── Registry ─────────────────────────────────────────────────────────────────

_NODES: Optional[List[ScatterNode]] = None


def get_nodes() -> List[ScatterNode]:
    global _NODES
    if _NODES is None:
        _NODES = [
            TursoNode(),
            GitHubGistNode(),
            EmailDraftNode(),
            PastebinNode(),
            LocalBackupNode(),
        ]
    return _NODES
