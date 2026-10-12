"""Simulation doubles for running the whole system without hardware.

``SIMULATE=true`` swaps the real serial link and hardware buses for these, so
the control loop, safety guard and API can all be exercised on any machine.
They are intentionally simple: plausible mid-range values, no randomness, so
behaviour is reproducible.
"""

from __future__ import annotations

from typing import Any


class SimulatedTransport:
    """Stands in for :class:`~farm_agent.transport.SerialTransport`.

    Returns a frame containing plausible values for the fields serial sensors
    ask for, and accepts (records) command lines.
    """

    #: Default values for the Arduino's known JSON fields.
    DEFAULTS: dict[str, Any] = {"soil_raw": 300, "temperature_c": 22.0}

    def __init__(self, frame: dict[str, Any] | None = None) -> None:
        self._frame = dict(self.DEFAULTS)
        if frame:
            self._frame.update(frame)
        self.written: list[str] = []

    def current_frame(self, max_age: float = 1.0) -> dict[str, Any]:
        return self._frame

    def write_line(self, line: str) -> None:
        self.written.append(line)


class _SimChannel:
    def __init__(self, value: int = 300) -> None:
        self.value = value


class _SimOneWire:
    def __init__(self, temperature: float = 22.0) -> None:
        self.temperature = temperature


class SimBuses(dict):
    """A ``buses`` object for direct sensors in simulation.

    Direct sensors inject hardware only when ``buses`` is a ``dict`` and
    ``buses.get(<id-or-type-key>)`` returns a device, so this subclasses ``dict``
    and overrides :meth:`get` to hand back a fresh simulated device of the right
    kind. Keys are matched by the sensor's type token (``"ads1115"`` /
    ``"ds18b20"``) or by common id naming (``*soil*`` / ``*temp*``); unknown keys
    return the default so the two-step lookup in each sensor's ``from_config``
    works.
    """

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        if key == "ds18b20" or "temp" in key:
            return _SimOneWire()
        if key == "ads1115" or "soil" in key or "ads" in key:
            return _SimChannel()
        return default
