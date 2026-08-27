"""services/friday_gmail.py — inbox triage over IMAP + an app password
(console.cloud.google.com isn't involved here; this is Gmail's supported
per-app password mechanism, generated under Google Account -> Security ->
App Passwords with 2FA enabled). JARVIS_V5's Gmail integration
(core/tools/gmail.py) uses the same IMAP/app-password mechanism, not
OAuth2 — two separate repos/deploys, each with its own EMAIL_ADDRESS/
EMAIL_PASSWORD, not meant to share state.

Accepted tradeoff, not an oversight: an app password is full-mailbox
access (read, send, delete — everything this account can do), with no
OAuth-style scope limiting (no restricting it to send-only, for
instance) and no fine-grained revocation beyond regenerating the whole
password. That's a real difference from OAuth2, and worth knowing if
EMAIL_PASSWORD ever leaks. What keeps it reasonable for a single-user
personal deploy: generating one requires 2FA already being enabled on
the account, it's independently revocable from the actual Google
password, and it's read from EMAIL_PASSWORD via env var only — never
committed (.env is gitignored). A full OAuth2 migration would close
that scope gap, but it's a materially bigger lift (consent screen,
token storage/refresh, a redirect flow like services/friday_calendar.py
already has for Google Calendar) for marginal gain here; if this ever
stops being a single-user deploy, that tradeoff is worth revisiting."""
import os
import re
import json
import socket
import imaplib
import smtplib
import email
import tempfile
import contextlib
import concurrent.futures
import time
from email import encoders
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from pathlib import Path

GMAIL_USER = os.getenv("EMAIL_ADDRESS", "")
GMAIL_PASS = os.getenv("EMAIL_PASSWORD", "")

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Per-call timeout (each of connect/TLS/login/send individually) and the
# hard wall-clock deadline for the *whole* connect+login+send operation --
# see send_email()'s _do_send() for why both exist. Module-level so tests
# can drive the real deadline-enforcement path with a short value instead
# of mocking it away or waiting out the real one.
SMTP_PER_CALL_TIMEOUT = 10
SMTP_OVERALL_TIMEOUT = 18


@contextlib.contextmanager
def _force_ipv4():
    """smtp.gmail.com resolves to both IPv4 and IPv6 addresses. Render's
    containers have no outbound IPv6 route, and confirmed live: every
    send_email() call failed with Errno 101 ("Network is unreachable")
    before ever reaching Gmail's login step -- imap.gmail.com's login
    over the same credentials worked fine in the same process, so this
    was never a credentials problem, just this one host resolving to an
    address family that can't actually be reached from here.

    socket.create_connection()'s normal "try each getaddrinfo result in
    turn, fall back on failure" behavior is the usual fix for exactly
    this dual-stack situation, but isn't saving it here in practice --
    forcing IPv4 explicitly removes the failing address family from the
    picture entirely rather than depending on that fallback. Scoped to
    only the one connection attempt inside this context (restored in
    `finally` even if the connection itself raises), not a global,
    process-wide patch of socket.getaddrinfo — nothing else in this
    process is affected, including the IMAP connection in connect()
    above, which was never broken and doesn't need this."""
    original = socket.getaddrinfo

    def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        return original(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_only
    try:
        yield
    finally:
        socket.getaddrinfo = original


class FridayGmail:

    def __init__(self):
        # Set by draft_reply(), consumed (and cleared) by send_draft() —
        # lets "send it" refer back to whatever FRIDAY last drafted
        # without the caller having to repeat subject/body/recipient.
        # In-memory only, like checkin_system's emergency_pending: one
        # process, one pending draft at a time is all this needs.
        self._last_draft = {}

    def connect(self):
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        return mail

    def get_unread(self, limit: int = 10) -> list:
        if not GMAIL_USER or not GMAIL_PASS:
            return []
        mail = None
        try:
            mail = self.connect()
            mail.select("inbox")
            _, ids = mail.search(None, "UNSEEN")
            email_ids = ids[0].split()[-limit:]
            emails = []
            for eid in reversed(email_ids):
                # One malformed message (bad encoding, missing headers,
                # non-text body) must not blank out every other unread
                # email in the batch — each one gets its own try/except
                # instead of one wrapping the whole loop.
                try:
                    emails.append(self._parse_message(mail, eid))
                except Exception as e:
                    print(f"[FRIDAY Gmail] Failed to parse message {eid}: {e}")
            return emails
        except Exception as e:
            print(f"[FRIDAY Gmail] {e}")
            return []
        finally:
            if mail is not None:
                try:
                    mail.logout()
                except Exception:
                    pass

    def _parse_message(self, mail, eid) -> dict:
        _, data = mail.fetch(eid, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])

        subject = msg.get("Subject", "") or ""
        decoded = decode_header(subject)[0][0] if subject else ""
        if isinstance(decoded, bytes):
            decoded = decoded.decode(errors="replace")
        subject = decoded or "(no subject)"

        sender = msg.get("From", "")
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode(errors="replace")[:200]
                    break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(errors="replace")[:200]

        return {
            "subject": subject, "from": sender, "body": body,
            "id": eid.decode(), "message_id": msg.get("Message-ID", ""),
        }

    def summarize_inbox(self) -> str:
        emails = self.get_unread(20)
        if not emails:
            return "Inbox is clear, boss."
        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Email triage — {len(emails)} unread:\n\n"
            + "\n".join(
                f"From: {e['from'][:40]}\n"
                f"Subject: {e['subject']}\n"
                f"Preview: {e['body'][:100]}\n"
                for e in emails[:10]
            )
            + "\n\nTriage this inbox. What needs immediate attention? "
              "What can wait? What's probably spam? "
              "FRIDAY style. Under 80 words."
        )
        return result["response"]

    def get_urgent(self) -> list:
        emails = self.get_unread(20)
        urgent = []
        URGENT_KEYWORDS = [
            "urgent", "asap", "important",
            "deadline", "emergency", "action required",
            "immediate", "critical", "time sensitive",
        ]
        for e in emails:
            subj = e["subject"].lower()
            if any(k in subj for k in URGENT_KEYWORDS):
                urgent.append(e)
        return urgent

    def draft_reply(self, email_subject: str = "", email_from: str = "",
                    email_body: str = "", instruction: str = "",
                    message_id: str = "") -> dict:
        """Draft a reply — FRIDAY writes it, the boss approves before it
        actually sends. This never sends by itself; approval happens as a
        separate step (send_draft(), after the boss says "send it")."""
        from core.friday_brain import friday_brain

        result = friday_brain.think(
            f"Draft an email reply:\n\n"
            f"From: {email_from}\nSubject: {email_subject}\n"
            f"Message: {email_body[:500]}\n\n"
            f"Instruction: {instruction or 'Draft a professional reply'}\n\n"
            f"Write the reply email body only. No subject line. "
            f"No 'Dear...' opener needed. Match the tone of the original. "
            f"Keep it concise and clear."
        )

        draft = {
            "draft": result["response"], "subject": f"Re: {email_subject}",
            "to": email_from, "ready": True,
            # Carried through to send_draft() so the actual send threads
            # onto the original message instead of landing as a new,
            # unrelated thread in the recipient's inbox.
            "message_id": message_id,
        }
        self._last_draft = draft
        return draft

    def extract_address(self, raw: str) -> str:
        """Pulls a bare address out of an RFC 2822 'Name <addr>' string
        (or a plain address, or free text containing one)."""
        match = _EMAIL_RE.search(raw or "")
        return match.group(0) if match else ""

    def _resolve_attachment(self, ref: str) -> Path | None:
        """A local file path, the id of something already ingested via
        services/documents.py, or the name of something FRIDAY generated
        via "create a file" (core/friday_memory.py's generated-files
        store) — callers shouldn't need to know which. Missing on all
        three counts (rather than silently dropping it) becomes a hard
        error in send_email(): an attachment the boss asked for that
        quietly never showed up is worse than a failed send."""
        p = Path(ref)
        if p.is_file():
            return p
        try:
            from services.documents import get_path
            doc_path = get_path(ref)
        except Exception:
            doc_path = None
        if doc_path and Path(doc_path).is_file():
            return Path(doc_path)
        try:
            from core.friday_memory import get_generated_file
            entry = get_generated_file(ref)
        except Exception:
            entry = None
        if entry:
            # Materialized on demand, not kept on disk between requests --
            # the store entry (JSON+Turso) is the durable copy; this is
            # just scratch space for smtplib to read bytes from.
            tmp_dir = Path(tempfile.gettempdir()) / "friday_generated_files"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = tmp_dir / entry["name"]
            tmp_path.write_text(entry.get("content", ""))
            return tmp_path
        return None

    def send_email(self, to: str = "", subject: str = "", body: str = "",
                    in_reply_to: str = "", attachments: list | None = None) -> dict:
        """Actually sends, via the same SMTP app-password credentials the
        IMAP side uses. No approval step here — the caller (a "send it"
        confirmation, or an explicit compose-and-send request) is the
        approval; this is the action, not another draft."""
        if not GMAIL_USER or not GMAIL_PASS:
            return {"ok": False, "error": "Gmail not configured"}

        address = self.extract_address(to)
        if not address:
            return {"ok": False, "error": f"'{to}' doesn't look like an email address"}
        if not (body or "").strip():
            return {"ok": False, "error": "Nothing to send — the body is empty"}

        files = []
        for ref in (attachments or []):
            path = self._resolve_attachment(ref)
            if not path:
                return {"ok": False, "error": f"Attachment not found: {ref}"}
            files.append(path)

        msg = MIMEMultipart()
        msg["Subject"] = subject or "(no subject)"
        msg["From"] = GMAIL_USER
        msg["To"] = address
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.attach(MIMEText(body))

        for path in files:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(path.read_bytes())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{path.name}"')
            msg.attach(part)

        # Written by _do_send() as it progresses, read by the except branches
        # below if the deadline fires -- a plain list because a timeout means
        # the background thread is abandoned mid-stage (see shutdown(wait=False)
        # below), not joined, so this is the only way to see how far it got.
        # A stale read on a genuine race is an acceptable diagnostic tradeoff;
        # nothing here needs to be exact, just far better than the previous
        # "timed out" with no further detail, which left "hangs somewhere in
        # the connect/login/send chain" and "the actual send keeps failing
        # outright" indistinguishable from the logs alone.
        stage = ["resolving smtp.gmail.com / opening connection"]

        def _do_send():
            with _force_ipv4():
                stage[0] = "TCP connect + TLS handshake"
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=SMTP_PER_CALL_TIMEOUT) as smtp:
                    stage[0] = "login"
                    smtp.login(GMAIL_USER, GMAIL_PASS)
                    stage[0] = "send_message"
                    smtp.send_message(msg)
                    stage[0] = "done"

        # smtplib's own `timeout` bounds each individual blocking call
        # (connect, TLS handshake, login, send) separately, not the whole
        # operation -- raising it to 25s (an earlier fix here) helped a
        # one-off cold-start blip, but confirmed live: on a more
        # persistently degraded connection, several sequential stages can
        # each eat close to that budget before proceeding, and they
        # compound past the HUD's 45s client-side deadline even though no
        # single stage looked slow on its own. Running the whole
        # connect+login+send in a thread and capping *that* with one hard
        # wall-clock deadline is what actually bounds total time,
        # regardless of how many SMTP stages there are. The per-call
        # timeout stays low as a fast first line of defense against one
        # truly stuck stage.
        #
        # Deliberately NOT a `with ThreadPoolExecutor() as pool:` block --
        # its __exit__ calls shutdown(wait=True), which blocks until the
        # background thread actually finishes regardless of .result()
        # already having raised TimeoutError, silently defeating the
        # deadline entirely (caught by a real test, not just reasoned
        # about: elapsed time matched the hang, not the timeout, until
        # this was fixed). shutdown(wait=False) lets the timeout mean what
        # it says; the thread isn't forcibly killed (Python threads can't
        # be) and may still complete in the background afterward -- worst
        # case a late/duplicate send once the network recovers, not data
        # loss or a hung request, which is the actual problem this fixes.
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        started = time.time()
        try:
            pool.submit(_do_send).result(timeout=SMTP_OVERALL_TIMEOUT)
        except concurrent.futures.TimeoutError:
            elapsed = time.time() - started
            print(f"[FRIDAY Gmail] send failed: {elapsed:.1f}s elapsed, stuck at stage: {stage[0]}")
            return {"ok": False, "error": "timed out"}
        except Exception as e:
            elapsed = time.time() - started
            print(f"[FRIDAY Gmail] send failed: {elapsed:.1f}s elapsed, stage: {stage[0]}, error: {e!r}")
            return {"ok": False, "error": str(e)}
        finally:
            pool.shutdown(wait=False)

        return {
            "ok": True, "to": address, "subject": msg["Subject"],
            "attachments": [p.name for p in files],
        }

    def send_draft(self, to: str = "", body: str = "", attachments: list | None = None) -> dict:
        """Sends whatever draft_reply() last produced. `to`/`body` let the
        boss redirect or tweak it in the same breath ("send it to her
        personal address instead") without redrafting."""
        if not self._last_draft:
            return {"ok": False, "error": "Nothing drafted yet, boss"}

        draft = self._last_draft
        result = self.send_email(
            to=to or draft.get("to", ""),
            subject=draft.get("subject", ""),
            body=body or draft.get("draft", ""),
            in_reply_to=draft.get("message_id", ""),
            attachments=attachments,
        )
        if result.get("ok"):
            self._last_draft = {}
        return result

    def find_email(self, search: str = "") -> dict:
        """Finds a specific email to reply to — scoped to the last 20
        unread messages, not the whole mailbox. A "reply to X" request
        about something already read or archived won't be found; that's
        a real scope limit, not a bug, but worth knowing."""
        emails = self.get_unread(20)
        search_lower = search.lower()

        for msg in emails:
            subj = msg.get("subject", "").lower()
            sender = msg.get("from", "").lower()
            if search_lower in subj or search_lower in sender:
                return msg
        return {}

    def smart_triage(self) -> dict:
        """Full inbox triage with action categories: urgent, reply_needed,
        read_later, probably_spam."""
        import re
        from core.friday_brain import friday_brain

        emails = self.get_unread(20)
        if not emails:
            return {"categories": {}, "total": 0}

        result = friday_brain.think(
            f"Email triage — {len(emails)} emails:\n\n"
            + "\n".join(
                f"From: {e['from'][:40]}\nSubject: {e['subject']}\n"
                for e in emails[:15]
            )
            + "\n\nCategorize each as:\n"
              "URGENT - needs action today\nREPLY - needs a reply this week\n"
              "READ - worth reading, no action\nSKIP - probably spam/newsletters\n\n"
              'Reply as JSON: {"urgent": [], "reply": [], "read": [], "skip": []} '
              "with subject lines."
        )

        try:
            clean = re.sub(r"```json|```", "", result["response"]).strip()
            categories = json.loads(clean)
        except Exception:
            categories = {"urgent": [], "reply": [], "read": [], "skip": []}

        return {
            "categories": categories, "total": len(emails),
            "summary": (
                f"{len(categories.get('urgent', []))} urgent, "
                f"{len(categories.get('reply', []))} need replies"
            ),
        }


friday_gmail = FridayGmail()
