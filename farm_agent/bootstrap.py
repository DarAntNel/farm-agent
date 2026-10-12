"""Composition root: build the whole object graph from config + env.

This is the only place that decides *which* concrete collaborators to wire
together, based on runtime mode:

* ``SIMULATE=true`` — use simulated transport/buses and fake actuators, so the
  system runs end-to-end with no hardware.
* ``DRY_RUN=true``  — real sensing, but the controller logs actuator commands
  instead of firing them.

Everything downstream depends only on the injected objects, never on these
decisions.
"""

from __future__ import annotations

import os
from typing import Any

from farm_agent.actuators.fake import FakeActuator
from farm_agent.config import build_actuators, build_sensors, load_policy, load_wiring
from farm_agent.control.controller import ActuatorController
from farm_agent.control.cycle import ControlCycle
from farm_agent.control.strategy import build_strategy
from farm_agent.events.store import build_event_store
from farm_agent.safety.guard import SafetyGuard
from farm_agent.safety.watchdog import Watchdog
from farm_agent.sensors.hub import SensorHub
from farm_agent.sim import SimBuses, SimulatedTransport
from farm_agent.transport import SerialTransport
from farm_agent.web.app import create_app


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def build_system(*, simulate: bool | None = None, dry_run: bool | None = None):
    """Build and return ``(app, cycle, controller, hub, event_store)``."""
    simulate = _env_bool("SIMULATE") if simulate is None else simulate
    dry_run = _env_bool("DRY_RUN") if dry_run is None else dry_run

    wiring = load_wiring()
    policy = load_policy()

    # Transport + buses (real or simulated).
    if simulate:
        transport: Any = SimulatedTransport()
        buses: Any = SimBuses()
    else:
        serial_cfg = wiring.get("serial", {})
        transport = SerialTransport(
            serial_cfg.get("port", "/dev/arduino"),
            int(serial_cfg.get("baud", 9600)),
            float(serial_cfg.get("timeout", 5.0)),
        )
        buses = None

    # Sensors.
    sensors = build_sensors(wiring, transport=transport, buses=buses)
    hub = SensorHub(sensors)

    # Actuators: in simulation, substitute fakes preserving id/name.
    if simulate:
        actuators = [
            FakeActuator(cfg["id"], cfg.get("name", cfg["id"]))
            for cfg in wiring.get("actuators", [])
        ]
    else:
        actuators = build_actuators(wiring, transport=transport)

    # Event store, safety spine, controller, strategy, cycle.
    es_cfg = wiring.get("event_store", {"kind": "memory"})
    event_store = build_event_store(es_cfg.get("kind", "memory"), es_cfg.get("path"))
    guard = SafetyGuard(policy)
    watchdog = Watchdog()
    controller = ActuatorController(
        actuators, guard, watchdog, event_store, dry_run=dry_run
    )
    controller.safe_init()  # never boot into an unknown "on" state
    strategy = build_strategy(policy)
    cycle = ControlCycle(hub, controller, strategy, policy, event_store)

    app = create_app(
        hub, controller, cycle, event_store, api_token=os.getenv("API_TOKEN")
    )
    return app, cycle, controller, hub, event_store
