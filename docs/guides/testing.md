# Testing

How to run the test suite, and how to write tests for a sensor (or any other
device) you add — all **without any hardware**. The whole suite uses the same
fakes that simulation uses, so it runs on a laptop or in CI in well under a
second.

> **The golden rule:** every sensor and actuator is built to accept its hardware
> dependency through the constructor (dependency injection). In tests you pass a
> *fake* instead of real hardware. You never need an Arduino, a Pi, or a wired
> sensor to test logic.

---

## Part 1 — Running the tests

`pyproject.toml` already points pytest at the `tests/` directory, so from the
repo root:

```powershell
# Windows (project venv)
./.venv/Scripts/python.exe -m pytest
```

```bash
# macOS / Linux (or with the venv activated)
python -m pytest
```

Useful variations:

```bash
python -m pytest -v                    # one line per test
python -m pytest tests/test_sensors.py # just the sensor tests
python -m pytest -k "guard or watchdog"# only tests matching the expression
python -m pytest -x                     # stop at the first failure
```

You should see every test pass (currently **95 passed**). If pytest reports
"command not found", you have not installed the dependencies yet — see
[getting-started.md](getting-started.md).

---

## Part 2 — The test toolkit

All shared test doubles live in [`tests/fakes.py`](../../tests/fakes.py) and are
exposed as pytest fixtures in [`tests/conftest.py`](../../tests/conftest.py).

| Fake | Stands in for | Key behaviour |
|------|---------------|---------------|
| `FakeSerialTransport` | `SerialTransport` | Give it scripted frames: `FakeSerialTransport([{"soil_raw": 512}])`. Its `current_frame()` returns them; `write_line()` records to `.written`. Pass `raises=...` to simulate the link being down. |
| `FakeClock` | `time.monotonic` | A controllable clock: call `clock()` for "now", `clock.advance(600)` to jump forward. Used for cooldown / watchdog tests. |
| `RecordingActuator` | a real actuator | Records performed commands in `.performed`; construct with `fail=True` to simulate a hardware error. |
| `FakeI2CChannel` / `FakeOneWireDevice` | ADS1115 channel / DS18B20 probe | Carry a `.value` / `.temperature` you set directly. |

Ready-made fixtures (from `conftest.py`): `clock`, `transport` (one good frame
with `soil_raw=512`, `temperature_c=21.5`), and `recording_actuator`.

---

## Part 3 — Testing a new serial sensor

Say you added a `HumiditySensor(SerialSensor)` that reads the JSON field
`humidity_pct`, valid `0..100`, unit `%` (see
[adding-a-sensor.md](adding-a-sensor.md)). A good test file
`tests/test_humidity.py` covers the four cases every serial sensor should:

```python
from farm_agent.sensors.humidity import HumiditySensor
from tests.fakes import FakeSerialTransport


def make(frame, **kw):
    transport = FakeSerialTransport([frame])
    return HumiditySensor.from_config({"id": "hum_1", "name": "Humidity"},
                                      transport=transport, **kw)


def test_valid_reading():
    reading = make({"humidity_pct": 55}).read()
    assert reading.ok is True
    assert reading.value == 55
    assert reading.unit == "%"


def test_out_of_range_is_not_ok():
    reading = make({"humidity_pct": 150}).read()
    assert reading.ok is False
    assert "range" in reading.error


def test_missing_field_is_not_ok():
    reading = make({"soil_raw": 500}).read()  # no humidity_pct
    assert reading.ok is False
    assert "missing" in reading.error


def test_transport_down_is_not_ok():
    import pytest
    transport = FakeSerialTransport(raises=TimeoutError("no data"))
    sensor = HumiditySensor.from_config({"id": "hum_1"}, transport=transport)
    reading = sensor.read()
    assert reading.ok is False
```

Notice the pattern: a sensor **never raises** for an expected failure — it
returns a `Reading` with `ok=False` and an `error`. Your tests assert on that,
not on exceptions.

Also add it to the registry test expectation if you keep one:

```python
from farm_agent.registry import sensor_registry
import farm_agent.sensors  # triggers registration
assert "humidity" in sensor_registry.available()
```

---

## Part 4 — Testing a new direct (hardware) sensor

Direct sensors (I2C/1-Wire) take an **injected device** so no bus is touched:

```python
from farm_agent.sensors.ads1115_soil import Ads1115SoilSensor
from tests.fakes import FakeI2CChannel


def test_direct_sensor_uses_injected_channel():
    sensor = Ads1115SoilSensor.from_config(
        {"id": "soil_2"},
        buses={"soil_2": FakeI2CChannel(value=700)},   # inject the fake
    )
    reading = sensor.read()
    assert reading.ok is True
    assert reading.value == 700
```

The `buses` argument is a `dict` keyed by the sensor's id (or its type key, e.g.
`"ads1115"`). Because the real Adafruit/`w1thermsensor` import is lazy, this test
runs on any machine.

---

## Part 5 — Testing a new actuator

Drive it through its injected backend, and assert on tracked state — not
hardware:

```python
from farm_agent.actuators.relay import RelayActuator
from farm_agent.models import Command


def test_relay_turns_on_via_injected_backend():
    calls = []
    pump = RelayActuator("pump_1", "Pump", pin=17, backend=lambda pin, on: calls.append((pin, on)))
    result = pump.apply(Command(actuator_id="pump_1", action="on"))
    assert result.accepted is True
    assert pump.is_on is True
    assert calls == [(17, True)]
```

For safety behaviour (clamping, cooldown, mutual exclusion), test the
`SafetyGuard` with a `FakeClock` — see
[`tests/test_guard.py`](../../tests/test_guard.py) for the full set.

---

## Part 6 — Testing the whole loop

To test sensing -> deciding -> acting together, build a `ControlCycle` on fakes
exactly as [`tests/test_cycle.py`](../../tests/test_cycle.py) does, then assert on
the summary `run_once()` returns and on the fake actuator's recorded commands.
For the HTTP layer, use Flask's test client as in
[`tests/test_web.py`](../../tests/test_web.py).

---

## Verify it worked

You are done when:

1. `python -m pytest` passes with your new test file included.
2. Your new test runs with **no hardware** and no network.
3. Your sensor's failure cases return `ok=False` (not exceptions).

Next: deploy to real hardware in
[running-on-raspberry-pi.md](running-on-raspberry-pi.md).
