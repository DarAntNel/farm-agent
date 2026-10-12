"""HTTP layer tests via Flask's test client (no hardware, no real timers)."""

from __future__ import annotations

import pytest

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
from farm_agent.web.app import create_app
from tests.fakes import FakeClock, FakeSerialTransport

TOKEN = "secret-token"


class _NoopTimer:
    def __init__(self, delay, callback):
        self.callback = callback

    def start(self):
        pass

    def cancel(self):
        pass


@pytest.fixture
def client():
    policy = FarmPolicy(
        {
            "strategy": "local_rules",
            "targets": {"soil_1": {"low": 400, "high": 800}},
            "rules": {
                "soil_1": {"low": {"actuator_id": "pump_1", "action": "on", "duration_s": 60}}
            },
            "safety": {"pump_1": {"max_runtime_s": 120, "cooldown_s": 600}},
        }
    )
    transport = FakeSerialTransport([{"soil_raw": 300, "temperature_c": 21.0}])
    hub = SensorHub(
        [SoilMoistureSensor.from_config({"id": "soil_1", "name": "Soil"}, transport=transport)]
    )
    pump = FakeActuator("pump_1", "Water pump")
    events = InMemoryEventStore()
    guard = SafetyGuard(policy, clock=FakeClock())
    controller = ActuatorController(
        [pump], guard, Watchdog(timer_factory=_NoopTimer), events
    )
    cycle = ControlCycle(hub, controller, LocalRulesStrategy(policy), policy, events)
    app = create_app(hub, controller, cycle, events, api_token=TOKEN)
    app.testing = True
    return app.test_client()


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_health_and_home(client):
    assert client.get("/health").get_json()["status"] == "healthy"
    assert client.get("/").get_json()["application"] == "farm-agent"


def test_legacy_sensor_endpoint(client):
    data = client.get("/sensor").get_json()
    assert data["soil_raw"] == 300
    assert "timestamp" in data


def test_sensors_and_one(client):
    allr = client.get("/sensors").get_json()["sensors"]
    assert any(s["sensor_id"] == "soil_1" for s in allr)
    assert client.get("/sensors/soil_1").get_json()["value"] == 300
    assert client.get("/sensors/nope").status_code == 404


def test_actuators_list_and_404(client):
    assert client.get("/actuators").get_json()["actuators"][0]["id"] == "pump_1"
    assert client.get("/actuators/ghost").status_code == 404


def test_command_requires_token(client):
    r = client.post("/actuators/pump_1/command", json={"action": "on"})
    assert r.status_code == 403


def test_command_with_token_accepted(client):
    r = client.post("/actuators/pump_1/command", json={"action": "on", "duration_s": 30}, headers=auth())
    assert r.status_code == 200
    assert r.get_json()["accepted"] is True


def test_command_unknown_actuator_404(client):
    r = client.post("/actuators/ghost/command", json={"action": "on"}, headers=auth())
    assert r.status_code == 404


def test_command_rejected_by_guard_is_422(client):
    # First activation succeeds, second is inside cooldown -> guard rejects -> 422.
    client.post("/actuators/pump_1/command", json={"action": "on"}, headers=auth())
    r = client.post("/actuators/pump_1/command", json={"action": "on"}, headers=auth())
    assert r.status_code == 422
    assert "cooldown" in r.get_json()["reason"].lower()


def test_control_tick_requires_token_then_runs(client):
    assert client.post("/control/tick").status_code == 403
    r = client.post("/control/tick", headers=auth())
    assert r.status_code == 200
    assert r.get_json()["strategy"] == "local_rules"


def test_control_status_and_events(client):
    assert client.get("/control/status").get_json()["strategy"] == "local_rules"
    client.post("/control/tick", headers=auth())
    assert len(client.get("/events").get_json()["events"]) > 0
