"""The control cycle — one pass of sense -> decide -> act.

This is the minimal orchestration spine. A background scheduler that calls
``run_once`` on an interval is a later sub-project; for now the cycle is driven
on demand (``POST /control/tick``) and by tests.
"""

from __future__ import annotations

from typing import Any

from farm_agent.config.policy import FarmPolicy
from farm_agent.control.assess import find_deviations
from farm_agent.control.controller import ActuatorController
from farm_agent.control.strategy import DecisionStrategy
from farm_agent.events.store import EventStore
from farm_agent.models import Event
from farm_agent.sensors.hub import SensorHub


class ControlCycle:
    def __init__(
        self,
        hub: SensorHub,
        controller: ActuatorController,
        strategy: DecisionStrategy,
        policy: FarmPolicy,
        event_store: EventStore,
    ) -> None:
        self._hub = hub
        self._controller = controller
        self._strategy = strategy
        self._policy = policy
        self._events = event_store

    def run_once(self) -> dict[str, Any]:
        # 1. Sense.
        readings = self._hub.read_all()
        for reading in readings:
            self._events.record(Event("reading", reading.to_dict()))

        # 2. Assess against policy.
        deviations = find_deviations(readings, self._policy)
        for dev in deviations:
            self._events.record(Event("deviation", dev.to_dict()))

        # 3. Decide (strategy proposes; it has no authority to act).
        history = self._events.recent(50)
        commands = self._strategy.decide(readings, deviations, history)
        note = None
        if getattr(self._strategy, "wired", True) is False:
            note = f"{self._strategy.name} strategy not yet wired; proposed no commands"
        self._events.record(
            Event(
                "decision",
                {
                    "strategy": self._strategy.name,
                    "commands": [c.to_dict() for c in commands],
                    "note": note,
                },
            )
        )

        # 4. Act (every command through the safety-guarded controller).
        results = [self._controller.execute(cmd) for cmd in commands]

        return {
            "strategy": self._strategy.name,
            "readings": [r.to_dict() for r in readings],
            "deviations": [d.to_dict() for d in deviations],
            "commands": [c.to_dict() for c in commands],
            "results": [r.to_dict() for r in results],
            "note": note,
        }

    def status(self) -> dict[str, Any]:
        return {
            "strategy": self._strategy.name,
            "dry_run": self._controller.dry_run,
            "sensors": self._hub.list_sensors(),
            "actuators": self._controller.states(),
        }
