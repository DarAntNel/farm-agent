"""Built-in default configuration.

Two *separate* concerns (see docs/modules/config.md):

* **Wiring** — which devices exist and the port each is on. Hardware topology.
* **Policy** — target ranges, decision rules, safety limits, strategy choice.
  Farming behaviour.

The defaults below let the app boot and do something useful in simulation with
no external files.
"""

from __future__ import annotations

from typing import Any

DEFAULT_WIRING: dict[str, Any] = {
    "serial": {"port": "/dev/arduino", "baud": 9600, "timeout": 5.0},
    "sensors": [
        {
            "type": "soil_moisture",
            "id": "soil_1",
            "name": "Soil moisture",
            "field": "soil_raw",
        },
        {
            "type": "temperature",
            "id": "temp_1",
            "name": "Air/soil temperature",
            "field": "temperature_c",
        },
    ],
    "actuators": [
        {
            "type": "serial_actuator",
            "id": "pump_1",
            "name": "Water pump",
            "command": "pump",
        },
    ],
    "event_store": {"kind": "memory"},
}

DEFAULT_POLICY: dict[str, Any] = {
    "strategy": "local_rules",
    # Target ranges keyed by sensor id. A reading outside [low, high] is a
    # deviation.
    "targets": {
        "soil_1": {"low": 400, "high": 800},
        "temp_1": {"low": 5, "high": 35},
    },
    # Rules mapping a deviation to a command. Keyed by sensor id then direction.
    "rules": {
        "soil_1": {
            "low": {"actuator_id": "pump_1", "action": "on", "duration_s": 180},
        },
    },
    # Per-actuator safety limits.
    "safety": {
        "pump_1": {
            "max_runtime_s": 300,
            "cooldown_s": 600,
            "max_activations_per_day": 24,
            "mutually_exclusive_with": [],
        },
    },
}
