"""ADS1115 soil-moisture sensor (direct I2C).

Some soil probes are wired to an ADS1115 analog-to-digital converter on the Pi's
I2C bus rather than to the Arduino. This sensor reads one ADS1115 channel
directly.

The Adafruit hardware libraries are imported *lazily* (inside
:meth:`_real_channel`) so the package still imports on a machine without them, and
a fake channel can be injected for tests/simulation. Any injected or constructed
channel is duck-typed: it only needs an integer ``.value`` attribute (see
:class:`tests.fakes.FakeI2CChannel`).
"""

from __future__ import annotations

from typing import Any, Optional

from farm_agent.models import Reading
from farm_agent.registry import sensor_registry
from farm_agent.sensors.base import DirectSensor


@sensor_registry.register("ads1115_soil")
class Ads1115SoilSensor(DirectSensor):
    """Soil-moisture probe read from an ADS1115 analog channel over I2C."""

    kind = "ads1115_soil"
    UNIT = "raw"
    #: The ADS1115 is a 16-bit, signed ADC; single-ended readings are 0..32767.
    VALID_RANGE = (0, 32767)

    def __init__(
        self,
        sensor_id: str,
        name: str,
        *,
        channel: Optional[Any] = None,
        address: int = 0x48,
        channel_index: int = 0,
        calibration_offset: float = 0.0,
    ) -> None:
        super().__init__(sensor_id, name)
        # An injected channel (a fake, or a pre-built real one) wins; otherwise
        # the real channel is built lazily on first read.
        self._channel = channel
        self._address = address
        self._channel_index = channel_index
        self._calibration = calibration_offset

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None, buses: Any = None) -> "Ads1115SoilSensor":
        """Build from a wiring-config entry.

        If ``buses`` carries an injected channel (keyed by this sensor's id or by
        ``"ads1115"``) it is used directly, so tests/simulation need no hardware.
        """
        channel = None
        if isinstance(buses, dict):
            channel = buses.get(cfg["id"]) or buses.get("ads1115")
        address = cfg.get("address", 0x48)
        # Accept both an int and a hex string like "0x48" from JSON config.
        address = int(address, 0) if isinstance(address, str) else int(address)
        return cls(
            cfg["id"],
            cfg.get("name", cls.__name__),
            channel=channel,
            address=address,
            channel_index=int(cfg.get("channel", 0)),
            calibration_offset=float(cfg.get("calibration_offset", 0.0)),
        )

    def _real_channel(self) -> Any:
        """Lazily construct a real ADS1115 analog channel (needs Adafruit)."""
        try:
            import board  # type: ignore
            import busio  # type: ignore
            import adafruit_ads1x15.ads1115 as ADS  # type: ignore
            from adafruit_ads1x15.analog_in import AnalogIn  # type: ignore
        except ImportError as exc:  # no hardware libs on this machine
            raise RuntimeError(
                "Adafruit ADS1x15 libraries not available; inject a channel for testing."
            ) from exc
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c, address=self._address)
        return AnalogIn(ads, getattr(ADS, f"P{self._channel_index}"))

    def read(self) -> Reading:
        try:
            channel = self._channel
            if channel is None:
                channel = self._channel = self._real_channel()
            value = float(channel.value) + self._calibration
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
