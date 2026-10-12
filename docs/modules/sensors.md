# Sensors — reading the environment

The sensor framework: one uniform `read()` interface, two ways of getting a
value (serial frame vs. direct hardware), and a hub that reads them all.

## What it does

Everything the rest of the system sees is a **`Sensor`** with a single method,
`read() -> Reading`. Whether a sensor talks to the Arduino or to a chip on the
Pi's own bus is irrelevant to the caller — they are interchangeable (Liskov).
The framework has four layers:

### 1. `Sensor` (abstract base — `sensors/base.py`)

The uniform interface. Every sensor has:

- `id`, `name`, `kind` properties.
- `read() -> Reading` — produce a measurement. **It must never raise for an
  expected failure**; it returns `Reading.failure(...)` instead, so one broken
  sensor never breaks a batch read.
- `from_config(cfg, *, transport=None, buses=None)` — a classmethod the factory
  calls to build an instance from one wiring-config entry (the **from_config
  contract**, below).
- `describe()` — a static dict (`id`, `name`, `kind`) with no read performed.

### 2. `SerialSensor` (abstract — `sensors/base.py`)

A sensor whose value is **one field of the Arduino's JSON frame**. The shared
`read()` does all the work: fetch the frame from the transport
(`current_frame(max_age)`), then `extract(frame)` — which pulls the named field,
applies a calibration offset, validates it against a valid range, and returns a
`Reading` (or `Reading.failure` if the field is missing, non-numeric, or out of
range). A concrete subclass usually only declares class attributes:

- `FIELD` — the JSON key to read (e.g. `"soil_raw"`).
- `UNIT` — the unit string (e.g. `"raw"`, `"°C"`).
- `VALID_RANGE` — the `(low, high)` of plausible values.

Two concrete serial sensors ship with the framework:

- **`SoilMoistureSensor`** (`sensors/soil_moisture.py`) — type key
  `"soil_moisture"`, field `soil_raw`, unit `raw`, range `(0, 1023)` (the
  Arduino's 10-bit ADC).
- **`TemperatureSensor`** (`sensors/temperature.py`) — type key `"temperature"`,
  field `temperature_c`, unit `°C`, range `(-55, 125)` (the DS18B20 family's
  rated range).

### 3. `DirectSensor` (abstract — `sensors/base.py`)

A sensor that reads **Pi hardware directly** (I2C, 1-Wire, GPIO). Hardware
libraries (Adafruit Blinka, `w1thermsensor`, etc.) are imported **lazily inside
the concrete subclass**, so the package still imports on a machine without them;
in simulation/tests a fake bus or device is injected instead. Two ship:

- **`Ads1115SoilSensor`** (`sensors/ads1115_soil.py`) — type key
  `"ads1115_soil"`, a soil probe read from an ADS1115 analog channel over I2C.
  Config: `address` (default `0x48`), `channel` index, `calibration_offset`. The
  channel is duck-typed — it only needs an integer `.value` attribute.
- **`Ds18b20Sensor`** (`sensors/ds18b20.py`) — type key `"ds18b20"`, temperature
  from a DS18B20 over 1-Wire. Config: `device_id`, `calibration_offset`. The
  device is duck-typed — it only needs a float `.temperature` attribute.

For both direct sensors, an injected bus/device (passed via `buses`) wins;
otherwise the real one is built lazily on first `read()`. If the hardware library
is missing or the bus fails, `read()` returns `Reading.failure(...)` with the
error message.

### 4. `SensorHub` (`sensors/hub.py`)

The one place the rest of the system asks for readings. It holds the live list of
sensors and offers:

- `read_all()` — read every sensor once; a broken sensor yields an `ok=False`
  reading rather than raising.
- `read_one(sensor_id)` — read one sensor by id; raises `KeyError` for an unknown
  id (the web layer maps this to a 404).
- `list_sensors()` — a static description of each sensor (no reads).

The hub depends only on the `Sensor` interface (dependency inversion) — it
neither knows nor cares whether a sensor is serial- or hardware-backed. Note:
reading the serial port only once per cycle is **not** the hub's job — that falls
out of the transport's frame cache (see [transport.md](transport.md)), which all
serial sensors share. The hub just calls `read()` on each sensor.

### The `from_config` contract

The factory never calls a sensor constructor directly. It looks the `type` up in
`sensor_registry`, then calls `cls.from_config(cfg, transport=..., buses=...)`:

- `cfg` — one entry from the wiring config (always has `id` and `type`; may have
  `name`, `field`, `unit`, `valid_range`, `calibration_offset`, `max_age`,
  `address`, `channel`, `device_id`, ...).
- `transport` — a `FrameSource` (the shared `SerialTransport`). **Serial sensors
  require it** and raise a clear `ValueError` if it is `None`.
- `buses` — a dict of injected hardware channels/devices for direct sensors
  (keyed by sensor id, or by a family key like `"ads1115"` / `"ds18b20"`).

`SerialSensor` provides a shared `from_config` that reads all the serial options;
direct sensors each implement their own to pick their bus out of `buses`.

## How to use it

In normal operation the config layer builds sensors for you; you only interact
with the `SensorHub`. The steps the factory performs, and that you follow when
testing, are:

1. **Create a transport** (real `SerialTransport` or a fake `FrameSource`).
2. **Build each sensor** via `from_config`, or construct it directly in tests.
3. **Put them in a `SensorHub`.**
4. **Read** with `read_all()` / `read_one(id)`.

```python
from farm_agent.sensors.soil_moisture import SoilMoistureSensor
from farm_agent.sensors.temperature import TemperatureSensor
from farm_agent.sensors.hub import SensorHub

# transport is any FrameSource (real SerialTransport, or a test fake)
soil = SoilMoistureSensor.from_config({"id": "soil_1", "name": "Soil moisture"},
                                      transport=transport)
temp = TemperatureSensor.from_config({"id": "temp_1", "name": "Temperature"},
                                     transport=transport)

hub = SensorHub([soil, temp])
for reading in hub.read_all():
    print(reading.sensor_id, reading.value, reading.unit, reading.ok)
```

To add a brand-new sensor type, see
[adding-a-sensor.md](../guides/adding-a-sensor.md) — it is one class plus one
config line (thanks to the [registry](registry.md)).

## What it depends on

- **`farm_agent.models`** — produces `Reading` objects.
- **`farm_agent.transport`** — serial sensors depend on the `FrameSource`
  protocol; the real `SerialTransport` supplies it.
- **`farm_agent.registry`** — each concrete sensor decorates itself with
  `@sensor_registry.register(...)`.
- **Hardware libraries** (Adafruit ADS1x15, `w1thermsensor`) — only imported
  lazily, inside direct sensors, at first real read. Never required to import the
  package.

## Example

A direct 1-Wire temperature sensor with an injected fake device (the pattern used
in simulation and tests — no hardware, no Adafruit libs):

```python
from farm_agent.sensors.ds18b20 import Ds18b20Sensor
from farm_agent.models import Reading

class FakeOneWireDevice:
    temperature = 22.5   # duck-typed: just needs a float .temperature

sensor = Ds18b20Sensor.from_config(
    {"id": "temp_soil", "name": "Soil temperature"},
    buses={"ds18b20": FakeOneWireDevice()},
)

reading = sensor.read()
assert isinstance(reading, Reading)
print(reading.value, reading.unit)   # 22.5 °C

# An out-of-range or missing value comes back as a failed Reading, never a crash:
# Reading(value=None, unit='°C', ok=False, error='value ... outside valid range ...')
```

## Where it lives

- `farm_agent/sensors/base.py` — `Sensor`, `SerialSensor`, `DirectSensor`
- `farm_agent/sensors/soil_moisture.py` — `SoilMoistureSensor`
- `farm_agent/sensors/temperature.py` — `TemperatureSensor`
- `farm_agent/sensors/ads1115_soil.py` — `Ads1115SoilSensor`
- `farm_agent/sensors/ds18b20.py` — `Ds18b20Sensor`
- `farm_agent/sensors/hub.py` — `SensorHub`

Related docs: [models.md](models.md), [transport.md](transport.md),
[registry.md](registry.md), [actuators.md](actuators.md).
