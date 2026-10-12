"""Actuator package.

Importing this package imports every concrete actuator module so their
``@actuator_registry.register(...)`` side effects run and the config-driven
factory can find them by type key.
"""

from farm_agent.actuators import relay, serial_actuator, fake  # noqa: F401
