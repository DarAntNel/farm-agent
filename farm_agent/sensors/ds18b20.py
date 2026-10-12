"""DS18B20 temperature sensor (direct 1-Wire).

A DS18B20 digital thermometer wired to the Pi's 1-Wire bus, read directly rather
than through the Arduino.

As with :class:`Ads1115SoilSensor`, the Adafruit library is imported *lazily* so
the package imports without hardware, and a fake device can be injected for
tests/simulation. The device is duck-typed: it only needs a float
``.temperature`` attribute (see :class:`tests.fakes.FakeOneWireDevice`).
"""

from __future__ import annotations

from typing import Any, Optional

from farm_agent.models import Reading
from farm_agent.registry import sensor_registry
from farm_agent.sensors.base import DirectSensor


@sensor_registry.register("ds18b20")
class Ds18b20Sensor(DirectSensor):
    """Temperature in Celsius read from a DS18B20 over 1-Wire."""

    kind = "ds18b20"
    UNIT = "°C"
    #: DS18B20 rated operating range.
    VALID_RANGE = (-55, 125)

    def __init__(
        self,
        sensor_id: str,
        name: str,
        *,
        device: Optional[Any] = None,
        device_id: Optional[str] = None,
        calibration_offset: float = 0.0,
    ) -> None:
        super().__init__(sensor_id, name)
        # An injected device (a fake, or a pre-built real one) wins; otherwise
        # the real device is built lazily on first read.
        self._device = device
        self._device_id = device_id
        self._calibration = calibration_offset

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None, buses: Any = None) -> "Ds18b20Sensor":
        """Build from a wiring-config entry.

        If ``buses`` carries an injected device (keyed by this sensor's id or by
        ``"ds18b20"``) it is used directly, so tests/simulation need no hardware.
        """
        device = None
        if isinstance(buses, dict):
            device = buses.get(cfg["id"]) or buses.get("ds18b20")
        return cls(
            cfg["id"],
            cfg.get("name", cls.__name__),
            device=device,
            device_id=cfg.get("device_id"),
            calibration_offset=float(cfg.get("calibration_offset", 0.0)),
        )

    def _real_device(self) -> Any:
        """Lazily construct a real DS18B20 device object (needs Adafruit)."""
        try:
            from w1thermsensor import W1ThermSensor  # type: ignore
        except ImportError as exc:  # no hardware libs on this machine
            raise RuntimeError(
                "w1thermsensor library not available; inject a device for testing."
            ) from exc
        if self._device_id:
            return W1ThermSensor(sensor_id=self._device_id)
        return W1ThermSensor()

    def read(self) -> Reading:
        try:
            device = self._device
            if device is None:
                device = self._device = self._real_device()
            value = float(device.temperature) + self._calibration
        except Exception as exc:  # hardware/bus failure or missing libs
            return Reading.failure(self.id, self.name, self.UNIT, str(exc))
        low, high = self.VALID_RANGE
        if not low <= value <= high:
            return Reading.failure(
                self.id,
                self.name,
                self.UNIT,
                f"value {value} outside valid range [{low}, {high}]",
            )
        return Reading(self.id, self.name, value, self.UNIT)
