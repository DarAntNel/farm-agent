"""Sensor interfaces.

Everything the rest of the system sees is a :class:`Sensor` with a single
``read() -> Reading`` method (Liskov: a serial sensor and a direct-hardware
sensor are interchangeable). Two abstract subclasses capture the two ways a
reading is obtained:

* :class:`SerialSensor` — the value arrives inside the Arduino's JSON frame.
* :class:`DirectSensor`  — the value is read directly from Pi hardware.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from farm_agent.models import Reading
from farm_agent.transport import FrameSource


class Sensor(ABC):
    """The uniform interface for every sensor."""

    #: short machine-readable category, e.g. "soil_moisture"
    kind: str = "sensor"

    def __init__(self, sensor_id: str, name: str) -> None:
        self._id = sensor_id
        self._name = name

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    def read(self) -> Reading:
        """Produce a :class:`Reading`. Must never raise for an expected
        failure — return ``Reading.failure(...)`` instead."""
        raise NotImplementedError

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None, buses: Any = None) -> "Sensor":
        """Build an instance from one wiring-config entry.

        The config-driven factory calls this. Subclasses that need hardware
        buses (direct sensors) or the serial transport read what they need from
        the keyword arguments.
        """
        raise NotImplementedError(
            f"{cls.__name__} must implement from_config()."
        )

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "kind": self.kind}


class SerialSensor(Sensor):
    """A sensor whose value is one field of the Arduino's JSON frame.

    Concrete subclasses typically only set the class attributes ``kind``,
    ``FIELD``, ``UNIT`` and ``VALID_RANGE``; the shared :meth:`read` handles
    fetching the frame, extracting the field, validating the range and applying
    a calibration offset.
    """

    FIELD: str = ""
    UNIT: str = ""
    VALID_RANGE: tuple[float, float] = (float("-inf"), float("inf"))

    def __init__(
        self,
        sensor_id: str,
        name: str,
        transport: FrameSource,
        *,
        field: Optional[str] = None,
        unit: Optional[str] = None,
        valid_range: Optional[tuple[float, float]] = None,
        calibration_offset: float = 0.0,
        max_age: float = 1.0,
    ) -> None:
        super().__init__(sensor_id, name)
        self._transport = transport
        self._field = field or self.FIELD
        self._unit = unit if unit is not None else self.UNIT
        self._range = valid_range or self.VALID_RANGE
        self._calibration = calibration_offset
        self._max_age = max_age

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None, buses: Any = None) -> "Sensor":
        if transport is None:
            raise ValueError(f"{cls.__name__} requires a serial transport.")
        return cls(
            cfg["id"],
            cfg.get("name", cls.__name__),
            transport,
            field=cfg.get("field"),
            unit=cfg.get("unit"),
            valid_range=tuple(cfg["valid_range"]) if "valid_range" in cfg else None,
            calibration_offset=float(cfg.get("calibration_offset", 0.0)),
            max_age=float(cfg.get("max_age", 1.0)),
        )

    def read(self) -> Reading:
        try:
            frame = self._transport.current_frame(max_age=self._max_age)
        except Exception as exc:  # transport down / timeout
            return Reading.failure(self.id, self.name, self._unit, str(exc))
        return self.extract(frame)

    def extract(self, frame: dict[str, Any]) -> Reading:
        """Pull this sensor's field out of ``frame`` and validate it."""
        if self._field not in frame:
            return Reading.failure(
                self.id, self.name, self._unit, f"field {self._field!r} missing from frame"
            )
        try:
            value = float(frame[self._field]) + self._calibration
        except (TypeError, ValueError):
            return Reading.failure(
                self.id, self.name, self._unit, f"field {self._field!r} is not numeric"
            )
        low, high = self._range
        if not low <= value <= high:
            return Reading.failure(
                self.id,
                self.name,
                self._unit,
                f"value {value} outside valid range [{low}, {high}]",
            )
        return Reading(self.id, self.name, value, self._unit)


class DirectSensor(Sensor):
    """A sensor that reads Pi hardware directly (I2C, 1-Wire, GPIO).

    Hardware libraries (Adafruit Blinka etc.) must be imported lazily *inside*
    the concrete subclass so the package still imports on a machine without
    them. In simulation/tests a fake bus is injected instead.
    """

    @abstractmethod
    def read(self) -> Reading:
        raise NotImplementedError
