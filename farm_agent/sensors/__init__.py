"""Sensor package.

Importing this package pulls in every concrete sensor module so that each one's
``@sensor_registry.register(...)`` side effect runs and the config-driven factory
can find it by type key. :class:`SensorHub` is re-exported as the package's public
entry point.
"""

from __future__ import annotations

from farm_agent.sensors.hub import SensorHub

# Import each concrete module for its registration side effect. The noqa marks
# them as intentionally imported-for-effect (not unused).
from farm_agent.sensors import (  # noqa: F401
    ads1115_soil,
    ds18b20,
    soil_moisture,
    temperature,
)

__all__ = ["SensorHub"]
