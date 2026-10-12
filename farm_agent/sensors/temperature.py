"""Temperature sensor (serial-backed).

The temperature value arrives as the ``temperature_c`` field of the Arduino's
shared JSON frame. Like :class:`SoilMoistureSensor`, this class only declares its
field, unit and valid range; :class:`~farm_agent.sensors.base.SerialSensor` does
the rest.
"""

from __future__ import annotations

from farm_agent.registry import sensor_registry
from farm_agent.sensors.base import SerialSensor


@sensor_registry.register("temperature")
class TemperatureSensor(SerialSensor):
    """Ambient/soil temperature in Celsius, read via the Arduino."""

    kind = "temperature"
    FIELD = "temperature_c"
    UNIT = "°C"
    #: Matches the DS18B20 family's rated operating range.
    VALID_RANGE = (-55, 125)
