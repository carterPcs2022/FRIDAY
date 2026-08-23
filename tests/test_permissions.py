"""tests/test_permissions.py — core/permissions.py's risk-tier
classification and ConfirmationGate (V3 Phase 3), plus the two routes
that actually consume them: the newly two-step /friday/hulkbuster/deploy
and the /friday/permissions introspection endpoint.
"""
from unittest import mock

from core.permissions import ConfirmationGate, RiskLevel, classify_default, risk_for


class TestClassifyDefault:
    def test_get_is_read(self):
        assert classify_default({"GET"}) == RiskLevel.READ
        assert classify_default({"GET", "HEAD", "OPTIONS"}) == RiskLevel.READ

    def test_post_is_write(self):
        assert classify_default({"POST"}) == RiskLevel.WRITE

    def test_unlisted_route_never_defaults_below_write_for_post(self):
        """An unlisted POST route must land at WRITE, not READ -- the
        whole point of a default is to never silently under-classify
        something nobody got around to tagging."""
        assert classify_default({"POST", "OPTIONS"}) != RiskLevel.READ


class TestRiskFor:
    def test_explicit_registry_entry_wins(self):
        assert risk_for("email.email_send", {"POST"}) == RiskLevel.EXTERNAL_COMM
        assert risk_for("security.trigger_lockdown", {"POST"}) == RiskLevel.DESTRUCTIVE
        assert risk_for("security.hulkbuster_deploy", {"POST"}) == RiskLevel.DESTRUCTIVE

    def test_recovery_actions_stay_write_not_destructive(self):
        """hulkbuster_stand_down and scatter_reassemble are recovery
        actions -- same "friction works against you" reasoning
        core/scatter.py already documents for reassemble()."""
        assert risk_for("security.hulkbuster_stand_down", {"POST"}) == RiskLevel.WRITE
        assert risk_for("security.scatter_reassemble", {"POST"}) == RiskLevel.WRITE

    def test_unregistered_endpoint_falls_back_to_default(self):
        assert risk_for("some_blueprint.some_new_get_route", {"GET"}) == RiskLevel.READ
        assert risk_for("some_blueprint.some_new_post_route", {"POST"}) == RiskLevel.WRITE


class TestConfirmationGate:
    def test_request_issues_a_token_and_nothing_executes(self):
        gate = ConfirmationGate("Test action")
        result = gate.request()
        assert result["status"] == "awaiting_confirmation"
        assert "confirm_token" in result and len(result["confirm_token"]) > 0

    def test_confirm_with_correct_token_succeeds_once(self):
        gate = ConfirmationGate("Test action")
        token = gate.request()["confirm_token"]
        assert gate.confirm(token) is True
        # Tokens are one-shot -- replaying the same token must fail.
        assert gate.confirm(token) is False

    def test_confirm_with_wrong_or_empty_token_fails(self):
        gate = ConfirmationGate("Test action")
        gate.request()
        assert gate.confirm("not-a-real-token") is False
        assert gate.confirm("") is False

    def test_confirm_after_window_expires_fails(self):
        gate = ConfirmationGate("Test action", window_seconds=-1)  # already expired
        token = gate.request()["confirm_token"]
        assert gate.confirm(token) is False

    def test_gates_are_independent(self):
        """A token issued by one gate must not confirm a different
        gate's pending action -- e.g. a lockdown confirmation token
        (if lockdown ever grows one) can't double as a HulkBuster one."""
        gate_a = ConfirmationGate("Action A")
        gate_b = ConfirmationGate("Action B")
        token_a = gate_a.request()["confirm_token"]
        assert gate_b.confirm(token_a) is False
        assert gate_a.confirm(token_a) is True


class TestHulkbusterDeployTwoStep:
    def test_first_call_without_token_only_requests_confirmation(self, client):
        with mock.patch("routes.security.HULKBUSTER_OK", True), \
             mock.patch("routes.security.hulkbuster") as hb:
            resp = client.post("/friday/hulkbuster/deploy", json={"reason": "test", "ip": "1.2.3.4"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("status") == "awaiting_confirmation"
        assert not hb.deploy.called

    def test_second_call_with_valid_token_actually_deploys(self, client):
        with mock.patch("routes.security.HULKBUSTER_OK", True), \
             mock.patch("routes.security.hulkbuster") as hb, \
             mock.patch("services.friday_security.friday_security._blocked_ips", {"1.2.3.4"}):
            hb.deploy.return_value = {"deployed": True, "ip": "1.2.3.4", "ip_blocked": True}
            first = client.post("/friday/hulkbuster/deploy", json={"reason": "test", "ip": "1.2.3.4"})
            token = first.get_json()["confirm_token"]
            second = client.post(
                "/friday/hulkbuster/deploy",
                json={"reason": "test", "ip": "1.2.3.4", "confirm_token": token},
            )
        assert second.status_code == 200
        body = second.get_json()
        assert body["deployed"] is True
        # V3 Phase 13: the route independently re-checks the live
        # blocklist rather than just trusting deploy()'s own ip_blocked flag.
        assert body["verification"] == {
            "status": "verified", "detail": "1.2.3.4 confirmed present in the live blocklist", "verified": True,
        }
        hb.deploy.assert_called_once_with("test", "1.2.3.4")

    def test_invalid_token_is_rejected(self, client):
        with mock.patch("routes.security.HULKBUSTER_OK", True), \
             mock.patch("routes.security.hulkbuster") as hb:
            resp = client.post(
                "/friday/hulkbuster/deploy",
                json={"reason": "test", "confirm_token": "made-up-token"},
            )
        assert resp.status_code == 400
        assert not hb.deploy.called


class TestLockdownStaysSingleStep:
    """Regression guard for the deliberate exception documented in
    core/permissions.py: /friday/lockdown must NOT gain a confirmation
    step -- it's auth-exempt on purpose so it still works from a brand
    new device if the boss's phone is lost or stolen, and a confirm-token
    round trip would defeat that."""

    def test_lockdown_executes_on_a_single_call(self, client):
        with mock.patch("routes.security.LOCKDOWN_OK", True), \
             mock.patch("routes.security.suit_lockdown") as sl:
            sl.activate.return_value = {"locked": True}
            resp = client.post("/friday/lockdown")
        assert resp.status_code == 200
        assert resp.get_json() == {"locked": True}
        sl.activate.assert_called_once()


class TestPermissionsRoute:
    def test_lists_every_registered_route_across_four_tiers(self, client):
        resp = client.get("/friday/permissions")
        assert resp.status_code == 200
        body = resp.get_json()
        assert set(body["tiers"].keys()) == {"READ", "WRITE", "EXTERNAL_COMM", "DESTRUCTIVE"}
        assert sum(body["counts"].values()) == len(body["tiers"]["READ"]) + len(body["tiers"]["WRITE"]) + \
            len(body["tiers"]["EXTERNAL_COMM"]) + len(body["tiers"]["DESTRUCTIVE"])

    def test_known_destructive_and_external_comm_routes_show_up(self, client):
        resp = client.get("/friday/permissions")
        body = resp.get_json()
        assert "/friday/lockdown" in body["tiers"]["DESTRUCTIVE"]
        assert "/friday/hulkbuster/deploy" in body["tiers"]["DESTRUCTIVE"]
        assert "/friday/email/send" in body["tiers"]["EXTERNAL_COMM"]
        assert "/friday/hulkbuster/stand-down" in body["tiers"]["WRITE"]


class TestCapabilitiesRoute:
    """V3 Phase 3 -- /friday/capabilities replaced the old thin
    CAPABILITY_MAP-trigger-names stub in place (same path/method, no
    second competing route) with the full registry."""

    def test_lists_both_route_and_chat_sourced_capabilities(self, client):
        resp = client.get("/friday/capabilities")
        assert resp.status_code == 200
        body = resp.get_json()
        sources = {c["source"] for c in body["capabilities"]}
        assert sources == {"route", "chat"}
        assert body["count"] == len(body["capabilities"])

    def test_category_filter(self, client):
        resp = client.get("/friday/capabilities?category=mcu_capability")
        body = resp.get_json()
        assert body["count"] > 0
        assert all(c["category"] == "mcu_capability" for c in body["capabilities"])

    def test_hulkbuster_deploy_capability_shows_destructive_and_confirmation_required(self, client):
        resp = client.get("/friday/capabilities")
        body = resp.get_json()
        cap = next(c for c in body["capabilities"] if c["name"] == "route:security.hulkbuster_deploy")
        assert cap["risk_level"] == "DESTRUCTIVE"
        assert cap["requires_confirmation"] is True


class TestPolicyEvaluateRoute:
    def test_unknown_capability_is_404(self, client):
        resp = client.post("/friday/policy/evaluate", json={"capability": "route:nope.nope"})
        assert resp.status_code == 404

    def test_low_risk_capability_is_allowed_outright(self, client):
        resp = client.post("/friday/policy/evaluate", json={"capability": "route:email.email_summary"})
        assert resp.status_code == 200
        assert resp.get_json()["decision"] == "allow"

    def test_destructive_capability_without_token_requires_confirmation(self, client):
        resp = client.post("/friday/policy/evaluate",
                            json={"capability": "route:security.hulkbuster_deploy"})
        body = resp.get_json()
        assert body["decision"] == "confirm"
        assert body["confirm_token"]

    def test_destructive_capability_with_valid_token_is_allowed(self, client):
        first = client.post("/friday/policy/evaluate",
                             json={"capability": "route:security.hulkbuster_deploy"})
        token = first.get_json()["confirm_token"]
        second = client.post("/friday/policy/evaluate",
                              json={"capability": "route:security.hulkbuster_deploy",
                                    "confirm_token": token})
        assert second.get_json()["decision"] == "allow"
