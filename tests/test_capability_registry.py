"""tests/test_capability_registry.py — V3 migration Phase 3. Two things
matter here: the registry doesn't silently drop or duplicate routes
(it's built from the same current_app.url_map every other introspection
route already uses), and the hand-described chat-only entries can't
drift from the real CAPABILITY_MAP without a test catching it.
"""
from core.capability_registry import (
    Capability,
    CapabilityRegistry,
    _CHAT_CAPABILITY_META,
    build_registry,
    register_chat_capabilities,
    register_routes,
)
from core.permissions import RiskLevel


class TestCapability:
    def test_available_by_default_with_no_check(self):
        cap = Capability("x", "desc", "cat", RiskLevel.READ, source="route")
        assert cap.is_available() is True

    def test_availability_check_true(self):
        cap = Capability("x", "desc", "cat", RiskLevel.READ, source="chat",
                          availability_check=lambda: True)
        assert cap.is_available() is True

    def test_availability_check_false(self):
        cap = Capability("x", "desc", "cat", RiskLevel.READ, source="chat",
                          availability_check=lambda: False)
        assert cap.is_available() is False

    def test_availability_check_exception_means_unavailable_not_a_crash(self):
        def boom():
            raise RuntimeError("service down")
        cap = Capability("x", "desc", "cat", RiskLevel.READ, source="chat",
                          availability_check=boom)
        assert cap.is_available() is False


class TestCapabilityRegistry:
    def test_register_and_get(self):
        registry = CapabilityRegistry()
        cap = Capability("x", "desc", "cat", RiskLevel.READ, source="route")
        registry.register(cap)
        assert registry.get("x") is cap

    def test_get_unknown_returns_none(self):
        assert CapabilityRegistry().get("nope") is None

    def test_by_category_filters(self):
        registry = CapabilityRegistry()
        registry.register(Capability("a", "d", "email", RiskLevel.READ, source="route"))
        registry.register(Capability("b", "d", "security", RiskLevel.READ, source="route"))
        assert [c.name for c in registry.by_category("email")] == ["a"]

    def test_available_excludes_unavailable_capabilities(self):
        registry = CapabilityRegistry()
        registry.register(Capability("healthy", "d", "cat", RiskLevel.READ, source="chat",
                                      availability_check=lambda: True))
        registry.register(Capability("broken", "d", "cat", RiskLevel.READ, source="chat",
                                      availability_check=lambda: False))
        assert [c.name for c in registry.available()] == ["healthy"]


class TestRegisterRoutes:
    def test_populates_from_real_app_url_map(self, app):
        registry = CapabilityRegistry()
        count = register_routes(registry, app.url_map)
        assert count > 100  # the real app has ~168 routes
        assert registry.get("route:email.email_send") is not None

    def test_skips_static_file_route(self, app):
        registry = CapabilityRegistry()
        register_routes(registry, app.url_map)
        assert all(c.description != "/static/<path:filename>" for c in registry.all())

    def test_destructive_route_requires_confirmation_and_is_not_reversible(self, app):
        registry = CapabilityRegistry()
        register_routes(registry, app.url_map)
        cap = registry.get("route:security.hulkbuster_deploy")
        assert cap.risk_level == RiskLevel.DESTRUCTIVE
        assert cap.requires_confirmation is True
        assert cap.reversible is False

    def test_read_route_does_not_require_confirmation(self, app):
        registry = CapabilityRegistry()
        register_routes(registry, app.url_map)
        cap = registry.get("route:email.email_summary")
        assert cap.requires_confirmation is False
        assert cap.reversible is True


class TestRegisterChatCapabilities:
    def test_metadata_covers_every_real_capability_map_entry(self):
        """Catches drift: if CAPABILITY_MAP gains or loses a trigger and
        this hand-written metadata dict isn't updated to match, this
        test fails instead of the registry silently under- or
        over-reporting FRIDAY's real chat-only capabilities."""
        from core.friday_capabilities import CAPABILITY_MAP
        assert set(CAPABILITY_MAP.keys()) == set(_CHAT_CAPABILITY_META.keys())

    def test_registers_one_capability_per_trigger(self):
        registry = CapabilityRegistry()
        from core.friday_capabilities import CAPABILITY_MAP
        count = register_chat_capabilities(registry)
        assert count == len(CAPABILITY_MAP)

    def test_hack_security_and_remote_system_control_are_not_registered(self):
        """Audit finding, not a design choice: neither method is wired
        into the real CAPABILITY_MAP at all (verified against the
        actual dict, not assumed) -- they're unreachable dead code, not
        merely simulated. Registering them as capabilities would
        misrepresent that."""
        from core.friday_capabilities import CAPABILITY_MAP
        assert "hack security" not in CAPABILITY_MAP
        assert "remote system control" not in CAPABILITY_MAP
        registry = CapabilityRegistry()
        register_chat_capabilities(registry)
        assert registry.get("chat:hack security") is None
        assert registry.get("chat:remote system control") is None

    def test_ordinary_capability_is_not_marked_simulated(self):
        registry = CapabilityRegistry()
        register_chat_capabilities(registry)
        cap = registry.get("chat:deploy veronica")
        assert cap.simulated is False

    def test_missing_friday_capabilities_module_degrades_to_zero_not_a_crash(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "core.friday_capabilities":
                raise ImportError("simulated failure")
            return real_import(name, *args, **kwargs)

        registry = CapabilityRegistry()
        monkeypatch.setattr(builtins, "__import__", fake_import)
        count = register_chat_capabilities(registry)
        assert count == 0
        assert registry.all() == []


class TestBuildRegistry:
    def test_combines_both_sources(self, app):
        registry = build_registry(app.url_map)
        assert registry.get("route:email.email_send") is not None
        assert registry.get("chat:deploy veronica") is not None
