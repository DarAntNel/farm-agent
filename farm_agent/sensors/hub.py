"""SensorHub — the one place the rest of the system asks for readings.

The hub holds the live set of :class:`~farm_agent.sensors.base.Sensor` objects and
offers batch and single reads. It depends only on the ``Sensor`` interface
(dependency inversion): it neither knows nor cares whether a sensor is serial- or
hardware-backed.

Reading the Arduino's serial port only once per cycle is *not* the hub's job — it
falls out of :class:`~farm_agent.transport.SerialTransport`'s frame cache, which
every serial sensor shares. The hub simply calls ``read()`` on each sensor.
"""

from __future__ import annotations

from typing import Any

from farm_agent.models import Reading
from farm_agent.sensors.base import Sensor


class SensorHub:
    """Aggregates sensors and exposes read-all / read-one / list operations."""

    def __init__(self, sensors: list[Sensor]) -> None:
        self._sensors = list(sensors)
        # Index by id for O(1) single-sensor lookup.
        self._by_id: dict[str, Sensor] = {s.id: s for s in self._sensors}

    def read_all(self) -> list[Reading]:
        """Read every sensor once. A broken sensor yields an ``ok=False``
        :class:`Reading` rather than raising, so one failure never breaks the
        batch."""
        return [sensor.read() for sensor in self._sensors]

    def read_one(self, sensor_id: str) -> Reading:
        """Read a single sensor by id.

        Raises :class:`KeyError` for an unknown id (the web layer maps this to a
        404).
        """
        try:
            sensor = self._by_id[sensor_id]
        except KeyError:
            raise KeyError(f"Unknown sensor id {sensor_id!r}.") from None
        return sensor.read()

    def list_sensors(self) -> list[dict[str, Any]]:
        """Return a static description of each sensor (no reads performed)."""
        return [sensor.describe() for sensor in self._sensors]
