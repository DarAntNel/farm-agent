"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import pytest

from tests.fakes import (
    FakeClock,
    FakeSerialTransport,
    RecordingActuator,
)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def transport() -> FakeSerialTransport:
    """A transport that yields one well-formed frame."""
    return FakeSerialTransport([{"soil_raw": 512, "temperature_c": 21.5}])


@pytest.fixture
def recording_actuator() -> RecordingActuator:
    return RecordingActuator("pump_1", "Water pump")
