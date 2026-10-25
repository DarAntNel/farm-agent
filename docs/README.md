# farm-agent Documentation

Welcome. This is the **start-here map** for the farm-agent documentation. It is
written for a developer who is new to this codebase and not expected to be an
expert — read the Architecture docs top to bottom first, then dip into the others
as you need them.

farm-agent is a modular **smart-farm control loop**: it senses the environment,
decides corrective actions against locally-stored config, and drives physical
actuators — with a deterministic safety spine so nothing reaches hardware
un-guarded, and a simulation mode so the whole thing runs with no hardware.

## How this documentation is organised

Docs are grouped by **level**, from the big picture down to exact details:

- **Architecture** — the whole system: what it is, why it is shaped this way,
  how it stays safe. *Start here.*
- **Modules** — one focused doc per code module (what it does, how to use it,
  what it depends on, an example).
- **Guides** — step-by-step, task-oriented how-tos ("add a sensor", "run in
  simulation").
- **Reference** — lookup tables: endpoints, device types, config schema.

> The full set of Architecture, Modules, Guides, and Reference docs below is
> written and in sync with the code. The authoritative design is the spec at
> [superpowers/specs/2026-10-11-sensor-actuator-framework-design.md](superpowers/specs/2026-10-11-sensor-actuator-framework-design.md).

---

## Architecture — read these first

| Doc | What it covers |
|-----|----------------|
| [architecture/overview.md](architecture/overview.md) | The full-system control loop (sense -> decide -> act), the inward-pointing layers (web -> control -> building blocks -> shared core), an ASCII diagram, how a request/tick flows end to end, and the `SIMULATE` / `DRY_RUN` runtime modes. |
| [architecture/design-decisions.md](architecture/design-decisions.md) | The *why*: one `Sensor` interface over hybrid serial + direct hardware; the registry + config "add one class + one config line" extensibility; "the decision layer proposes, the safety guard disposes"; the wiring-config vs policy-config split; dependency injection everywhere; and each SOLID principle mapped to a concrete place in the code. |
| [architecture/safety-model.md](architecture/safety-model.md) | How nothing reaches hardware un-guarded: every command flows `ActuatorController` -> `SafetyGuard` (clamp / cooldown / daily-cap / mutual-exclusion) -> `Actuator`, plus the auto-off `Watchdog` and `safe_init` at startup; fail-safe = off; and exactly what the LLM can and cannot do. |

---

## Modules — one doc per code module

| Doc | What it covers |
|-----|----------------|
| [modules/models.md](modules/models.md) | The immutable value objects: `Reading`, `Command`, `ActuatorResult`, `Deviation`, `Event`. |
| [modules/transport.md](modules/transport.md) | `SerialTransport`: connect, reconnect, and the shared decoded-frame cache. |
| [modules/registry.md](modules/registry.md) | The shared registration + factory pattern used for sensors and actuators. |
| [modules/sensors.md](modules/sensors.md) | `Sensor` / `SerialSensor` / `DirectSensor` and the `SensorHub`. |
| [modules/actuators.md](modules/actuators.md) | `Actuator` and the `Relay` / `Serial` / `Fake` implementations. |
| [modules/safety-guard.md](modules/safety-guard.md) | `SafetyLimits` + `SafetyGuard` and the clamp/reject rules. |
| [modules/watchdog.md](modules/watchdog.md) | The auto-off watchdog and safe startup. |
| [modules/decision.md](modules/decision.md) | `assess` + `DecisionStrategy` + `LocalRulesStrategy` + the `LlmStrategy` stub. |
| [modules/controller.md](modules/controller.md) | `ActuatorController`, the single command chokepoint. |
| [modules/control-cycle.md](modules/control-cycle.md) | `ControlCycle.run_once`, the orchestration spine. |
| [modules/events.md](modules/events.md) | `EventStore` (in-memory ring buffer + JSONL). |
| [modules/config.md](modules/config.md) | Wiring config vs policy config: loaders and defaults. |
| [modules/web-api.md](modules/web-api.md) | The Flask layer, the auth seam, and the routes. |

---

## Guides — step-by-step how-tos

| Doc | What it covers |
|-----|----------------|
| [guides/getting-started.md](guides/getting-started.md) | Run in simulation, then in Docker. |
| [guides/adding-a-sensor.md](guides/adding-a-sensor.md) | End-to-end tutorial: add a new sensor. |
| [guides/adding-an-actuator.md](guides/adding-an-actuator.md) | End-to-end tutorial: add a new actuator. |
| [guides/removing-a-device.md](guides/removing-a-device.md) | Remove a sensor or actuator cleanly. |
| [guides/configuring-rules.md](guides/configuring-rules.md) | Set target ranges, decision rules, and safety limits. |
| [guides/simulation-and-dry-run.md](guides/simulation-and-dry-run.md) | Test safely without a farm. |
| [guides/testing.md](guides/testing.md) | Run the suite, and write tests for a new sensor/actuator with the fakes. |
| [guides/running-on-raspberry-pi.md](guides/running-on-raspberry-pi.md) | Deploy to real hardware: wiring, interfaces, dry-run → live, systemd, Docker. |

---

## Reference — lookup tables

| Doc | What it covers |
|-----|----------------|
| [reference/api-endpoints.md](reference/api-endpoints.md) | Every endpoint: request/response, auth, status codes. |
| [reference/sensor-types.md](reference/sensor-types.md) | Built-in sensors and their ports. |
| [reference/actuator-types.md](reference/actuator-types.md) | Built-in actuators and their ports. |
| [reference/config-schema.md](reference/config-schema.md) | The wiring + policy config schema. |

---

## Also useful

- **The authoritative design spec:**
  [superpowers/specs/2026-10-11-sensor-actuator-framework-design.md](superpowers/specs/2026-10-11-sensor-actuator-framework-design.md)
  — the full approved design this codebase is built from.
