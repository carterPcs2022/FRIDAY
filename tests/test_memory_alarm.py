"""tests/test_memory_alarm.py — the memory alarm warns before the OOM kill,
stays quiet below the threshold, and doesn't spam."""
from unittest import mock

from core.autonomous_agent import AutonomousAgent


def _agent():
    return AutonomousAgent()


def test_quiet_below_threshold():
    ag = _agent()
    with mock.patch.object(AutonomousAgent, "_memory_used_mb", return_value=100.0), \
         mock.patch.object(ag, "_alert") as alert:
        ag._memory_alarm()
    alert.assert_not_called()


def test_alerts_above_threshold_once_per_hour():
    ag = _agent()
    with mock.patch.object(AutonomousAgent, "_memory_used_mb", return_value=480.0), \
         mock.patch.object(ag, "_alert") as alert:
        ag._memory_alarm()
        ag._memory_alarm()  # inside the cooldown: must not alert again
    assert alert.call_count == 1
    assert alert.call_args.kwargs.get("priority") == "high"


def test_memory_reader_never_raises():
    assert AutonomousAgent._memory_used_mb() >= 0.0
