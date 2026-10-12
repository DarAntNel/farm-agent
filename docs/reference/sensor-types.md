# Sensor Types Reference

The built-in sensor types registered in `sensor_registry`. Each concrete sensor
module self-registers via a `@sensor_registry.register("<type key>")` decorator
(imported for effect by
[`farm_agent/sensors/__init__.py`](../../farm_agent/sensors/__init__.py)). The
`type` key in a wiring-config `sensors[]` entry must match one of these keys; the
config factory (`build_sensors`) looks the class up and calls its `from_config`.

Every sensor produces a `Reading` and **never raises** for an expected failure —
a failed read returns `Reading.failure(...)` (`ok: false`, `value: null`, with an
`error` message). See [models](../modules/models.md).

## Registered types

| Type key | Class | Base | Measures | Unit | Valid range |
|----------|-------|------|----------|------|-------------|
| `soil_moisture` | `SoilMoistureSensor` | `SerialSensor` | Soil moisture (capacitive/resistive probe on the Arduino) | `raw` | `0 .. 1023` (10-bit Arduino ADC) |
| `temperature`   | `TemperatureSensor`  | `SerialSensor` | Ambient/soil temperature via the Arduino | `°C` | `-55 .. 125` |
| `ads1115_soil`  | `Ads1115SoilSensor`  | `DirectSensor` | Soil moisture read from an ADS1115 ADC channel over I2C | `raw` | `0 .. 32767` (16-bit single-ended) |
| `ds18b20`       | `Ds18b20Sensor`      | `DirectSensor` | Temperature from a DS18B20 over 1-Wire | `°C` | `-55 .. 125` |

> **Serial vs direct.** `SerialSensor` sensors read their value from a field of
> the Arduino's shared JSON frame (fetched via the serial transport). `DirectSensor`
> sensors read Pi hardware directly (I2C / 1-Wire), importing the Adafruit
> libraries lazily so the package still imports without hardware; in
> simulation/tests a fake bus or device is injected.

## Wiring-config keys per type

These are the keys each sensor reads from its `sensors[]` entry in the **wiring**
config (via `from_config`). `type` and `id` are required for every sensor; all
others are optional with the defaults shown. See
[config-schema.md](config-schema.md) for the full file schema.

### `soil_moisture` and `temperature` (serial)

Both share the `SerialSensor` config contract.

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `type` | yes | — | `"soil_moisture"` or `"temperature"` |
| `id` | yes | — | Unique sensor id (e.g. `soil_1`, `temp_1`) |
| `name` | no | class name | Human-readable label |
| `field` | no | class `FIELD` (`soil_raw` / `temperature_c`) | JSON field to read from the Arduino frame |
| `unit` | no | class `UNIT` (`raw` / `°C`) | Reported unit |
| `valid_range` | no | class `VALID_RANGE` | `[low, high]`; a value outside it becomes a failed read |
| `calibration_offset` | no | `0.0` | Added to the raw value before range check |
| `max_age` | no | `1.0` | Max age (seconds) of a cached serial frame before a fresh read |

### `ads1115_soil` (direct, I2C)

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `type` | yes | — | `"ads1115_soil"` |
| `id` | yes | — | Unique sensor id |
| `name` | no | class name | Human-readable label |
| `channel` | no | `0` | ADS1115 analog input channel index (→ `P0`..`P3`) |
| `address` | no | `0x48` (72) | I2C bus address of the ADS1115 |
| `calibration_offset` | no | `0.0` | Added to the raw value before range check |

> In simulation/tests, a fake channel is injected via the `buses` mapping keyed
> by the sensor's `id` or by `"ads1115"`; when present it wins over building a
> real channel.

### `ds18b20` (direct, 1-Wire)

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `type` | yes | — | `"ds18b20"` |
| `id` | yes | — | Unique sensor id |
| `name` | no | class name | Human-readable label |
| `device_id` | no | first device on the bus | 1-Wire device id to select a specific probe |
| `calibration_offset` | no | `0.0` | Added to the °C value before range check |

> In simulation/tests, a fake device is injected via the `buses` mapping keyed by
> the sensor's `id` or by `"ds18b20"`.

## Adding a sensor type

Each new sensor is one class + one config line: subclass `SerialSensor` or
`DirectSensor`, decorate it with `@sensor_registry.register("<key>")`, import it
in `sensors/__init__.py`, then add a `sensors[]` entry with the matching `type`.
See the [adding-a-sensor guide](../guides/adding-a-sensor.md) and the
[sensors module doc](../modules/sensors.md).

## Related

- [config-schema.md](config-schema.md) — full wiring/policy schema
- [actuator-types.md](actuator-types.md) — the actuator side
- [sensors module doc](../modules/sensors.md) · [registry module doc](../modules/registry.md)
