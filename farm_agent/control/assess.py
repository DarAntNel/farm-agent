"""Turn readings into deviations.

A *deviation* is a reading that has drifted outside its configured target range.
This module is pure: given readings and policy it returns deviations, with no
side effects — easy to reason about and test.
"""

from __future__ import annotations

from farm_agent.config.policy import FarmPolicy
from farm_agent.models import Deviation, Reading


def find_deviations(readings: list[Reading], policy: FarmPolicy) -> list[Deviation]:
    """Return a :class:`Deviation` for every reading outside its target range.

    Readings that failed (``ok=False``), have no value, or have no configured
    target are skipped.
    """
    deviations: list[Deviation] = []
    for reading in readings:
        if not reading.ok or reading.value is None:
            continue
        target = policy.target_for(reading.sensor_id)
        if target is None:
            continue
        low, high = target
        if reading.value < low:
            direction = "low"
        elif reading.value > high:
            direction = "high"
        else:
            continue
        deviations.append(
            Deviation(
                sensor_id=reading.sensor_id,
                metric=reading.name,
                value=reading.value,
                target_low=low,
                target_high=high,
                direction=direction,
            )
        )
    return deviations
