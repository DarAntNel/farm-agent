"""Tests for assessment and decision strategies (foundation-only deps)."""

from __future__ import annotations

from farm_agent.config.policy import FarmPolicy
from farm_agent.control.assess import find_deviations
from farm_agent.control.strategy import (
    LlmStrategy,
    LocalRulesStrategy,
    build_strategy,
)
from farm_agent.models import Reading


def make_policy() -> FarmPolicy:
    return FarmPolicy(
        {
            "strategy": "local_rules",
            "targets": {"soil_1": {"low": 400, "high": 800}},
            "rules": {
                "soil_1": {
                    "low": {"actuator_id": "pump_1", "action": "on", "duration_s": 180},
                }
            },
        }
    )


def test_find_deviations_detects_low():
    policy = make_policy()
    readings = [Reading("soil_1", "Soil", 300, "raw")]
    devs = find_deviations(readings, policy)
    assert len(devs) == 1
    assert devs[0].direction == "low"
    assert devs[0].sensor_id == "soil_1"


def test_find_deviations_detects_high():
    policy = make_policy()
    readings = [Reading("soil_1", "Soil", 900, "raw")]
    devs = find_deviations(readings, policy)
    assert devs[0].direction == "high"


def test_find_deviations_in_range_is_empty():
    policy = make_policy()
    readings = [Reading("soil_1", "Soil", 500, "raw")]
    assert find_deviations(readings, policy) == []


def test_find_deviations_skips_failed_and_untargeted():
    policy = make_policy()
    readings = [
        Reading.failure("soil_1", "Soil", "raw", "boom"),
        Reading("temp_1", "Temp", 999, "°C"),  # no target configured
    ]
    assert find_deviations(readings, policy) == []


def test_local_rules_emits_command_for_deviation():
    policy = make_policy()
    readings = [Reading("soil_1", "Soil", 300, "raw")]
    devs = find_deviations(readings, policy)
    cmds = LocalRulesStrategy(policy).decide(readings, devs, [])
    assert len(cmds) == 1
    assert cmds[0].actuator_id == "pump_1"
    assert cmds[0].action == "on"
    assert cmds[0].duration_s == 180
    assert cmds[0].source == "local_rules"


def test_local_rules_no_deviation_no_command():
    policy = make_policy()
    assert LocalRulesStrategy(policy).decide([], [], []) == []


def test_llm_strategy_is_stub():
    policy = make_policy()
    strat = LlmStrategy(policy)
    assert strat.wired is False
    assert strat.decide([], [], []) == []


def test_build_strategy_selects_by_policy():
    assert isinstance(build_strategy(make_policy()), LocalRulesStrategy)
    llm_policy = FarmPolicy({"strategy": "llm"})
    assert isinstance(build_strategy(llm_policy), LlmStrategy)


def test_build_strategy_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        build_strategy(FarmPolicy({"strategy": "nope"}))
