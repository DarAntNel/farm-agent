# Config Schema Reference

farm-agent keeps **two separate** JSON config files, reflecting two separate
concerns (see [`farm_agent/config/`](../../farm_agent/config/) and the
[config module doc](../modules/config.md)):

- **Wiring** — *hardware topology*: which devices exist and the port each is on.
  Loaded by `load_wiring()` from `$WIRING_CONFIG`, else the built-in defaults.
- **Policy** — *farming behaviour*: target ranges, decision rules, safety limits,
  strategy choice. Loaded by `load_policy()` from `$POLICY_CONFIG`, else defaults.

Both are plain JSON objects, validated on load with clear errors, and both have
sane defaults so the app boots out of the box (in simulation) with no external
files.

---

## Wiring config

Top-level keys:

| Key | Type | Required | Meaning |
|-----|------|----------|---------|
| `serial` | object | no | Serial link to the Arduino (used in real mode) |
| `sensors` | array | no | Sensor entries to instantiate |
| `actuators` | array | no | Actuator entries to instantiate |
| `event_store` | object | no | Where audit events are stored |

### `serial`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `port` | string | `"/dev/arduino"` | Serial device path |
| `baud` | integer | `9600` | Baud rate |
| `timeout` | number | `5.0` | Read timeout in seconds |

### `sensors[]`

Each entry needs at least `type` and `id` (validated on load). `type` must be a
registered sensor key. Remaining keys depend on the type — see
[sensor-types.md](sensor-types.md) for the per-type key tables.

| Key | Type | Required | Meaning |
|-----|------|----------|---------|
| `type` | string | yes | Registered sensor type key (`soil_moisture`, `temperature`, `ads1115_soil`, `ds18b20`) |
| `id` | string | yes | Unique sensor id |
| `name` | string | no | Human-readable label |
| `field` | string | no | (serial) JSON field in the Arduino frame |
| `calibration_offset` | number | no | Added to the raw value |
| `unit`, `valid_range`, `max_age` | — | no | (serial) see [sensor-types.md](sensor-types.md) |
| `channel`, `address` | int | no | (`ads1115_soil`) I2C channel index / bus address |
| `device_id` | string | no | (`ds18b20`) 1-Wire device id |

### `actuators[]`

Each entry needs at least `type` and `id`. `type` must be a registered actuator
key. See [actuator-types.md](actuator-types.md) for the per-type key tables.

| Key | Type | Required | Meaning |
|-----|------|----------|---------|
| `type` | string | yes | Registered actuator type key (`relay`, `serial_actuator`, `fake`) |
| `id` | string | yes | Unique actuator id |
| `name` | string | no | Human-readable label |
| `pin` | integer | yes for `relay` | BCM GPIO pin |
| `command` | string | no | (`serial_actuator`) Arduino-side command prefix; defaults to `id` |

### `event_store`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `kind` | string | `"memory"` | `"memory"` (in-RAM ring buffer) or `"jsonl"` (append-only file) |
| `path` | string | — | **Required when `kind` is `"jsonl"`**: the JSONL file path |

See the [events module doc](../modules/events.md).

### Annotated wiring example

```jsonc
{
  "serial": {
    "port": "/dev/arduino",   // serial device the Arduino is on
    "baud": 9600,             // must match the Arduino sketch
    "timeout": 5.0            // seconds before a read gives up
  },
  "sensors": [
    {
      "type": "soil_moisture", // registered sensor key
      "id": "soil_1",          // unique id (also used by /sensor back-compat)
      "name": "Soil moisture",
      "field": "soil_raw",     // JSON field in the Arduino frame
      "calibration_offset": 0  // added to the raw reading
    },
    {
      "type": "temperature",
      "id": "temp_1",
      "name": "Air/soil temperature",
      "field": "temperature_c"
    }
    // Direct-hardware alternatives:
    // { "type": "ads1115_soil", "id": "soil_2", "channel": 0, "address": 72 }
    // { "type": "ds18b20", "id": "temp_2", "device_id": "00000abc1234" }
  ],
  "actuators": [
    {
      "type": "relay",         // registered actuator key
      "id": "pump_1",          // unique id (referenced by policy rules/safety)
      "name": "Water pump",
      "pin": 17                // BCM GPIO pin the relay is wired to
    }
    // Arduino-side alternative:
    // { "type": "serial_actuator", "id": "valve_1", "command": "valve" }
  ],
  "event_store": {
    "kind": "memory"           // or "jsonl" with a "path"
    // "kind": "jsonl", "path": "/var/log/farm-agent/events.jsonl"
  }
}
```

---

## Policy config

Top-level keys:

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `strategy` | string | `"local_rules"` | Decision strategy to use (`local_rules`, or `llm` — stub) |
| `targets` | object | `{}` | Per-sensor acceptable range; a reading outside it is a deviation |
| `rules` | object | `{}` | Per-sensor, per-direction command to issue on a deviation |
| `safety` | object | `{}` | Per-actuator safety limits enforced by the guard |

### `targets{}`

Keyed by **sensor id**. Each target needs both `low` and `high` (validated;
`low > high` is an error).

| Key | Type | Meaning |
|-----|------|---------|
| `low` | number | Inclusive lower bound; a value below it is a `low` deviation |
| `high` | number | Inclusive upper bound; a value above it is a `high` deviation |

### `rules{}`

Keyed by **sensor id**, then by **direction** (`low` or `high`). The value is the
command to propose when that deviation occurs.

| Key | Type | Required | Meaning |
|-----|------|----------|---------|
| `actuator_id` | string | yes | Which actuator to command |
| `action` | string | no (default `"on"`) | `"on"`, `"off"` or `"set"` |
| `duration_s` | number | no | Auto-off after N seconds (still clamped by the guard) |
| `params` | object | no | Pass-through parameters |

### `safety{}`

Keyed by **actuator id**. Enforced deterministically on every command by the
[safety guard](../modules/safety-guard.md), whoever proposed it. An actuator with
no entry uses conservative defaults (`max_runtime_s` 300, no cooldown, effectively
unlimited daily activations, no exclusions).

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `max_runtime_s` | number | `300` | An `on` command's `duration_s` is **clamped** to this |
| `cooldown_s` | number | `0` | Minimum seconds between the end of one activation and the next; a command sooner is **rejected** |
| `max_activations_per_day` | integer | `1000000` | Hard cap on activations in a rolling 24h; over it is **rejected** |
| `mutually_exclusive_with` | array of ids | `[]` | Actuators that must not be on at the same time; a conflict is **rejected** |

### Annotated policy example

```jsonc
{
  "strategy": "local_rules",   // deterministic rules; "llm" is a stub for now
  "targets": {
    "soil_1": { "low": 400, "high": 800 },  // soil raw in-range band
    "temp_1": { "low": 5,   "high": 35 }    // temperature °C in-range band
  },
  "rules": {
    "soil_1": {
      "low": {                        // soil below 400 -> run the pump
        "actuator_id": "pump_1",
        "action": "on",
        "duration_s": 180             // request 3 min (guard may clamp it)
      }
      // "high": { ... }              // optional rule for the other direction
    }
  },
  "safety": {
    "pump_1": {
      "max_runtime_s": 300,           // clamp any on-duration to 5 min
      "cooldown_s": 600,              // at least 10 min between runs
      "max_activations_per_day": 24,  // at most 24 runs / rolling day
      "mutually_exclusive_with": []   // e.g. ["drain_1"] to block overlap
    }
  }
}
```

---

## Environment variables

Set at process start; read by the bootstrap and web layers.

| Variable | Default | Effect |
|----------|---------|--------|
| `WIRING_CONFIG` | *(built-in defaults)* | Path to the wiring JSON file |
| `POLICY_CONFIG` | *(built-in defaults)* | Path to the policy JSON file |
| `SIMULATE` | `false` | `true` → simulated transport/buses + `FakeActuator`s; runs with no hardware |
| `DRY_RUN` | `false` | `true` → real sensing, but the controller logs actuator commands instead of firing them |
| `API_TOKEN` | *(unset)* | Bearer token for guarded routes; **unset disables those routes (403)** — see [api-endpoints.md](api-endpoints.md#authentication) |
| `PORT` | `8080` | TCP port the Flask app listens on |

> Booleans accept `1`, `true`, `yes`, `on` (case-insensitive) as true.
> `SIMULATE` and `DRY_RUN` can also be passed directly to `build_system(...)`.

## Related

- [sensor-types.md](sensor-types.md) · [actuator-types.md](actuator-types.md) · [api-endpoints.md](api-endpoints.md)
- [config module doc](../modules/config.md) · [events module doc](../modules/events.md) · [safety-guard module doc](../modules/safety-guard.md)
