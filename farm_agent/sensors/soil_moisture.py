"""Soil-moisture sensor (serial-backed).

The soil probe is wired to the Arduino, so its value arrives as the ``soil_raw``
field of the shared JSON frame. All the real work (fetching the frame, extracting
the field, validating the range, applying the calibration offset) lives in
:class:`~farm_agent.sensors.base.SerialSensor`; this class only declares *which*
field it owns and what counts as a valid value.
"""

from __future__ import annotations

from farm_agent.registry import sensor_registry
from farm_agent.sensors.base import SerialSensor


@sensor_registry.register("soil_moisture")
class SoilMoistureSensor(SerialSensor):
    """Capacitive/resistive soil-moisture probe read via the Arduino."""

    kind = "soil_moisture"
    FIELD = "soil_raw"
    UNIT = "raw"
    #: 10-bit ADC on the Arduino, so the raw reading is 0..1023.
    VALID_RANGE = (0, 1023)
