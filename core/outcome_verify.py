"""core/outcome_verify.py — check that an action FRIDAY reported actually
happened.

Levels 1 through 3 of the anti-hallucination work all concern what she
*says* she can do. _matched_but_unavailable() admits a system is off,
action_claims.py catches the conversational path claiming an action it
structurally cannot have taken, and tool_router.py routes a request to a
real capability instead of letting the model improvise.

None of them help once a real handler runs. If the handler acts and the
action half-fails, she reports success, because "the handler returned"
and "the thing happened" are different facts and only the first was ever
checked. That is precisely the SMTP bug: she said "sending an email,
boss" and meant it, the send timed out inside a library call, and the
success path had already been taken.

So this reads the result back from the service afterwards, by id.

Three states, and the third is the important one:

    confirmed     the artifact is really there
    contradicted  the service says it is not
    unknown       we could not check

`unknown` is not a hedge or a rounding error. The network being down, a
token having expired, or an id never coming back are all cases where
FRIDAY genuinely does not know -- and collapsing them into
`contradicted` would have her telling the boss an email failed when she
simply could not look. It is reported as "couldn't confirm", which is a
different sentence from "didn't work", and the difference matters most
in exactly the situation where both are plausible.

Verification is best-effort and must never turn a successful action into
an error. A verifier that raises, times out, or returns nonsense yields
`unknown` and the original response stands.
"""
import logging

# mode -> (what to call it in a message, the payload key that names the
# artifact this action produced, verifier)
#
# Deliberately short. Every entry costs a network round trip on the
# request path, so this covers the actions that are expensive to get
# wrong and cheap to check -- not everything that could theoretically be
# read back.
_VERIFIERS = {}


def register(mode: str, label: str, id_key: str, fn):
    _VERIFIERS[mode] = (label, id_key, fn)


def is_verifiable(mode: str) -> bool:
    return mode in _VERIFIERS


def applies(mode: str, payload: dict) -> bool:
    """Whether there is anything to check.

    A mode is reused across every outcome a handler can report -- success,
    a parse failure, "scrapped it", the boss never finishing a pending
    reply, the remote API rejecting the request. Only the success path
    produces an id. On every other path, `verify()` used to be called
    anyway, find no id, come back "unknown", and append "I couldn't
    confirm it went through, though -- worth checking" onto a response
    that had already said "Failed to create event: 400" or "Couldn't
    send that, boss -- ..." in the same breath. Confirmed live: this
    covers every non-success branch of _cmd_calendar_add, _cmd_email_send
    and _cmd_email_compose_send, not just one.

    The handler's own response is already the complete, correct answer
    for those paths. Nothing here should touch it."""
    entry = _VERIFIERS.get(mode)
    if not entry:
        return False
    _, id_key, _ = entry
    return bool(payload.get(id_key))


def verify(mode: str, payload: dict) -> dict:
    """Returns {"state", "detail", "label"}. Never raises.

    Callers on the real dispatch path check applies() first and skip this
    entirely when it would return False -- see its docstring. Kept
    callable on an empty payload regardless, since tests exercise it
    directly and a verifier being asked to check nothing should still
    behave (message_exists("")/event_exists("") already answer "unknown"
    on their own for exactly that input)."""
    entry = _VERIFIERS.get(mode)
    if not entry:
        return {"state": "unknown", "detail": "nothing registered", "label": ""}
    label, _id_key, fn = entry
    try:
        result = fn(payload) or {}
    except Exception as e:
        logging.warning("[verify] %s verifier failed", mode, exc_info=True)
        return {"state": "unknown", "detail": repr(e), "label": label}

    state = result.get("state")
    if state not in ("confirmed", "contradicted", "unknown"):
        # A verifier that returns something unrecognised has told us
        # nothing, and guessing which way it meant would be worse than
        # saying so.
        return {"state": "unknown", "detail": "verifier gave no usable answer",
                "label": label}
    return {"state": state, "detail": result.get("detail", ""), "label": label}


def amend(response: str, mode: str, result: dict) -> str:
    """Rewrite a success message the service has contradicted, or soften
    one it could not confirm.

    A confirmed action is left completely alone -- the overwhelmingly
    common case, and adding "(verified)" to every reply would make her
    tiresome and train the boss to stop reading."""
    state = result.get("state")
    label = result.get("label") or "that"

    if state == "confirmed":
        return response
    if state == "contradicted":
        detail = result.get("detail", "")
        return (f"Correction, boss — I told you I {label}, but it isn't there "
                f"when I check{': ' + detail if detail else ''}.")
    return (f"{response} I couldn't confirm it went through, though — "
            f"worth checking.")


def _gmail_send(payload: dict) -> dict:
    from core.app_state import friday_gmail
    if not friday_gmail:
        return {"state": "unknown", "detail": "Gmail service not loaded"}
    return friday_gmail.message_exists(payload.get("message_id", ""))


def _calendar_add(payload: dict) -> dict:
    from core.app_state import friday_calendar
    if not friday_calendar:
        return {"state": "unknown", "detail": "Calendar service not loaded"}
    return friday_calendar.event_exists(payload.get("event_id", ""))


# The mode strings are the ones the handlers actually tag their
# responses with -- tests/test_outcome_verify.py asserts these still
# exist in server.py, so a renamed mode can't silently switch
# verification off.
register("email_send", "sent that email", "message_id", _gmail_send)
register("email_compose_send", "sent that email", "message_id", _gmail_send)
register("calendar", "added that to your calendar", "event_id", _calendar_add)
