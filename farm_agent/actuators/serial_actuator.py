"""An actuator wired to the Arduino, driven over the shared serial link.

Some actuators (e.g. a relay board hanging off the Arduino rather than the Pi's
own GPIO) are controlled by sending a short command line to the microcontroller.
:class:`SerialActuator` does exactly that and nothing more — it writes one line
per command through a :class:`~farm_agent.transport.LineSink` and lets the base
class track on/off state. No safety policy lives here (see the safety slice).
"""

from __future__ import annotations

from typing import Any

from farm_agent.actuators.base import Actuator
from farm_agent.models import Command
from farm_agent.registry import actuator_registry
from farm_agent.transport import LineSink


@actuator_registry.register("serial_actuator")
class SerialActuator(Actuator):
    """Drives an Arduino-side actuator by writing command lines to the device."""

    kind = "serial_actuator"

    def __init__(
        self,
        actuator_id: str,
        name: str,
        transport: LineSink,
        command_prefix: str,
    ) -> None:
        super().__init__(actuator_id, name)
        self._transport = transport
        self._prefix = command_prefix

    def _perform(self, command: Command) -> None:
        # The Arduino parses a simple whitespace-delimited line, e.g.
        # ``pump on 180`` or ``pump off``. A missing duration becomes an empty
        # token so the prefix/action are always in the same positions.
        duration = "" if command.duration_s is None else command.duration_s
        line = f"{self._prefix} {command.action} {duration}".rstrip()
        self._transport.write_line(line)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None) -> "SerialActuator":
        if transport is None:
            raise ValueError(
                "SerialActuator requires a transport (LineSink) to send commands."
            )
        # ``command`` is the Arduino-side name for this device; it defaults to the
        # actuator id when not separately configured.
        return cls(
            cfg["id"],
            cfg.get("name", cfg["id"]),
            transport,
            cfg.get("command", cfg["id"]),
        )
