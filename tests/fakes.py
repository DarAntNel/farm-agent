"""Shared test doubles so the whole system is testable without hardware.

These are the fakes every slice's tests build on:

* :class:`FakeSerialTransport` — satisfies the ``FrameSource``/``LineSink``
  protocols; feed it scripted frames or make it raise.
* :class:`FakeClock` — deterministic monotonic time for cooldown/watchdog tests.
* :class:`RecordingActuator` — a minimal :class:`Actuator` that records the
  commands it performs (and can be told to fail).
* :class:`FakeI2CChannel` / :class:`FakeOneWireDevice` — stand-ins for direct
  sensor hardware.
"""

from __future__ import annotations

from typing import Any, Optional

from farm_agent.actuators.base import Actuator
from farm_agent.models import Command


class FakeClock:
    """A controllable monotonic clock."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:  # usable anywhere `clock()` is expected
        return self._t

    def time(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


class FakeSerialTransport:
    """Scripted stand-in for :class:`farm_agent.transport.SerialTransport`."""

    def __init__(
        self,
        frames: Optional[list[dict[str, Any]]] = None,
        *,
        raises: Optional[Exception] = None,
    ) -> None:
        # If one frame is given it is returned every time; a list is consumed
        # then the last frame repeats.
        self._frames = list(frames or [{}])
        self._idx = 0
        self._raises = raises
        self.written: list[str] = []

    def current_frame(self, max_age: float = 1.0) -> dict[str, Any]:
        if self._raises is not None:
            raise self._raises
        frame = self._frames[min(self._idx, len(self._frames) - 1)]
        if self._idx < len(self._frames) - 1:
            self._idx += 1
        return frame

    def write_line(self, line: str) -> None:
        if self._raises is not None:
            raise self._raises
        self.written.append(line)


class RecordingActuator(Actuator):
    """A minimal actuator that records performed commands."""

    kind = "recording"

    def __init__(self, actuator_id: str, name: str = "recording", *, fail: bool = False) -> None:
        super().__init__(actuator_id, name)
        self.performed: list[Command] = []
        self._fail = fail

    def _perform(self, command: Command) -> None:
        if self._fail:
            raise RuntimeError("simulated hardware failure")
        self.performed.append(command)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None) -> "RecordingActuator":
        return cls(cfg["id"], cfg.get("name", "recording"))


class FakeI2CChannel:
    """Stand-in for a single ADS1x15 analog channel."""

    def __init__(self, value: int = 500) -> None:
        self.value = value


class FakeOneWireDevice:
    """Stand-in for a DS18B20 1-Wire device."""

    def __init__(self, temperature: float = 21.0) -> None:
        self.temperature = temperature
