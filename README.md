# farm-agent

A modular, extensible smart-farm framework. Sensors observe the environment, a
decision layer compares readings against locally-stored config, and — when
conditions drift — a **deterministic safety layer** drives actuators (e.g. "soil
too dry → run the water pump for 3 minutes"). The decision step is pluggable:
deterministic local rules today, an LLM/agent later, behind the same interface.

> **Design principle:** the decision layer only *proposes* actions; the safety
> guard *disposes* — nothing reaches hardware without passing runtime, cooldown,
> daily-cap and mutual-exclusion checks, and every "on" gets a guaranteed
> auto-off.

## Quick start (no hardware)

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # Linux/Pi

SIMULATE=true API_TOKEN=dev ./.venv/Scripts/python.exe app.py
```

Then:

```bash
curl localhost:8080/sensors
curl localhost:8080/control/status
curl -X POST localhost:8080/control/tick -H "Authorization: Bearer dev"
```

Run the tests:

```bash
./.venv/Scripts/python.exe -m pytest
```

## How it fits together

```
 Sensors ──readings──▶ Control cycle ──deviation?──▶ Decision strategy
    ▲                        │   ▲                    (LocalRules now, LLM later)
    │                        │   └── policy + history          │
    │                   Safety guard ◀──── proposed commands ──┘
    │                        │  (clamp / cooldown / reject)
    │                        ▼
    └──────────── Actuators + auto-off watchdog ──▶ pump on, guaranteed off
                             │
                             ▼
                        Event store  (the audit trail / "previous events")
```

## Add a sensor or actuator

Adding a device is a **one class + one config line** change:

1. Write a class and register it (`@sensor_registry.register("my_type")`).
2. Add one entry to the wiring config naming that `type` and its port.

See [docs/guides/adding-a-sensor.md](docs/guides/adding-a-sensor.md) and
[docs/guides/adding-an-actuator.md](docs/guides/adding-an-actuator.md).

## Runtime modes

| Mode | Env | Effect |
|------|-----|--------|
| Simulation | `SIMULATE=true` | Fake transport/buses + fake actuators — runs anywhere, no hardware. |
| Dry run | `DRY_RUN=true` | Real sensing, but actuator commands are logged, not fired. |
| Live | (neither) | Real serial link + real actuators (Raspberry Pi). |

## Documentation

Full, human-readable docs live in [docs/](docs/README.md):

- **Architecture** — the big picture, design decisions, and the safety model.
- **Modules** — one step-by-step doc per module.
- **Guides** — getting started, adding/removing devices, configuring rules,
  simulation & dry-run.
- **Reference** — API endpoints, built-in sensor/actuator types, config schema.

The authoritative design spec is in
[docs/superpowers/specs/](docs/superpowers/specs/2026-10-11-sensor-actuator-framework-design.md).

## Project layout

```
farm_agent/
  models.py registry.py transport.py bootstrap.py sim.py
  sensors/    actuators/    safety/    control/    events/    config/    web/
app.py          # thin entrypoint (Docker CMD unchanged)
tests/          # pytest suite, runs with no hardware
docs/           # human-readable documentation
```

## Roadmap

This repo is the sensing + actuation foundation with a safety spine. Planned
follow-on sub-projects, each slotting in behind the existing seams:

1. Real LLM decision agent (replacing the `LlmStrategy` stub).
2. Durable, queryable history backend.
3. A scheduled control daemon (currently `run_once` on demand).
4. Alerting and multi-zone support.
