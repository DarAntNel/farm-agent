"""Tests for config loading, validation, and the device factory."""

from __future__ import annotations

import json

import pytest

from farm_agent.config.policy import FarmPolicy, load_policy
from farm_agent.config.wiring import build_actuators, build_sensors, load_wiring
from tests.fakes import FakeSerialTransport


def test_defaults_load_without_files():
    wiring = load_wiring()
    policy = load_policy()
    assert any(s["type"] == "soil_moisture" for s in wiring["sensors"])
    assert policy.strategy == "local_rules"
    assert policy.target_for("soil_1") == (400.0, 800.0)


def test_build_sensors_and_actuators_from_default_wiring():
    wiring = load_wiring()
    transport = FakeSerialTransport([{"soil_raw": 500, "temperature_c": 20}])
    sensors = build_sensors(wiring, transport=transport)
    assert {s.id for s in sensors} == {"soil_1", "temp_1"}
    actuators = build_actuators(wiring, transport=transport)
    assert actuators[0].id == "pump_1"


def test_wiring_override_from_file(tmp_path):
    cfg = {
        "sensors": [{"type": "temperature", "id": "t9", "field": "temperature_c"}],
        "actuators": [],
    }
    path = tmp_path / "wiring.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    wiring = load_wiring(str(path))
    assert wiring["sensors"][0]["id"] == "t9"


def test_wiring_validation_rejects_missing_type(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"sensors": [{"id": "x"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_wiring(str(path))


def test_policy_validation_rejects_bad_target(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"targets": {"s": {"low": 9, "high": 1}}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_policy(str(path))


def test_unknown_sensor_type_raises():
    wiring = {"sensors": [{"type": "does_not_exist", "id": "z"}], "actuators": []}
    with pytest.raises(KeyError):
        build_sensors(wiring, transport=FakeSerialTransport())


def test_limits_for_falls_back_to_default():
    policy = FarmPolicy({})
    limits = policy.limits_for("anything")
    assert limits.max_runtime_s > 0
