"""core/policy_engine.py — V3 migration Phase 5: one evaluate() entry
point for "is this capability invocation allowed right now," unifying
core/permissions.py's risk tiers and ConfirmationGate behind a single
call instead of every DESTRUCTIVE route hand-rolling its own request/
confirm dance (see routes/security.py's hulkbuster_deploy for the
pattern this generalizes for anything new).

Deliberately does NOT replace core/permissions.py, core/access_auth.py,
or any existing route's own confirm-gate — the V3 directive is explicit
that unifying must not mean building a second competing permission
system. access_auth.py's bearer-token check still runs first, at the
Flask level, for every request regardless of this engine; PolicyEngine
only decides how much a request that already passed that gate should
cost to actually execute. Existing hand-rolled gates (HulkBuster,
Scatter, self-repair) are left exactly as they are working today —
PolicyEngine is here for new capability call sites (like the
/friday/policy/evaluate route below) to use going forward, not a
mandatory migration of what already works.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.capability_registry import Capability
from core.permissions import ConfirmationGate


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


@dataclass
class PolicyResult:
    decision: PolicyDecision
    reason: str
    confirm_token: Optional[str] = None
    expires_seconds: Optional[int] = None

    def to_dict(self) -> dict:
        d = {"decision": self.decision.value, "reason": self.reason}
        if self.confirm_token:
            d["confirm_token"] = self.confirm_token
            d["expires_seconds"] = self.expires_seconds
        return d


class PolicyEngine:
    """One ConfirmationGate per capability name — same isolation
    core/permissions.py's own docstring requires ("one gate per action,
    not one gate shared across unrelated destructive actions"), so a
    pending confirmation on one capability can't accidentally confirm
    a different one."""

    def __init__(self):
        self._gates: dict[str, ConfirmationGate] = {}

    def _gate_for(self, capability: Capability) -> ConfirmationGate:
        if capability.name not in self._gates:
            self._gates[capability.name] = ConfirmationGate(capability.name)
        return self._gates[capability.name]

    def evaluate(self, capability: Capability, confirm_token: str = None) -> PolicyResult:
        if not capability.is_available():
            return PolicyResult(PolicyDecision.DENY, "capability unavailable")

        if not capability.requires_confirmation:
            return PolicyResult(PolicyDecision.ALLOW, "no confirmation required for this risk tier")

        gate = self._gate_for(capability)
        if not confirm_token:
            request = gate.request()
            return PolicyResult(
                PolicyDecision.CONFIRM, request["warning"],
                confirm_token=request["confirm_token"], expires_seconds=request["expires_seconds"],
            )
        if gate.confirm(confirm_token):
            return PolicyResult(PolicyDecision.ALLOW, "confirmed")
        return PolicyResult(PolicyDecision.DENY, "confirmation missing or expired — request again")


policy_engine = PolicyEngine()
