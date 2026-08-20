"""services/friday_phone.py — a real phone number for FRIDAY via Twilio.
Call her, text her, or let her call you for a critical alert. Ported from
JARVIS_V5's services/phone.py; FRIDAY has no equivalent at all today
(confirmed: no "twilio" reference anywhere in her codebase before this).

JARVIS routes phone conversation through core/brain_v2.py's brain object
directly. FRIDAY has no separate brain object to import — her entire
command pipeline (lockdown check, Mayday, safe check-in, security
screening, NLU routing) lives inline in server.py's POST /command route,
nearly 1000 lines of it. Rather than duplicating or extracting that,
phone turns speak to her the same way any other client does: a loopback
HTTP call to her own /command endpoint. Slightly more latency than an
in-process call, negligible next to Twilio's own round trip, and it
means a phone call gets Mayday/lockdown/security-screening/NLU exactly
as designed, for free, instead of a second parallel implementation that
could drift from the real one.

Twilio is an optional dependency — everything here degrades to a clear
error if it isn't installed/configured rather than crashing at import time.
"""
import os
import re

import requests

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_PHONE", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
_INTERNAL_PORT = os.getenv("PORT", "8080")
FRIDAY_NAME = os.getenv("FRIDAY_NAME", "FRIDAY")


def _twilio_configured() -> bool:
    return bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM)


def _clean_for_speech(text: str) -> str:
    """Strip markdown and collapse newlines — phones don't render either,
    and TwiML <Say> reads them aloud literally otherwise."""
    clean = re.sub(r"[*_`#\[\]]", "", text or "")
    clean = re.sub(r"\n+", ". ", clean)
    return clean[:400]


def _ask_friday(prompt: str) -> str:
    """Loopback call to her own /command — see module docstring for why.
    Carries FRIDAY_ACCESS_TOKEN if set — core/access_auth.py gates
    /command like everything else now, and a loopback call is still an
    external HTTP request from that gate's point of view."""
    try:
        headers = {}
        access_token = os.getenv("FRIDAY_ACCESS_TOKEN", "")
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        r = requests.post(
            f"http://127.0.0.1:{_INTERNAL_PORT}/command",
            json={"prompt": prompt},
            headers=headers,
            timeout=20,
        )
        return r.json().get("response", "I'm here, but something went wrong on my end.")
    except Exception as e:
        return f"I'm having trouble reaching myself right now: {e}"


class FridayPhone:

    def handle_incoming_call(self) -> str:
        """Twilio webhook for an incoming call — greets, then records the
        caller's speech and posts it to /friday/phone/respond."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna" rate="95%">
        Hey, it's {FRIDAY_NAME}. What's up?
    </Say>
    <Record action="{PUBLIC_URL}/friday/phone/respond" method="POST"
            maxLength="30" playBeep="false" transcribe="true"
            transcribeCallback="{PUBLIC_URL}/friday/phone/transcribed" />
</Response>"""

    def handle_response(self, transcript: str) -> str:
        """Process what the caller said, speak the response back, then
        keep listening."""
        clean = _clean_for_speech(_ask_friday(transcript))
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna" rate="95%">{clean}</Say>
    <Record action="{PUBLIC_URL}/friday/phone/respond" method="POST"
            maxLength="30" playBeep="false" timeout="3" />
</Response>"""

    def handle_sms(self, from_number: str, message: str) -> str:
        """Someone texted FRIDAY — process and text back."""
        if not _twilio_configured():
            return "Twilio not configured"

        response = _ask_friday(message)[:1500]

        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=f"FRIDAY: {response}", from_=TWILIO_FROM, to=from_number)
        return response

    def send_sms(self, to_number: str, message: str) -> dict:
        """FRIDAY texts out proactively — distinct from handle_sms(), which
        only replies to a text that came in. Same Twilio client, opposite
        direction: this is FRIDAY-initiated, not a response."""
        if not _twilio_configured():
            return {"error": "Twilio not configured (TWILIO_ACCOUNT_SID/AUTH_TOKEN/PHONE)"}
        if not to_number:
            return {"error": "No destination number provided"}
        if not (message or "").strip():
            return {"error": "Nothing to send — the message is empty"}

        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        sent = client.messages.create(body=message[:1500], from_=TWILIO_FROM, to=to_number)
        return {"ok": True, "sid": sent.sid, "to": to_number}

    def send_alert_call(self, message: str, to_number: str) -> dict:
        """FRIDAY calls you directly for a critical alert."""
        if not _twilio_configured():
            return {"error": "Twilio not configured (TWILIO_ACCOUNT_SID/AUTH_TOKEN/PHONE)"}
        if not to_number:
            return {"error": "No destination number provided"}

        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        clean_msg = _clean_for_speech(message)
        call = client.calls.create(
            twiml=f"""<Response>
                <Say voice="Polly.Joanna" rate="95%">
                    Boss. {FRIDAY_NAME} here. {clean_msg}
                    Call back when you get a chance.
                </Say>
            </Response>""",
            from_=TWILIO_FROM, to=to_number,
        )
        return {"call_sid": call.sid, "status": call.status}


friday_phone = FridayPhone()
