"""Immutable value objects shared across the whole framework.

These are the *contracts* every other module speaks in. Keeping them small,
immutable, and dependency-free means sensors, actuators, the safety guard, the
decision layer, and the web layer can all be understood and tested in terms of
the same handful of records.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal, Optional


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Centralised so every timestamp in the system is produced the same way and
    so tests can monkeypatch a single function if they need deterministic time.
    """
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Sensing
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Reading:
    """One measurement produced by a :class:`~farm_agent.sensors.base.Sensor`.

    A *failed* read is still a ``Reading`` (with ``ok=False`` and an ``error``
    message) so that one broken sensor never crashes a batch read.
    """

    sensor_id: str
    name: str
    value: Optional[float]
    unit: str
    timestamp: str = field(default_factory=utc_now_iso)
    ok: bool = True
    error: Optional[str] = None

    @classmethod
    def failure(cls, sensor_id: str, name: str, unit: str, error: str) -> "Reading":
        """Convenience constructor for a failed read."""
        return cls(
            sensor_id=sensor_id,
            name=name,
            value=None,
            unit=unit,
            ok=False,
            error=error,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Actuation
# --------------------------------------------------------------------------- #
ActuatorAction = Literal["on", "off", "set"]
CommandSource = Literal["local_rules", "llm", "manual", "watchdog", "system"]


@dataclass(frozen=True)
class Command:
    """A requested actuator action.

    A command is only ever a *request*. It must pass the
    :class:`~farm_agent.safety.guard.SafetyGuard` before it can reach hardware,
    where it may be clamped (e.g. duration capped) or rejected outright.
    """

    actuator_id: str
    action: ActuatorAction
    duration_s: Optional[float] = None
    params: dict[str, Any] = field(default_factory=dict)
    source: CommandSource = "system"
    timestamp: str = field(default_factory=utc_now_iso)

    def replace(self, **changes: Any) -> "Command":
        """Return a copy with some fields changed (used by the guard to clamp)."""
        from dataclasses import replace as _replace

        return _replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActuatorResult:
    """The outcome of trying to apply a :class:`Command`."""

    actuator_id: str
    accepted: bool
    applied: Optional[Command] = None
    reason: Optional[str] = None
    timestamp: str = field(default_factory=utc_now_iso)

    @classmethod
    def rejected(cls, actuator_id: str, reason: str) -> "ActuatorResult":
        return cls(actuator_id=actuator_id, accepted=False, applied=None, reason=reason)

    @classmethod
    def ok(cls, actuator_id: str, applied: Command, reason: Optional[str] = None) -> "ActuatorResult":
        return cls(actuator_id=actuator_id, accepted=True, applied=applied, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.applied is not None:
            data["applied"] = self.applied.to_dict()
        return data


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #
Direction = Literal["low", "high"]


@dataclass(frozen=True)
class Deviation:
    """A reading that has drifted outside its configured target range."""

    sensor_id: str
    metric: str
    value: float
    target_low: float
    target_high: float
    direction: Direction

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
EventType = Literal["reading", "deviation", "decision", "actuation"]


@dataclass(frozen=True)
class Event:
    """An append-only audit record.

    Everything the system observes and does is recorded as an ``Event`` so the
    history can answer "why did the pump run at 3am?" and later feed the LLM
    decision agent as context ("previous events").
    """

    type: EventType
    payload: dict[str, Any]
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
