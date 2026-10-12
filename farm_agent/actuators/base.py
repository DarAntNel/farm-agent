"""Actuator interfaces.

An :class:`Actuator` is the mirror image of a sensor: it *acts on* the
environment instead of observing it. Crucially, nothing outside this package
calls ``apply`` directly — all commands flow through the
:class:`~farm_agent.control.controller.ActuatorController`, which runs the
safety guard and watchdog first. The base class here only models the raw
device; it enforces no policy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from farm_agent.models import ActuatorResult, Command, utc_now_iso


class Actuator(ABC):
    """The uniform interface for every actuator."""

    kind: str = "actuator"

    def __init__(self, actuator_id: str, name: str) -> None:
        self._id = actuator_id
        self._name = name
        self._is_on: bool = False
        self._since: Optional[str] = None

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_on(self) -> bool:
        return self._is_on

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None) -> "Actuator":
        """Build an instance from one wiring-config entry. Subclass-specific."""
        raise NotImplementedError(
            f"{cls.__name__} must implement from_config()."
        )

    @abstractmethod
    def _perform(self, command: Command) -> None:
        """Do the raw hardware action for ``command``. Subclass responsibility.

        May raise on hardware failure; :meth:`apply` turns that into a rejected
        :class:`ActuatorResult`.
        """
        raise NotImplementedError

    def apply(self, command: Command) -> ActuatorResult:
        """Perform ``command`` and update tracked state.

        This is the *raw* apply — it assumes the command has already been
        validated by the safety guard.
        """
        try:
            self._perform(command)
        except Exception as exc:
            return ActuatorResult.rejected(self.id, f"hardware error: {exc}")

        if command.action == "on":
            self._is_on = True
            self._since = utc_now_iso()
        elif command.action == "off":
            self._is_on = False
            self._since = utc_now_iso()
        return ActuatorResult.ok(self.id, command)

    def safe_off(self) -> ActuatorResult:
        """Force the actuator to its safe (off) state."""
        return self.apply(Command(actuator_id=self.id, action="off", source="system"))

    def state(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "is_on": self._is_on,
            "since": self._since,
        }
