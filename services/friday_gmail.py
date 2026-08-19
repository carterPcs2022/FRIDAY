"""services/friday_gmail.py — inbox triage over IMAP + an app password
(console.cloud.google.com isn't involved here; this is Gmail's supported
per-app password mechanism, generated under Google Account -> Security ->
App Passwords with 2FA enabled). JARVIS_V5's Gmail integration
(core/tools/gmail.py) uses the same IMAP/app-password mechanism, not
OAuth2 — two separate repos/deploys, each with its own EMAIL_ADDRESS/
EMAIL_PASSWORD, not meant to share state."""
import os
import re
import json
import imaplib
import smtplib
import email
from email import encoders
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from pathlib import Path

GMAIL_USER = os.getenv("EMAIL_ADDRESS", "")
GMAIL_PASS = os.getenv("EMAIL_PASSWORD", "")

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


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
        """A local file path, or the id of something already ingested via
        services/documents.py — either way, callers shouldn't need to
        know which. Missing on both counts (rather than silently dropping
        it) becomes a hard error in send_email(): an attachment the boss
        asked for that quietly never showed up is worse than a failed send."""
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

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
                smtp.login(GMAIL_USER, GMAIL_PASS)
                smtp.send_message(msg)
        except Exception as e:
            print(f"[FRIDAY Gmail] send failed: {e}")
            return {"ok": False, "error": str(e)}

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
