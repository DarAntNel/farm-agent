"""Wiring config: which devices exist, and the device factory.

Wiring describes the *hardware topology* — the serial link plus a list of
sensors and actuators, each naming a registered ``type`` and the port it lives
on. ``load_wiring`` reads it (from the ``WIRING_CONFIG`` env var pointing at a
JSON file, else the built-in defaults); ``build_sensors`` / ``build_actuators``
turn it into live objects via the registries.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from farm_agent.config.defaults import DEFAULT_WIRING
from farm_agent.registry import actuator_registry, sensor_registry


def load_wiring(path: Optional[str] = None) -> dict[str, Any]:
    """Load wiring config from ``path`` / ``$WIRING_CONFIG`` / defaults."""
    path = path or os.getenv("WIRING_CONFIG")
    if not path:
        return DEFAULT_WIRING
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    _validate_wiring(data)
    return data


def _validate_wiring(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("Wiring config must be a JSON object.")
    for section in ("sensors", "actuators"):
        entries = data.get(section, [])
        if not isinstance(entries, list):
            raise ValueError(f"Wiring '{section}' must be a list.")
        for entry in entries:
            if "type" not in entry or "id" not in entry:
                raise ValueError(
                    f"Each {section[:-1]} entry needs 'type' and 'id'; got {entry!r}."
                )


def _ensure_registered() -> None:
    """Import the concrete device modules so they self-register."""
    import farm_agent.actuators  # noqa: F401
    import farm_agent.sensors  # noqa: F401


def build_sensors(wiring: dict[str, Any], *, transport: Any, buses: Any = None) -> list:
    """Instantiate every sensor declared in ``wiring``."""
    _ensure_registered()
    sensors = []
    for cfg in wiring.get("sensors", []):
        cls = sensor_registry.get(cfg["type"])
        sensors.append(cls.from_config(cfg, transport=transport, buses=buses))
    return sensors


def build_actuators(wiring: dict[str, Any], *, transport: Any = None) -> list:
    """Instantiate every actuator declared in ``wiring``."""
    _ensure_registered()
    actuators = []
    for cfg in wiring.get("actuators", []):
        cls = actuator_registry.get(cfg["type"])
        actuators.append(cls.from_config(cfg, transport=transport))
    return actuators
