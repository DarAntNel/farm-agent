"""The deterministic safety chokepoint.

The decision layer (local rules now, an LLM later) only ever *proposes*
commands. The :class:`SafetyGuard` *disposes*: it clamps an ``on`` command's
duration to the configured maximum and rejects anything that would violate a
cooldown, a daily activation cap, or a mutual-exclusion rule. Nothing reaches
hardware without passing through here, so this layer is pure and deterministic:
all time comes from an injected clock, and it performs no I/O. When in doubt it
rejects; ``off`` is always safe and never rate-limited.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable, Mapping

from farm_agent.actuators.base import Actuator
from farm_agent.models import ActuatorResult, Command

if TYPE_CHECKING:  # avoid a circular import (policy -> safety.limits -> safety pkg)
    from farm_agent.config.policy import FarmPolicy

#: Seconds in a rolling 24-hour window (used for the daily activation cap).
_ONE_DAY_S = 24 * 60 * 60


class SafetyGuard:
    """Validate/clamp/reject every proposed command against policy limits.

    The guard keeps its own per-actuator history of activation start times so it
    can enforce cooldowns and the rolling-24h cap. The controller is responsible
    for calling :meth:`record_activation` after a successful ``on``.
    """

    def __init__(self, policy: "FarmPolicy", *, clock: Callable[[], float] = time.monotonic) -> None:
        self._policy = policy
        self._clock = clock
        # actuator_id -> list of activation start times (seconds, from clock()).
        self._activations: dict[str, list[float]] = {}

    def review(self, command: Command, actuators: Mapping[str, Actuator]) -> ActuatorResult:
        """Decide whether ``command`` may proceed, possibly clamped.

        * ``off`` is always allowed (fail-safe) and is never rate-limited.
        * ``on`` has its ``duration_s`` clamped down to ``max_runtime_s`` (and a
          missing duration is filled in with ``max_runtime_s``), then is
          rejected if the actuator is still in cooldown, has hit its daily cap,
          or any mutually-exclusive actuator is currently on.
        * Any other action is passed through unchanged (still subject to no
          clamping/limits here — those apply to activations).
        """
        actuator_id = command.actuator_id

        # Fail-safe: turning something off is always permitted.
        if command.action == "off":
            return ActuatorResult.ok(actuator_id, command)

        if command.action != "on":
            return ActuatorResult.ok(actuator_id, command)

        limits = self._policy.limits_for(actuator_id)

        # 1) Clamp the requested duration down to the configured maximum.
        duration = command.duration_s
        if duration is None or duration > limits.max_runtime_s:
            duration = limits.max_runtime_s
        clamped = command.replace(duration_s=duration)

        now = self._clock()
        history = self._activations.get(actuator_id, [])

        # 2) Reject if still inside the cooldown window.
        if history:
            last_start = history[-1]
            if now - last_start < limits.cooldown_s:
                return ActuatorResult.rejected(
                    actuator_id,
                    f"in cooldown: {limits.cooldown_s - (now - last_start):.0f}s remaining",
                )

        # 3) Reject if the rolling-24h activation cap is already met.
        recent = [t for t in history if now - t < _ONE_DAY_S]
        if len(recent) >= limits.max_activations_per_day:
            return ActuatorResult.rejected(
                actuator_id,
                f"daily activation cap reached ({limits.max_activations_per_day})",
            )

        # 4) Reject if any mutually-exclusive actuator is currently on.
        for other_id in limits.mutually_exclusive_with:
            other = actuators.get(other_id)
            if other is not None and other.is_on:
                return ActuatorResult.rejected(
                    actuator_id,
                    f"mutually exclusive with active actuator {other_id!r}",
                )

        return ActuatorResult.ok(actuator_id, clamped)

    def record_activation(self, actuator_id: str) -> None:
        """Record that ``actuator_id`` just started an activation.

        Called by the controller *after* a successful ``on`` so the next review
        can enforce cooldown and the rolling-24h count. Uses the injected clock
        so tests stay deterministic.
        """
        self._activations.setdefault(actuator_id, []).append(self._clock())
