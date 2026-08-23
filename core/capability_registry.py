"""core/capability_registry.py — V3 migration Phase 3: a metadata catalog
answering "what can FRIDAY do, and is it usable right now" without
duplicating a single handler.

Two sources, both introspected rather than hand-maintained duplicates:

1. Every registered Flask route, via the same current_app.url_map
   introspection routes/orchestration.py's /friday/permissions already
   uses, risk-classified through the existing core/permissions.py (not
   a second, competing risk system). This alone covers the large
   majority of FRIDAY's real capability surface — email, calendar,
   tasks, security, self-repair, veronica, offline mode, everything
   that's a route — for free and accurately.

2. core/friday_capabilities.py's CAPABILITY_MAP — FRIDAY's own named,
   chat-only abilities that never became HTTP routes. Hand-described
   once below; tests/test_capability_registry.py checks this list's
   keys against the real CAPABILITY_MAP so it can't silently drift.
   These entries carry NO callable — the registry describes them, it
   doesn't invoke them. server.py's command() dispatch chain and
   CAPABILITY_MAP's own lambdas remain the one real invocation path.

server.py's ~50 chat-only _cmd_* trigger functions (weather, news,
tasks, medications, …) are deliberately NOT enumerated here yet — that
would mean hand-describing and risk-guessing fifty functions in one
pass, with real risk of getting several wrong. "Migrate incrementally"
is the phase's own instruction; CAPABILITY_MAP is the natural, already-
named starting slice, not the finish line.

Honest-state finding from this audit (the concrete case the V3
directive's Phase 25 calls out by name): core/friday_capabilities.py's
hack_security() and remote_system_control() were pure flavor — a voice
line and a success dict, no real system behind either — AND unreachable
from chat entirely, with no trigger phrase wired up at all. The boss
chose to wire them into CAPABILITY_MAP rather than delete them, so
they're now reachable, but still exactly as simulated as their own
docstrings say. Both are marked simulated=True below, distinct from
every other CAPABILITY_MAP entry.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.permissions import RiskLevel, risk_for


@dataclass
class Capability:
    name: str
    description: str
    category: str
    risk_level: RiskLevel
    source: str  # "route" | "chat"
    reversible: bool = True
    requires_confirmation: bool = False
    simulated: bool = False
    endpoint: Optional[str] = None       # Flask endpoint, route-sourced only
    trigger: Optional[str] = None        # chat trigger phrase, chat-sourced only
    availability_check: Optional[Callable[[], bool]] = field(default=None, repr=False)

    def is_available(self) -> bool:
        """True unless a check is registered and it explicitly says no —
        an unregistered check means "presumed available," not "verified
        available." See this module's docstring for why route-sourced
        entries mostly fall in that presumed bucket for now: the route
        itself already degrades to a clean {"error": "unavailable"} JSON
        when its backing service is unconfigured, which is the existing
        honesty mechanism for those ~167 entries."""
        if self.availability_check is None:
            return True
        try:
            return bool(self.availability_check())
        except Exception:
            return False


class CapabilityRegistry:
    def __init__(self):
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Optional[Capability]:
        return self._capabilities.get(name)

    def all(self) -> list[Capability]:
        return list(self._capabilities.values())

    def by_category(self, category: str) -> list[Capability]:
        return [c for c in self._capabilities.values() if c.category == category]

    def available(self) -> list[Capability]:
        return [c for c in self._capabilities.values() if c.is_available()]

    def clear(self) -> None:
        self._capabilities.clear()


def _endpoint_category(endpoint: str) -> str:
    """Blueprint name is already a reasonable category ('email',
    'security', 'offline', ...) -- server.py's own bare routes (no dot
    in the endpoint) fall under 'core'."""
    return endpoint.split(".", 1)[0] if "." in endpoint else "core"


def register_routes(registry: CapabilityRegistry, url_map) -> int:
    """Populates the registry from every live Flask route. Returns the
    count registered. Safe to call more than once (e.g. in tests against
    a fresh registry) -- registration is a straight overwrite by name."""
    count = 0
    for rule in url_map.iter_rules():
        if rule.rule == "/static/<path:filename>":
            continue
        methods = rule.methods - {"HEAD", "OPTIONS"}
        tier = risk_for(rule.endpoint, methods)
        registry.register(Capability(
            name=f"route:{rule.endpoint}",
            description=rule.rule,
            category=_endpoint_category(rule.endpoint),
            risk_level=tier,
            source="route",
            reversible=tier < RiskLevel.DESTRUCTIVE,
            requires_confirmation=tier == RiskLevel.DESTRUCTIVE,
            endpoint=rule.endpoint,
        ))
        count += 1
    return count


def _brain_available() -> bool:
    from core.friday_brain import is_anthropic_healthy, is_groq_healthy
    return is_anthropic_healthy() or is_groq_healthy()


def _veronica_available() -> bool:
    from core.app_state import VERONICA_OK
    return VERONICA_OK


def _pushcut_mom_available() -> bool:
    from services.friday_pushcut import MOM_WEBHOOK_URL
    return bool(MOM_WEBHOOK_URL)


# name -> (description, requires_confirmation, simulated, availability_check)
_CHAT_CAPABILITY_META: dict[str, tuple] = {
    "analyze fighting": ("Fighting-pattern analysis via FRIDAY's reasoning", False, False, _brain_available),
    "fighting pattern": ("Fighting-pattern analysis via FRIDAY's reasoning", False, False, _brain_available),
    "contusion": ("Logs a contusion check and speaks the area — no medical system behind it", False, False, None),
    "emergency contact": ("Speaks an emergency-contacted line and sends a critical Pushover alert", False, False, None),
    "intel on": ("Intelligence brief via FRIDAY's reasoning, plus a web search if available", False, False, _brain_available),
    "scan for": ("Disaster-scan brief via FRIDAY's reasoning", False, False, _brain_available),
    "atmospheric": ("Object-detection brief via FRIDAY's reasoning", False, False, _brain_available),
    "life functions": ("Reads the real emotional-trend log as a life-functions stand-in", False, False, None),
    "barn door": ("Speaks a containment line and sets a flag — no real containment system", False, False, None),
    "critical scan": ("Critical-scan brief via FRIDAY's reasoning, spoken aloud", False, False, _brain_available),
    "evacuation plan": ("Evacuation-plan brief via FRIDAY's reasoning", False, False, _brain_available),
    "physics calculation": ("Physics/risk analysis via FRIDAY's reasoning", False, False, _brain_available),
    "monitor internet": ("Internet-monitoring brief via FRIDAY's reasoning, plus news search if available", False, False, _brain_available),
    "deploy veronica": ("Runs a real Veronica monitor pass — restores/alerts on watched components", False, False, _veronica_available),
    "call mom": ("Fires the pre-configured Pushcut 'Call Mom' notification", False, False, _pushcut_mom_available),
    "call my mom": ("Fires the pre-configured Pushcut 'Call Mom' notification", False, False, _pushcut_mom_available),
    # The two honest exceptions -- see this module's docstring.
    "hack security": ("Pure flavor: speaks a line, no real system accessed", False, True, None),
    "remote system control": ("Pure flavor: speaks a line, no real system controlled", False, True, None),
}


def register_chat_capabilities(registry: CapabilityRegistry) -> int:
    try:
        from core.friday_capabilities import CAPABILITY_MAP
    except Exception:
        # Same degrade-gracefully convention as every *_OK flag elsewhere
        # in this codebase -- a broken friday_capabilities.py shouldn't
        # take the whole registry (or /friday/capabilities) down with it.
        return 0

    count = 0
    for trigger in CAPABILITY_MAP:
        meta = _CHAT_CAPABILITY_META.get(trigger)
        if meta is None:
            continue
        description, requires_confirmation, simulated, availability_check = meta
        registry.register(Capability(
            name=f"chat:{trigger}",
            description=description,
            category="mcu_capability",
            risk_level=RiskLevel.WRITE,
            source="chat",
            reversible=True,
            requires_confirmation=requires_confirmation,
            simulated=simulated,
            trigger=trigger,
            availability_check=availability_check,
        ))
        count += 1
    return count


def build_registry(url_map) -> CapabilityRegistry:
    """Fresh registry populated from both sources. Call with
    current_app.url_map at request time (or app.url_map at startup) --
    not cached at import time, since routes register after this module
    loads."""
    registry = CapabilityRegistry()
    register_routes(registry, url_map)
    register_chat_capabilities(registry)
    return registry
