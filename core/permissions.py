"""core/permissions.py — per-route risk tiers on top of
core/access_auth.py's binary "does this request carry a valid
credential" gate.

access_auth answers "is this caller allowed to talk to FRIDAY at all."
This answers a different question: "how much should this specific
action cost to trigger." Reading the calendar and deploying HulkBuster
require the identical bearer token today — the audit's second core
finding. This doesn't touch access_auth's mechanism or replace it; it's
a layer on top, and every route below still needs to pass the existing
gate first.

Four tiers — the audit's scoped recommendation, not the full six-tier
READ/LOW_RISK_WRITE/EXTERNAL_COMMUNICATION/SYSTEM_CHANGE/SENSITIVE/
DESTRUCTIVE from the original V3 directive. Four is the 80% version
that actually matters for a single-user deploy:

  READ          — no state change. Status checks, calendar lookups,
                  memory recall.
  WRITE         — changes FRIDAY's own stored state, nothing leaves the
                  system. Add a task, log a habit, save a journal entry,
                  draft (not send) an email, routine cache cleanup.
  EXTERNAL_COMM — reaches a real person or system outside FRIDAY: send
                  an email, send a text, place a call.
  DESTRUCTIVE   — hard to reverse, or shuts something down: lockdown,
                  HulkBuster, Scatter.

ROUTE_RISK is keyed by Flask endpoint name ("blueprint_name.function_name"
for blueprint routes, bare function name for server.py's own routes --
exactly what a Rule's .endpoint reports). Only routes that don't fit the
method-based default are listed explicitly; everything else falls back
to classify_default() -- GET/HEAD -> READ, everything else -> WRITE.
That default never *under*-classifies an unlisted route as harmless: a
POST route nobody got around to tagging still lands at WRITE, one tier
above a free pass, not at READ.

DESTRUCTIVE-tier routes generally go through ConfirmationGate, the same
two-step token pattern core/scatter.py already uses for the Scatter
Protocol (request a token, confirm with that exact token inside a
10-minute window) -- generalized here so /friday/hulkbuster/deploy gets
it too instead of executing immediately on a single POST, which is what
it did before this. Scatter itself keeps its own passphrase-bound
implementation untouched (it already works, and rewriting a working
security-critical path purely for uniformity carries real risk for no
real benefit).

/friday/lockdown is the one deliberate exception, not an oversight: it's
in core/access_auth.py's EXEMPT_PATHS on purpose, reachable with *no*
credential at all, specifically so it still works from a brand-new
device if the boss's phone is lost or stolen. Gating it behind a
confirm-token round-trip would fight the entire reason it's frictionless
-- the same "friction here works against you, not for you" reasoning
core/scatter.py already applies to reassemble(). It stays tagged
DESTRUCTIVE below (that's true, and worth surfacing), but deliberately
does not get ConfirmationGate wired in.
"""
import time
import secrets
from enum import IntEnum

CONFIRM_WINDOW_SECONDS = 600


class RiskLevel(IntEnum):
    READ = 0
    WRITE = 1
    EXTERNAL_COMM = 2
    DESTRUCTIVE = 3


ROUTE_RISK: dict = {
    # -- Reaching You: real email/call/text leaves the system --
    "email.email_send": RiskLevel.EXTERNAL_COMM,
    "phone.friday_phone_alert": RiskLevel.EXTERNAL_COMM,
    "phone.friday_phone_text": RiskLevel.EXTERNAL_COMM,
    "phone.friday_pushcut_call": RiskLevel.EXTERNAL_COMM,
    "phone.friday_pushcut_call_mom": RiskLevel.EXTERNAL_COMM,

    # -- Destructive: hard to reverse, or shuts something down --
    # trigger_lockdown is tagged DESTRUCTIVE but deliberately has no
    # ConfirmationGate -- see the module docstring. It's the one
    # intentional exception, not a gap.
    "security.trigger_lockdown": RiskLevel.DESTRUCTIVE,
    "security.hulkbuster_deploy": RiskLevel.DESTRUCTIVE,
    "security.trigger_scatter": RiskLevel.DESTRUCTIVE,
    # Writes a self-generated patch to a live core file (server.py,
    # friday_brain.py, the security files...). Sandbox-tested and
    # confirm-gated (see core/self_repair.py), but the actual write is
    # the same "hard to reverse cleanly if wrong" shape as the rest of
    # this tier.
    "orchestration.self_repair_confirm": RiskLevel.DESTRUCTIVE,
    # Same shape as self_repair_confirm above: both overwrite one of
    # FRIDAY's own core source files (server.py, security files, ...)
    # on a single call. Found during a security review -- these were
    # previously unclassified (falling through to plain WRITE, no
    # confirmation) despite doing exactly what HulkBuster/self-repair
    # are gated for.
    "orchestration.veronica_repair": RiskLevel.DESTRUCTIVE,
    "orchestration.veronica_contain": RiskLevel.DESTRUCTIVE,

    # -- Recovery actions: same reasoning core/scatter.py already
    # documents for reassemble() staying single-step -- friction here
    # works against you, not for you, so these deliberately stay WRITE
    # rather than inheriting their destructive counterpart's tier.
    "security.hulkbuster_stand_down": RiskLevel.WRITE,
    "security.scatter_reassemble": RiskLevel.WRITE,

    # -- Twilio webhooks: auth-exempt (see core/access_auth.py
    # EXEMPT_PATHS -- Twilio can't send a bearer token) and reactive,
    # not boss- or attacker-triggerable as an action in their own right.
    # Listed explicitly so they read as a deliberate call, not an
    # oversight.
    "phone.friday_phone_call": RiskLevel.WRITE,
    "phone.friday_phone_sms": RiskLevel.WRITE,
}


def classify_default(methods) -> "RiskLevel":
    methods = {m.upper() for m in methods}
    if "GET" in methods or "HEAD" in methods:
        return RiskLevel.READ
    return RiskLevel.WRITE


def risk_for(endpoint: str, methods=frozenset({"GET"})) -> "RiskLevel":
    if endpoint in ROUTE_RISK:
        return ROUTE_RISK[endpoint]
    return classify_default(methods)


class ConfirmationGate:
    """A reusable version of core/scatter.py's request/confirm token
    pattern, for DESTRUCTIVE actions that don't carry their own
    passphrase the way Scatter does (lockdown, HulkBuster). Each
    instance tracks its own pending tokens -- one gate per action, not
    one gate shared across unrelated destructive actions, so a pending
    lockdown confirmation can't accidentally confirm a HulkBuster
    deploy."""

    def __init__(self, action_name: str, window_seconds: int = CONFIRM_WINDOW_SECONDS):
        self.action_name = action_name
        self.window_seconds = window_seconds
        self._pending: dict = {}

    def _prune(self):
        now = time.time()
        self._pending = {t: exp for t, exp in self._pending.items() if exp > now}

    def request(self) -> dict:
        """Issues a confirm token. Doesn't execute anything -- the
        caller still has to come back with this exact token via
        confirm() inside the window."""
        self._prune()
        token = secrets.token_hex(16)
        self._pending[token] = time.time() + self.window_seconds
        return {
            "status": "awaiting_confirmation", "confirm_token": token,
            "expires_seconds": self.window_seconds,
            "warning": f"{self.action_name} requires confirmation. Send this token back "
                       f"within {self.window_seconds // 60} minutes to proceed.",
        }

    def confirm(self, confirm_token: str) -> bool:
        """One-shot: a valid token is consumed whether or not the caller
        goes on to actually execute the action, same as Scatter's own
        pending-token pop -- a token can't be replayed."""
        self._prune()
        return self._pending.pop(confirm_token, None) is not None
