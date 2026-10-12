"""Per-actuator safety limits.

These are deterministic constraints the :class:`~farm_agent.safety.guard.SafetyGuard`
enforces on every command, independent of whoever proposed it (local rules or,
later, an LLM). They come from the *policy* config (see
:mod:`farm_agent.config.policy`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SafetyLimits:
    """Limits for a single actuator.

    * ``max_runtime_s`` — an ``on`` command's duration is clamped to this.
    * ``cooldown_s`` — minimum seconds between the end of one activation and the
      start of the next.
    * ``max_activations_per_day`` — hard cap on activations in a rolling 24h.
    * ``mutually_exclusive_with`` — ids of actuators that must not be on at the
      same time as this one.
    """

    max_runtime_s: float = 300.0
    cooldown_s: float = 0.0
    max_activations_per_day: int = 1_000_000
    mutually_exclusive_with: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyLimits":
        return cls(
            max_runtime_s=float(data.get("max_runtime_s", 300.0)),
            cooldown_s=float(data.get("cooldown_s", 0.0)),
            max_activations_per_day=int(data.get("max_activations_per_day", 1_000_000)),
            mutually_exclusive_with=list(data.get("mutually_exclusive_with", [])),
        )


#: Used when policy config names no limits for an actuator. Deliberately
#: conservative on runtime, permissive on counts.
DEFAULT_LIMITS = SafetyLimits()
