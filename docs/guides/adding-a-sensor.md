# Adding a Sensor

This is the headline tutorial. By the end you will have added a brand-new sensor to
the framework, wired it into config, set a target range for it, and confirmed it
shows up at `/sensors` — all in simulation, with no hardware.

The project's guiding rule is: **adding a sensor = one class + one config line.**
A concrete sensor class registers itself under a string type key, and the
config-driven factory builds it from a wiring entry. No other code changes.

There are two kinds of sensor, depending on *where the value comes from*:

- **(a) Serial sensor** — the value arrives inside the Arduino's JSON frame (one
  field of it). This is the common, easy case. Subclass `SerialSensor`.
- **(b) Direct sensor** — the value is read straight off Raspberry Pi hardware
  (I2C, 1-Wire, GPIO). Subclass `DirectSensor` with a lazy hardware import.

We will do a **full worked example of a serial sensor** (a humidity sensor), then
cover the direct-sensor path.

---

## Background: how a reading happens

All serial sensors share one Arduino JSON frame per cycle. `SerialSensor.read()`:

1. asks the transport for the latest frame (`transport.current_frame(...)`),
2. calls `extract(frame)`, which pulls out **this sensor's one field**, converts it
   to a float, adds the calibration offset, and checks it is inside the valid range,
3. returns a `Reading` (or `Reading.failure(...)` — a failed read never raises).

So a concrete serial sensor usually only declares four things: `kind`, `FIELD`
(the JSON key), `UNIT`, and `VALID_RANGE`. Everything else is inherited.

For reference, the existing soil sensor is the whole class:

```python
@sensor_registry.register("soil_moisture")
class SoilMoistureSensor(SerialSensor):
    kind = "soil_moisture"
    FIELD = "soil_raw"
    UNIT = "raw"
    VALID_RANGE = (0, 1023)
```

That is the pattern you are about to copy.

---

## Path (a): a serial sensor — worked example (humidity)

Goal: read a humidity percentage that the Arduino reports as the `humidity_pct`
field of its JSON frame.

### Step 1 — Write the sensor class

Create `farm_agent/sensors/humidity.py`:

```python
"""Relative-humidity sensor (serial-backed).

The humidity value arrives as the ``humidity_pct`` field of the Arduino's shared
JSON frame. Like the soil and temperature sensors, this class only declares which
field it owns, its unit, and what counts as a valid value; SerialSensor does the
rest (fetching the frame, extracting the field, validating, applying calibration).
"""

from __future__ import annotations

from farm_agent.registry import sensor_registry
from farm_agent.sensors.base import SerialSensor


@sensor_registry.register("humidity")
class HumiditySensor(SerialSensor):
    """Relative humidity (%), read via the Arduino."""

    kind = "humidity"
    FIELD = "humidity_pct"
    UNIT = "%"
    #: Relative humidity is a percentage, so 0..100.
    VALID_RANGE = (0, 100)
```

That is the entire class. The `@sensor_registry.register("humidity")` decorator is
what makes the type key `"humidity"` usable in config.

### Step 2 — Make the module import on package load

The registry decorator only runs when the module is imported. The sensors package
imports every concrete module for exactly this side effect, so add yours to
`farm_agent/sensors/__init__.py`:

```python
from farm_agent.sensors import (  # noqa: F401
    ads1115_soil,
    ds18b20,
    humidity,        # <-- add this line
    soil_moisture,
    temperature,
)
```

> **Why this matters:** if you skip this, `sensor_registry.get("humidity")` raises
> `Unknown sensor type 'humidity'. Available types: ...` when the factory tries to
> build it, because the class was never imported and never registered.

### Step 3 — Add one wiring-config entry

Wiring config says *which devices exist*. You can either edit the defaults for a
quick try, or (better) create your own JSON file and point `WIRING_CONFIG` at it.

Create `my-wiring.json` at the repo root:

```json
{
  "serial": {"port": "/dev/arduino", "baud": 9600, "timeout": 5.0},
  "sensors": [
    {"type": "soil_moisture", "id": "soil_1", "name": "Soil moisture", "field": "soil_raw"},
    {"type": "temperature",   "id": "temp_1", "name": "Air/soil temperature", "field": "temperature_c"},
    {"type": "humidity",      "id": "hum_1",  "name": "Relative humidity"}
  ],
  "actuators": [
    {"type": "relay", "id": "pump_1", "name": "Water pump", "pin": 17}
  ],
  "event_store": {"kind": "memory"}
}
```

The new line is the `humidity` entry. A sensor entry needs at least `type` (the
registered key) and `id` (a unique name you choose). Optional per-sensor overrides
the base class understands: `name`, `field` (defaults to the class `FIELD`), `unit`,
`valid_range`, `calibration_offset`, and `max_age`.

> **Tip — calibration:** if your probe reads consistently high or low, add
> `"calibration_offset": -3.0` to the entry. It is added to every raw value before
> the range check.

### Step 4 — Teach the simulator about the new field (so it shows a value)

In simulation the Arduino frame is faked. The default fake frame only contains
`soil_raw` and `temperature_c`, so a brand-new `humidity_pct` field would be
"missing" and your sensor would report `ok: false` ("field 'humidity_pct' missing
from frame"). That is correct behaviour — it proves the extraction works — but to
see a real value in simulation, provide the field.

The simplest way, without touching code, is to confirm the failure first (Step 6),
then supply a frame. The simulated transport accepts an override frame; the quickest
no-code demonstration is to accept the `ok: false` humidity reading as proof the
sensor is wired in. If you want a live value in simulation, the fake transport's
default fields live in `farm_agent/sim.py` (`SimulatedTransport.DEFAULTS`) — you may
add `"humidity_pct": 55.0` there for local experimentation.

> On real hardware this step is unnecessary: the Arduino supplies `humidity_pct` in
> its JSON frame and the sensor reads it directly.

### Step 5 — Add a target range in policy (optional but recommended)

So the control loop can act on humidity, give it a target range in policy config.
Create `my-policy.json`:

```json
{
  "strategy": "local_rules",
  "targets": {
    "soil_1": {"low": 400, "high": 800},
    "temp_1": {"low": 5, "high": 35},
    "hum_1":  {"low": 40, "high": 70}
  },
  "rules": {
    "soil_1": {"low": {"actuator_id": "pump_1", "action": "on", "duration_s": 180}}
  },
  "safety": {
    "pump_1": {"max_runtime_s": 300, "cooldown_s": 600, "max_activations_per_day": 24, "mutually_exclusive_with": []}
  }
}
```

The new part is `"hum_1": {"low": 40, "high": 70}` under `targets`. A reading outside
that band becomes a *deviation*. (To make a humidity deviation actually *do*
something, add a rule mapping it to an actuator — see
[configuring-rules.md](configuring-rules.md).)

### Step 6 — Run it in simulation and confirm it shows up

Start the app pointing at your two config files:

```bash
# Git Bash / macOS / Linux
SIMULATE=true \
  WIRING_CONFIG=my-wiring.json \
  POLICY_CONFIG=my-policy.json \
  python app.py
```

```powershell
# Windows PowerShell
$env:SIMULATE = "true"
$env:WIRING_CONFIG = "my-wiring.json"
$env:POLICY_CONFIG = "my-policy.json"
./.venv/Scripts/python.exe app.py
```

Then query the sensors:

```bash
curl http://localhost:8080/sensors/hum_1
```

If you did Step 4 (added `humidity_pct` to the sim defaults), expect:

```json
{"sensor_id": "hum_1", "name": "Relative humidity", "value": 55.0, "unit": "%", "ok": true, "error": null, "timestamp": "..."}
```

If you skipped Step 4, you will instead see the sensor present but failing cleanly,
which **still proves it is wired in correctly**:

```json
{"sensor_id": "hum_1", "name": "Relative humidity", "value": null, "unit": "%", "ok": false, "error": "field 'humidity_pct' missing from frame", "timestamp": "..."}
```

---

## Path (b): a direct hardware sensor

Use this when the value comes straight off the Pi (I2C/1-Wire/GPIO), not the
Arduino. The model class to copy is `Ads1115SoilSensor`
(`farm_agent/sensors/ads1115_soil.py`). Two rules matter:

1. **Lazy hardware import** — import the vendor library *inside* a method, never at
   module top level, so the package still imports on a machine with no hardware.
2. **Injectable device** — accept a pre-built channel/bus so tests and simulation
   can pass a fake; only build the real device when nothing was injected.

Skeleton for a new direct sensor `farm_agent/sensors/my_direct.py`:

```python
"""My direct-hardware sensor (reads the Pi directly)."""

from __future__ import annotations

from typing import Any, Optional

from farm_agent.models import Reading
from farm_agent.registry import sensor_registry
from farm_agent.sensors.base import DirectSensor


@sensor_registry.register("my_direct")
class MyDirectSensor(DirectSensor):
    kind = "my_direct"
    UNIT = "raw"
    VALID_RANGE = (0, 65535)

    def __init__(
        self,
        sensor_id: str,
        name: str,
        *,
        device: Optional[Any] = None,   # injected fake/real device
        address: int = 0x40,
        calibration_offset: float = 0.0,
    ) -> None:
        super().__init__(sensor_id, name)
        self._device = device
        self._address = address
        self._calibration = calibration_offset

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None, buses: Any = None) -> "MyDirectSensor":
        # If a bus/channel was injected (dict keyed by id or a type key), use it.
        device = None
        if isinstance(buses, dict):
            device = buses.get(cfg["id"]) or buses.get("my_direct")
        return cls(
            cfg["id"],
            cfg.get("name", cls.__name__),
            device=device,
            address=int(cfg.get("address", 0x40)),
            calibration_offset=float(cfg.get("calibration_offset", 0.0)),
        )

    def _real_device(self) -> Any:
        """Build the real device, importing the vendor lib lazily."""
        try:
            import board          # type: ignore
            import busio          # type: ignore
            import my_vendor_lib  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Hardware libraries not available; inject a device for testing."
            ) from exc
        i2c = busio.I2C(board.SCL, board.SDA)
        return my_vendor_lib.Device(i2c, address=self._address)

    def read(self) -> Reading:
        try:
            device = self._device
            if device is None:
                device = self._device = self._real_device()
            value = float(device.value) + self._calibration
        except Exception as exc:
            return Reading.failure(self.id, self.name, self.UNIT, str(exc))
        low, high = self.VALID_RANGE
        if not low <= value <= high:
            return Reading.failure(self.id, self.name, self.UNIT, f"value {value} outside valid range [{low}, {high}]")
        return Reading(self.id, self.name, value, self.UNIT)
```

The rest is identical to Path (a): add `my_direct` to the imports in
`farm_agent/sensors/__init__.py`, add a wiring entry
(`{"type": "my_direct", "id": "x_1", "address": 64}`), and set a target in policy.

> **Simulation note for direct sensors:** in `SIMULATE` mode the buses object
> (`SimBuses`, a `dict` subclass) hands each direct sensor a simulated device, so
> direct sensors return live simulated values out of the box — no hardware and no
> vendor libraries required. For your `from_config` to benefit, keep the same
> injection pattern the built-in direct sensors use: `if isinstance(buses, dict):
> device = buses.get(cfg["id"]) or buses.get("<type_key>")`. `SimBuses.get`
> recognises the type key (e.g. `"ads1115"`, `"ds18b20"`) and common id naming
> (`*soil*`, `*temp*`); for an unrecognised key it returns the default, so give
> your sensor a matching type key or id. Direct sensors are also exercised in the
> test suite with injected fakes (see `tests/fakes.py`).

---

## What NOT to touch

- You do **not** edit `SerialSensor` / `DirectSensor` in `sensors/base.py`,
  `registry.py`, the hub, or the web layer. The whole point of the registry is that
  new types plug in without changing shared code.
- You do **not** register the same type key twice — the registry raises a clear
  "already registered" error.

---

## Verify it worked

You have added a sensor successfully when:

1. The app starts with no import or config errors.
2. `curl http://localhost:8080/sensors` lists your new sensor id.
3. `curl http://localhost:8080/sensors/<your_id>` returns it — with `ok: true` and a
   value if the field/device is available, or a clean `ok: false` with a descriptive
   `error` if not (both prove it is wired in; a crash or an "Unknown sensor" 404
   would mean it is not).
4. If you added a target range, `POST /control/tick` (with your `API_TOKEN`) shows a
   `deviation` for it when the reading is outside the band — check `GET /events`.

Related: [configuring-rules.md](configuring-rules.md) to make a deviation trigger an
actuator, and [removing-a-device.md](removing-a-device.md) to take one out cleanly.
