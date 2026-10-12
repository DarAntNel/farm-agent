"""A tiny generic type registry, reused for sensors and actuators.

This is the mechanism that makes the system *extensible*: a concrete sensor or
actuator class registers itself under a string ``type`` key, and the config-
driven factory (see :mod:`farm_agent.config`) looks that key up to build the
object. Adding a new device type is therefore:

    1. write a class,
    2. decorate it with ``@sensor_registry.register("my_type")``,
    3. add one line to the config naming that type and its port.

No other code changes.
"""

from __future__ import annotations

from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    """Maps a string type-key to a class.

    Raises clear errors on duplicate registration and on unknown lookups so
    that a typo in config or a double-import produces an actionable message
    rather than a mysterious ``KeyError``.
    """

    def __init__(self, label: str) -> None:
        self._label = label
        self._types: dict[str, type[T]] = {}

    def register(self, key: str) -> Callable[[type[T]], type[T]]:
        """Decorator: register ``cls`` under ``key``."""

        def decorator(cls: type[T]) -> type[T]:
            if key in self._types and self._types[key] is not cls:
                raise ValueError(
                    f"{self._label} type {key!r} is already registered to "
                    f"{self._types[key].__name__}; cannot re-register to "
                    f"{cls.__name__}."
                )
            self._types[key] = cls
            return cls

        return decorator

    def get(self, key: str) -> type[T]:
        """Return the class registered under ``key`` or raise a clear error."""
        try:
            return self._types[key]
        except KeyError:
            available = ", ".join(sorted(self._types)) or "(none)"
            raise KeyError(
                f"Unknown {self._label} type {key!r}. Available types: {available}."
            ) from None

    def available(self) -> list[str]:
        return sorted(self._types)

    def __contains__(self, key: str) -> bool:
        return key in self._types


# The two shared registries. Concrete classes import these and decorate
# themselves; the package __init__ files import the concrete modules so the
# registration side effects run.
sensor_registry: "Registry" = Registry("sensor")
actuator_registry: "Registry" = Registry("actuator")
