"""tests/test_policy_engine.py — V3 migration Phase 5. PolicyEngine is a
thin facade over the existing core/permissions.py ConfirmationGate
pattern (see that module's docstring on why one gate per action
matters) — these tests check the facade's own decision logic, not
ConfirmationGate itself (already covered by tests/test_permissions.py).
"""
from core.capability_registry import Capability
from core.permissions import RiskLevel
from core.policy_engine import PolicyDecision, PolicyEngine


def _cap(name="cap", risk=RiskLevel.READ, requires_confirmation=False, available=True):
    return Capability(
        name=name, description="d", category="cat", risk_level=risk, source="route",
        requires_confirmation=requires_confirmation,
        availability_check=(lambda: available),
    )


class TestEvaluate:
    def test_unavailable_capability_is_denied(self):
        engine = PolicyEngine()
        result = engine.evaluate(_cap(available=False))
        assert result.decision == PolicyDecision.DENY
        assert "unavailable" in result.reason

    def test_no_confirmation_required_is_allowed_outright(self):
        engine = PolicyEngine()
        result = engine.evaluate(_cap(requires_confirmation=False))
        assert result.decision == PolicyDecision.ALLOW

    def test_confirmation_required_with_no_token_issues_one(self):
        engine = PolicyEngine()
        result = engine.evaluate(_cap(requires_confirmation=True))
        assert result.decision == PolicyDecision.CONFIRM
        assert result.confirm_token
        assert result.expires_seconds

    def test_confirmation_required_with_valid_token_is_allowed(self):
        engine = PolicyEngine()
        cap = _cap(requires_confirmation=True)
        first = engine.evaluate(cap)
        second = engine.evaluate(cap, confirm_token=first.confirm_token)
        assert second.decision == PolicyDecision.ALLOW

    def test_confirmation_required_with_invalid_token_is_denied(self):
        engine = PolicyEngine()
        result = engine.evaluate(_cap(requires_confirmation=True), confirm_token="made-up")
        assert result.decision == PolicyDecision.DENY

    def test_token_is_one_shot(self):
        engine = PolicyEngine()
        cap = _cap(requires_confirmation=True)
        first = engine.evaluate(cap)
        token = first.confirm_token
        engine.evaluate(cap, confirm_token=token)  # consumes it
        replay = engine.evaluate(cap, confirm_token=token)
        assert replay.decision == PolicyDecision.DENY

    def test_gate_is_per_capability_not_shared(self):
        """A pending confirmation on one capability must not confirm a
        different one -- the exact isolation core/permissions.py's own
        docstring requires of ConfirmationGate."""
        engine = PolicyEngine()
        cap_a = _cap(name="a", requires_confirmation=True)
        cap_b = _cap(name="b", requires_confirmation=True)
        token_a = engine.evaluate(cap_a).confirm_token
        cross = engine.evaluate(cap_b, confirm_token=token_a)
        assert cross.decision == PolicyDecision.DENY


class TestPolicyResultToDict:
    def test_allow_has_no_token_fields(self):
        engine = PolicyEngine()
        d = engine.evaluate(_cap()).to_dict()
        assert d["decision"] == "allow"
        assert "confirm_token" not in d

    def test_confirm_includes_token_fields(self):
        engine = PolicyEngine()
        d = engine.evaluate(_cap(requires_confirmation=True)).to_dict()
        assert d["decision"] == "confirm"
        assert "confirm_token" in d
        assert "expires_seconds" in d
