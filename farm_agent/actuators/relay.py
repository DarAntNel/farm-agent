"""A GPIO relay actuator (e.g. the water pump) on the Raspberry Pi.

A relay is the simplest actuator: a single pin is driven high to energise the
relay (device on) and low to release it (device off). The GPIO library import is
**lazy** so this module imports fine on a dev machine with no hardware, and the
backend that actually toggles the pin is **injectable** so tests run without any
GPIO at all. As with every actuator, no safety policy lives here.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from farm_agent.actuators.base import Actuator
from farm_agent.models import Command
from farm_agent.registry import actuator_registry

# A backend is any callable that sets ``pin`` to on/off: ``backend(pin, value)``.
Backend = Callable[[int, bool], None]


def _make_gpio_backend() -> Backend:
    """Build a real GPIO-backed toggle, importing the hardware lib lazily.

    Called only when no backend was injected and a command is actually
    performed, so merely importing this module never requires ``RPi.GPIO``.
    """
    try:
        import RPi.GPIO as GPIO  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only on hardware
        raise RuntimeError(
            "RPi.GPIO is not available; inject a backend or run in simulation."
        ) from exc

    GPIO.setmode(GPIO.BCM)

    def _backend(pin: int, value: bool) -> None:  # pragma: no cover - hardware
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH if value else GPIO.LOW)

    return _backend


@actuator_registry.register("relay")
class RelayActuator(Actuator):
    """Drives a single GPIO relay pin high (on) or low (off)."""

    kind = "relay"

    def __init__(
        self,
        actuator_id: str,
        name: str,
        pin: int,
        *,
        backend: Optional[Backend] = None,
    ) -> None:
        super().__init__(actuator_id, name)
        self._pin = pin
        # Injected for tests; otherwise a real GPIO backend is created lazily on
        # first use so construction never needs hardware.
        self._backend = backend

    def _resolve_backend(self) -> Backend:
        if self._backend is None:
            self._backend = _make_gpio_backend()
        return self._backend

    def _perform(self, command: Command) -> None:
        # "off" drives the pin low; anything else ("on"/"set") drives it high.
        value = command.action != "off"
        self._resolve_backend()(self._pin, value)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None) -> "RelayActuator":
        return cls(cfg["id"], cfg.get("name", cfg["id"]), cfg["pin"])
