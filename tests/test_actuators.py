"""Tests for the concrete actuators (relay, serial, fake) and their registry.

Everything here runs with NO hardware: the relay gets an injected backend and the
serial actuator gets a ``FakeSerialTransport``. These tests exercise the contract
the rest of the system relies on — ``apply``/``_perform``, on/off state tracking,
``safe_off``, the hardware-error path, ``state()`` shape, registry lookups, and
``from_config`` for each type.
"""

from __future__ import annotations

import pytest

from farm_agent.actuators.fake import FakeActuator
from farm_agent.actuators.relay import RelayActuator
from farm_agent.actuators.serial_actuator import SerialActuator
from farm_agent.models import Command
from farm_agent.registry import actuator_registry
from tests.fakes import FakeSerialTransport


# --------------------------------------------------------------------------- #
# A tiny injectable GPIO backend double.
# --------------------------------------------------------------------------- #
class FakeBackend:
    """Records every (pin, value) toggle; can be told to raise."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[int, bool]] = []
        self._fail = fail

    def __call__(self, pin: int, value: bool) -> None:
        if self._fail:
            raise RuntimeError("simulated GPIO failure")
        self.calls.append((pin, value))


# --------------------------------------------------------------------------- #
# RelayActuator
# --------------------------------------------------------------------------- #
def test_relay_apply_on_sets_pin_high_and_is_on() -> None:
    backend = FakeBackend()
    relay = RelayActuator("pump_1", "Water pump", pin=17, backend=backend)

    result = relay.apply(Command(actuator_id="pump_1", action="on"))

    assert result.accepted is True
    assert relay.is_on is True
    assert backend.calls == [(17, True)]


def test_relay_apply_off_sets_pin_low_and_is_off() -> None:
    backend = FakeBackend()
    relay = RelayActuator("pump_1", "Water pump", pin=17, backend=backend)
    relay.apply(Command(actuator_id="pump_1", action="on"))

    result = relay.apply(Command(actuator_id="pump_1", action="off"))

    assert result.accepted is True
    assert relay.is_on is False
    assert backend.calls == [(17, True), (17, False)]


def test_relay_safe_off_forces_off() -> None:
    backend = FakeBackend()
    relay = RelayActuator("pump_1", "Water pump", pin=17, backend=backend)
    relay.apply(Command(actuator_id="pump_1", action="on"))

    result = relay.safe_off()

    assert result.accepted is True
    assert relay.is_on is False
    assert backend.calls[-1] == (17, False)


def test_relay_hardware_error_is_rejected_and_state_unchanged() -> None:
    backend = FakeBackend(fail=True)
    relay = RelayActuator("pump_1", "Water pump", pin=17, backend=backend)

    result = relay.apply(Command(actuator_id="pump_1", action="on"))

    assert result.accepted is False
    assert result.reason is not None
    assert "hardware error" in result.reason
    assert relay.is_on is False


def test_relay_state_shape() -> None:
    relay = RelayActuator("pump_1", "Water pump", pin=17, backend=FakeBackend())

    state = relay.state()

    assert state["id"] == "pump_1"
    assert state["name"] == "Water pump"
    assert state["kind"] == "relay"
    assert state["is_on"] is False
    assert state["since"] is None


def test_relay_from_config() -> None:
    relay = RelayActuator.from_config({"id": "pump_1", "name": "Water pump", "pin": 23})

    assert isinstance(relay, RelayActuator)
    assert relay.id == "pump_1"
    assert relay.name == "Water pump"
    assert relay._pin == 23


def test_relay_from_config_defaults_name_to_id() -> None:
    relay = RelayActuator.from_config({"id": "pump_1", "pin": 23})

    assert relay.name == "pump_1"


# --------------------------------------------------------------------------- #
# SerialActuator
# --------------------------------------------------------------------------- #
def test_serial_actuator_writes_expected_line_on() -> None:
    transport = FakeSerialTransport()
    act = SerialActuator("pump_1", "Water pump", transport, command_prefix="pump")

    result = act.apply(Command(actuator_id="pump_1", action="on", duration_s=180))

    assert result.accepted is True
    assert transport.written == ["pump on 180"]
    assert act.is_on is True


def test_serial_actuator_writes_line_without_duration() -> None:
    transport = FakeSerialTransport()
    act = SerialActuator("pump_1", "Water pump", transport, command_prefix="pump")

    act.apply(Command(actuator_id="pump_1", action="off"))

    assert transport.written == ["pump off"]
    assert act.is_on is False


def test_serial_actuator_hardware_error_is_rejected() -> None:
    transport = FakeSerialTransport(raises=RuntimeError("serial down"))
    act = SerialActuator("pump_1", "Water pump", transport, command_prefix="pump")

    result = act.apply(Command(actuator_id="pump_1", action="on"))

    assert result.accepted is False
    assert "hardware error" in result.reason
    assert act.is_on is False


def test_serial_actuator_from_config_requires_transport() -> None:
    with pytest.raises(ValueError):
        SerialActuator.from_config({"id": "pump_1"})


def test_serial_actuator_from_config_builds_with_transport() -> None:
    transport = FakeSerialTransport()
    act = SerialActuator.from_config(
        {"id": "pump_1", "name": "Water pump", "command": "P1"},
        transport=transport,
    )

    assert isinstance(act, SerialActuator)
    assert act.id == "pump_1"
    assert act.name == "Water pump"
    act.apply(Command(actuator_id="pump_1", action="on"))
    assert transport.written == ["P1 on"]


def test_serial_actuator_from_config_command_defaults_to_id() -> None:
    transport = FakeSerialTransport()
    act = SerialActuator.from_config({"id": "pump_1"}, transport=transport)

    act.apply(Command(actuator_id="pump_1", action="on"))
    assert transport.written == ["pump_1 on"]


# --------------------------------------------------------------------------- #
# FakeActuator
# --------------------------------------------------------------------------- #
def test_fake_actuator_records_commands() -> None:
    act = FakeActuator("led_1", "Status LED")
    cmd_on = Command(actuator_id="led_1", action="on")
    cmd_off = Command(actuator_id="led_1", action="off")

    act.apply(cmd_on)
    act.apply(cmd_off)

    assert act.performed == [cmd_on, cmd_off]
    assert act.is_on is False


def test_fake_actuator_state_shape() -> None:
    act = FakeActuator("led_1", "Status LED")
    act.apply(Command(actuator_id="led_1", action="on"))

    state = act.state()

    assert state["kind"] == "fake"
    assert state["id"] == "led_1"
    assert state["is_on"] is True
    assert state["since"] is not None


def test_fake_actuator_from_config() -> None:
    act = FakeActuator.from_config({"id": "led_1", "name": "Status LED"})

    assert isinstance(act, FakeActuator)
    assert act.id == "led_1"
    assert act.name == "Status LED"


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "key, expected",
    [
        ("relay", RelayActuator),
        ("serial_actuator", SerialActuator),
        ("fake", FakeActuator),
    ],
)
def test_registry_lookup(key: str, expected: type) -> None:
    assert actuator_registry.get(key) is expected


def test_registry_unknown_type_raises() -> None:
    with pytest.raises(KeyError):
        actuator_registry.get("nonexistent_actuator")
