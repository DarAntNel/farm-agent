# Actuator Types Reference

The built-in actuator types registered in `actuator_registry`. Each concrete
actuator module self-registers via an `@actuator_registry.register("<type key>")`
decorator (imported for effect by
[`farm_agent/actuators/__init__.py`](../../farm_agent/actuators/__init__.py)). The
`type` key in a wiring-config `actuators[]` entry must match one of these keys;
the factory (`build_actuators`) looks the class up and calls its `from_config`.

## Actuators are "dumb"

Every actuator models **only the raw device** — it enforces **no** policy. An
actuator's `_perform(...)` just toggles a pin or writes a serial line. Nothing
outside the actuator package calls `apply` directly: **all** commands flow through
the [`ActuatorController`](../modules/controller.md), which runs the
[safety guard](../modules/safety-guard.md) and [watchdog](../modules/watchdog.md)
first. That means the policy limits — `max_runtime_s` (duration clamp),
`cooldown_s`, `max_activations_per_day`, `mutually_exclusive_with` — and the
auto-off timer are applied uniformly, regardless of actuator type. A command the
guard rejects never reaches the device. See [config-schema.md](config-schema.md)
for the `safety` block.

## Registered types

| Type key | Class | Drives | Config keys read | Notes |
|----------|-------|--------|------------------|-------|
| `relay` | `RelayActuator` | A single GPIO relay pin on the Pi (e.g. a water pump): high = on, low = off | `pin` (required), `id`, `name` | Lazy `RPi.GPIO` import; GPIO backend injectable for tests. `"off"` drives the pin low, any other action drives it high. |
| `serial_actuator` | `SerialActuator` | An Arduino-side device driven by writing one command line over the shared serial link | `command` (optional, defaults to `id`), `id`, `name` | Writes `"<command> <action> <duration>"` (e.g. `pump on 180`, `pump off`); needs a serial transport (`LineSink`). |
| `fake` | `FakeActuator` | Nothing — records every command it is asked to perform | `id`, `name` | Used automatically in `SIMULATE=true` mode and as a spy in tests. No hardware. |

> **Simulation substitution.** In `SIMULATE=true` mode the bootstrap replaces the
> configured actuators with `FakeActuator`s that preserve each entry's `id` and
> `name`, so the whole system runs end-to-end with no hardware. In `DRY_RUN=true`
> mode the real actuators are built but the controller logs the would-apply
> command instead of firing it. See [`bootstrap.py`](../../farm_agent/bootstrap.py)
> and [config-schema.md](config-schema.md#environment-variables).

## Wiring-config keys per type

`type` and `id` are required for every actuator. See
[config-schema.md](config-schema.md) for the full file schema.

### `relay`

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `type` | yes | — | `"relay"` |
| `id` | yes | — | Unique actuator id (e.g. `pump_1`) |
| `name` | no | the `id` | Human-readable label |
| `pin` | yes | — | BCM GPIO pin number driven high (on) / low (off) |

### `serial_actuator`

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `type` | yes | — | `"serial_actuator"` |
| `id` | yes | — | Unique actuator id |
| `name` | no | the `id` | Human-readable label |
| `command` | no | the `id` | Arduino-side name used as the command-line prefix |

### `fake`

| Key | Required | Default | Meaning |
|-----|----------|---------|---------|
| `type` | yes | — | `"fake"` |
| `id` | yes | — | Unique actuator id |
| `name` | no | `"fake"` | Human-readable label |

## Actuator state

Regardless of type, each actuator reports the same state shape (via `/actuators`
and `/actuators/<id>`):

```json
{"id": "pump_1", "name": "Water pump", "kind": "relay", "is_on": false, "since": null}
```

`kind` equals the registered type key; `since` is the ISO timestamp of the last
on/off transition (or `null` if never toggled).

## Adding an actuator type

One class + one config line: subclass `Actuator`, implement `_perform` and
`from_config`, decorate with `@actuator_registry.register("<key>")`, import it in
`actuators/__init__.py`, then add an `actuators[]` entry. See the
[adding-an-actuator guide](../guides/adding-an-actuator.md) and the
[actuators module doc](../modules/actuators.md).

## Related

- [config-schema.md](config-schema.md) — wiring + policy (including the `safety` block)
- [sensor-types.md](sensor-types.md) — the sensor side
- [actuators module doc](../modules/actuators.md) · [controller](../modules/controller.md) · [safety-guard](../modules/safety-guard.md) · [watchdog](../modules/watchdog.md)
