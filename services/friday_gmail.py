"""services/friday_gmail.py — inbox triage over IMAP + an app password
(console.cloud.google.com isn't involved here; this is Gmail's supported
per-app password mechanism, generated under Google Account -> Security ->
App Passwords with 2FA enabled). Separate from JARVIS_V5's Gmail
integration (core/tools/gmail.py), which uses OAuth2 instead — two
different repos, two different credential mechanisms, not meant to share
state."""
import os
import imaplib
import email
from email.header import decode_header

GMAIL_USER = os.getenv("GMAIL_ADDRESS", "")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD", "")


class FridayGmail:

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
            "id": eid.decode(),
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


friday_gmail = FridayGmail()
