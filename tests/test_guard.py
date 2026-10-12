"""Tests for the deterministic :class:`SafetyGuard`.

Everything uses a :class:`FakeClock` and :class:`RecordingActuator`s so the guard
is exercised with no real time and no hardware. The policy is built from an
explicit dict so the limits under test are unambiguous.
"""

from __future__ import annotations

import pytest

from farm_agent.config.policy import FarmPolicy
from farm_agent.models import Command
from farm_agent.safety import SafetyGuard
from tests.fakes import FakeClock, RecordingActuator


def _policy() -> FarmPolicy:
    return FarmPolicy(
        {
            "safety": {
                "pump_1": {
                    "max_runtime_s": 300,
                    "cooldown_s": 600,
                    "max_activations_per_day": 2,
                    "mutually_exclusive_with": ["valve_1"],
                }
            }
        }
    )


def _actuators() -> dict[str, RecordingActuator]:
    return {
        "pump_1": RecordingActuator("pump_1", "Water pump"),
        "valve_1": RecordingActuator("valve_1", "Drain valve"),
    }


def _on(duration_s=None) -> Command:
    return Command(actuator_id="pump_1", action="on", duration_s=duration_s, source="llm")


def test_duration_clamped_to_max_runtime() -> None:
    guard = SafetyGuard(_policy(), clock=FakeClock())
    result = guard.review(_on(duration_s=9999), _actuators())
    assert result.accepted is True
    assert result.applied.duration_s == 300


def test_duration_none_filled_with_max_runtime() -> None:
    guard = SafetyGuard(_policy(), clock=FakeClock())
    result = guard.review(_on(duration_s=None), _actuators())
    assert result.accepted is True
    assert result.applied.duration_s == 300


def test_duration_below_max_is_left_alone() -> None:
    guard = SafetyGuard(_policy(), clock=FakeClock())
    result = guard.review(_on(duration_s=120), _actuators())
    assert result.accepted is True
    assert result.applied.duration_s == 120


def test_reject_while_in_cooldown_then_allow_after_advance() -> None:
    clock = FakeClock()
    guard = SafetyGuard(_policy(), clock=clock)
    actuators = _actuators()

    first = guard.review(_on(), actuators)
    assert first.accepted is True
    guard.record_activation("pump_1")

    # Still inside the 600s cooldown window -> rejected.
    clock.advance(300)
    blocked = guard.review(_on(), actuators)
    assert blocked.accepted is False
    assert "cooldown" in blocked.reason

    # Past the cooldown window -> allowed again.
    clock.advance(301)  # total 601s since activation
    allowed = guard.review(_on(), actuators)
    assert allowed.accepted is True


def test_reject_when_daily_cap_exceeded() -> None:
    clock = FakeClock()
    guard = SafetyGuard(_policy(), clock=clock)
    actuators = _actuators()

    # Cap is 2. Record two activations, spacing past cooldown so only the cap
    # (not the cooldown) is the reason for the eventual rejection.
    for _ in range(2):
        result = guard.review(_on(), actuators)
        assert result.accepted is True
        guard.record_activation("pump_1")
        clock.advance(700)  # clear the 600s cooldown

    third = guard.review(_on(), actuators)
    assert third.accepted is False
    assert "cap" in third.reason


def test_reject_on_mutual_exclusion() -> None:
    clock = FakeClock()
    guard = SafetyGuard(_policy(), clock=clock)
    actuators = _actuators()
    actuators["valve_1"]._is_on = True  # paired actuator currently on

    result = guard.review(_on(), actuators)
    assert result.accepted is False
    assert "valve_1" in result.reason


def test_mutual_exclusion_ok_when_paired_off() -> None:
    guard = SafetyGuard(_policy(), clock=FakeClock())
    actuators = _actuators()
    assert actuators["valve_1"].is_on is False
    result = guard.review(_on(), actuators)
    assert result.accepted is True


def test_off_always_allowed_and_not_rate_limited() -> None:
    clock = FakeClock()
    guard = SafetyGuard(_policy(), clock=clock)
    actuators = _actuators()

    # Even with the paired actuator on and no cooldown elapsed, off is allowed.
    actuators["valve_1"]._is_on = True
    guard.record_activation("pump_1")
    off = Command(actuator_id="pump_1", action="off", source="llm")
    result = guard.review(off, actuators)
    assert result.accepted is True
    assert result.applied.action == "off"


def test_unknown_actuator_uses_default_limits() -> None:
    # No "safety" entry for mixer_1 -> DEFAULT_LIMITS (max_runtime_s=300).
    guard = SafetyGuard(_policy(), clock=FakeClock())
    cmd = Command(actuator_id="mixer_1", action="on", duration_s=9999, source="llm")
    result = guard.review(cmd, _actuators())
    assert result.accepted is True
    assert result.applied.duration_s == 300
