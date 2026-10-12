"""End-to-end control-cycle tests, all in-memory / no hardware."""

from __future__ import annotations

from farm_agent.actuators.fake import FakeActuator
from farm_agent.config.policy import FarmPolicy
from farm_agent.control.controller import ActuatorController
from farm_agent.control.cycle import ControlCycle
from farm_agent.control.strategy import LocalRulesStrategy
from farm_agent.events.store import InMemoryEventStore
from farm_agent.safety.guard import SafetyGuard
from farm_agent.safety.watchdog import Watchdog
from farm_agent.sensors.hub import SensorHub
from farm_agent.sensors.soil_moisture import SoilMoistureSensor
from tests.fakes import FakeClock, FakeSerialTransport


class _NoopTimer:
    """A timer that records but never fires — keeps cycle tests deterministic."""

    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback

    def start(self):
        pass

    def cancel(self):
        pass


def build_cycle(frame, *, dry_run=False, clock=None):
    policy = FarmPolicy(
        {
            "strategy": "local_rules",
            "targets": {"soil_1": {"low": 400, "high": 800}},
            "rules": {
                "soil_1": {"low": {"actuator_id": "pump_1", "action": "on", "duration_s": 9999}}
            },
            "safety": {"pump_1": {"max_runtime_s": 300, "cooldown_s": 600}},
        }
    )
    transport = FakeSerialTransport([frame])
    hub = SensorHub([SoilMoistureSensor.from_config({"id": "soil_1", "name": "Soil"}, transport=transport)])
    pump = FakeActuator("pump_1", "Water pump")
    events = InMemoryEventStore()
    guard = SafetyGuard(policy, clock=clock or FakeClock())
    watchdog = Watchdog(timer_factory=_NoopTimer)
    controller = ActuatorController([pump], guard, watchdog, events, dry_run=dry_run)
    cycle = ControlCycle(hub, controller, LocalRulesStrategy(policy), policy, events)
    return cycle, controller, pump, events


def test_dry_soil_triggers_guarded_pump():
    cycle, controller, pump, events = build_cycle({"soil_raw": 300})
    summary = cycle.run_once()
    assert summary["deviations"][0]["direction"] == "low"
    assert summary["results"][0]["accepted"] is True
    # Duration was clamped by the guard from 9999 to the 300s max.
    assert summary["results"][0]["applied"]["duration_s"] == 300
    assert pump.is_on is True
    assert len(pump.performed) == 1


def test_in_range_does_nothing():
    cycle, controller, pump, events = build_cycle({"soil_raw": 600})
    summary = cycle.run_once()
    assert summary["deviations"] == []
    assert summary["commands"] == []
    assert pump.is_on is False


def test_dry_run_does_not_fire():
    cycle, controller, pump, events = build_cycle({"soil_raw": 300}, dry_run=True)
    summary = cycle.run_once()
    assert summary["results"][0]["accepted"] is True
    assert "dry-run" in (summary["results"][0]["reason"] or "")
    assert pump.performed == []  # nothing actually fired
    assert pump.is_on is False


def test_events_recorded_in_order():
    cycle, controller, pump, events = build_cycle({"soil_raw": 300})
    cycle.run_once()
    types = [e.type for e in events.recent(50)]
    assert types[0] == "reading"
    assert "deviation" in types
    assert "decision" in types
    assert types[-1] == "actuation"


def test_cooldown_blocks_second_activation():
    clock = FakeClock()
    cycle, controller, pump, events = build_cycle({"soil_raw": 300}, clock=clock)
    first = cycle.run_once()
    assert first["results"][0]["accepted"] is True
    # Immediately run again: still within the 600s cooldown -> rejected.
    second = cycle.run_once()
    assert second["results"][0]["accepted"] is False
    assert "cooldown" in second["results"][0]["reason"].lower()
