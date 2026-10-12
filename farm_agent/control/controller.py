"""The actuator controller — the one place commands reach hardware.

Every command flows through here, so the safety guard, the auto-off watchdog,
the event log, and dry-run all apply uniformly. Nothing else in the system calls
``Actuator.apply`` directly.
"""

from __future__ import annotations

from typing import Optional

from farm_agent.actuators.base import Actuator
from farm_agent.events.store import EventStore
from farm_agent.models import ActuatorResult, Command, Event
from farm_agent.safety.guard import SafetyGuard
from farm_agent.safety.watchdog import Watchdog


class ActuatorController:
    def __init__(
        self,
        actuators: list[Actuator],
        guard: SafetyGuard,
        watchdog: Watchdog,
        event_store: EventStore,
        *,
        dry_run: bool = False,
    ) -> None:
        self._actuators = {a.id: a for a in actuators}
        self._guard = guard
        self._watchdog = watchdog
        self._events = event_store
        self._dry_run = dry_run

    # -- introspection ---------------------------------------------------- #
    def get(self, actuator_id: str) -> Actuator:
        return self._actuators[actuator_id]  # raises KeyError -> web maps to 404

    def states(self) -> list[dict]:
        return [a.state() for a in self._actuators.values()]

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    # -- lifecycle -------------------------------------------------------- #
    def safe_init(self) -> None:
        """Force every actuator to its safe (off) state at startup."""
        self._watchdog.cancel_all()
        for actuator in self._actuators.values():
            actuator.safe_off()

    def shutdown(self) -> None:
        self._watchdog.cancel_all()

    # -- the single command chokepoint ------------------------------------ #
    def execute(self, command: Command) -> ActuatorResult:
        """Validate ``command`` through the guard, then apply it (unless dry-run)."""
        if command.actuator_id not in self._actuators:
            raise KeyError(command.actuator_id)
        actuator = self._actuators[command.actuator_id]

        decision = self._guard.review(command, self._actuators)
        if not decision.accepted:
            self._record(command, decision)
            return decision

        approved = decision.applied or command

        if self._dry_run:
            result = ActuatorResult.ok(
                approved.actuator_id, approved, reason="dry-run: not applied"
            )
            self._record(command, result)
            return result

        result = actuator.apply(approved)
        if result.accepted:
            if approved.action == "on":
                self._guard.record_activation(approved.actuator_id)
                if approved.duration_s:
                    self._watchdog.schedule(
                        approved.actuator_id,
                        approved.duration_s,
                        lambda aid=approved.actuator_id: self._auto_off(aid),
                    )
            elif approved.action == "off":
                self._watchdog.cancel(approved.actuator_id)
        self._record(command, result)
        return result

    # -- internals -------------------------------------------------------- #
    def _auto_off(self, actuator_id: str) -> None:
        actuator = self._actuators.get(actuator_id)
        if actuator is None:
            return
        result = actuator.safe_off()
        self._events.record(
            Event("actuation", {"auto_off": True, "result": result.to_dict()})
        )

    def _record(self, requested: Command, result: ActuatorResult) -> None:
        self._events.record(
            Event(
                "actuation",
                {
                    "requested": requested.to_dict(),
                    "result": result.to_dict(),
                    "dry_run": self._dry_run,
                },
            )
        )
