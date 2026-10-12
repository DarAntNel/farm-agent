"""A no-hardware actuator used by simulation mode and tests.

:class:`FakeActuator` is the actuator mirror of ``FakeSerialTransport``: it
performs no real action, it simply records every :class:`Command` it is asked to
perform. That makes it the default actuator in ``SIMULATE=true`` mode and a handy
spy in tests where you want to assert *what* was commanded without any device.
"""

from __future__ import annotations

from typing import Any

from farm_agent.actuators.base import Actuator
from farm_agent.models import Command
from farm_agent.registry import actuator_registry


@actuator_registry.register("fake")
class FakeActuator(Actuator):
    """An actuator that records commands instead of touching hardware."""

    kind = "fake"

    def __init__(self, actuator_id: str, name: str = "fake") -> None:
        super().__init__(actuator_id, name)
        # Every command handed to :meth:`_perform` lands here in order, so tests
        # and the simulation UI can inspect exactly what was requested.
        self.performed: list[Command] = []

    def _perform(self, command: Command) -> None:
        self.performed.append(command)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None) -> "FakeActuator":
        return cls(cfg["id"], cfg.get("name", "fake"))
