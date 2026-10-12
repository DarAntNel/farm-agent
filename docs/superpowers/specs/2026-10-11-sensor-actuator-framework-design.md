# Sensor + Actuator Framework (with Safety Spine) — Design Spec

**Date:** 2026-10-11
**Status:** Approved for planning
**Author:** Daryl Nelson (with Claude Code)

## 1. The full system this belongs to

The end goal is a **smart-farm control loop**: sensors observe the environment,
the system compares readings against locally-stored config, and when conditions
drift out of range it decides corrective actions and drives **physical
actuators** (e.g. "soil too dry → run the water pump for 3 minutes"). Decisions
will eventually be made by an LLM/agent given the current readings, the config,
and recent history.

```
 [Sensors] ──readings──▶ [Control cycle] ──deviation?──▶ [Decision strategy]
    ▲                          │   ▲                       (LocalRules now,
    │                          │   └── policy config +        LLM later)
    │                          ▼        recent history            │
    │                   [Safety guard] ◀──── proposed commands ───┘
    │                          │  (validate / clamp / reject)
    │                          ▼
    └──────────────── [Actuators + watchdog] ──▶ turns pump on, auto-off
                               │
                               ▼
                        [Event store]  (feeds "previous events" back in)
```

### Sub-project map
1. **Sensor framework** — *this build*
2. **Actuator framework + safety spine** — *this build*
3. **Config & rules (wiring + policy split)** — *seams + loaders in this build*
4. **Event / history store** — *in-memory + JSONL in this build; durable backend later*
5. **Decision agent (LLM)** — *interface + stub in this build; real agent later*
6. **Control loop / scheduler** — *`run_once` spine in this build; daemon later*

## 2. Scope of THIS build

**In:** sensor framework (hybrid serial + direct), actuator framework, the
deterministic **safety guard layer**, **auto-off watchdog**, **dry-run +
simulation mode**, a **`LocalRulesStrategy`** decision strategy, the
`DecisionStrategy` interface with a **stubbed `LlmStrategy`**, an **event-log
seam** (in-memory + JSONL), the **wiring-vs-policy config split**, an **auth
seam** on actuator/control endpoints, a minimal **`ControlCycle.run_once`**
spine, the HTTP API, tests, and the `docs/` tree.

**Out (later sub-projects):** the real LLM call, a durable/queryable history
backend, a scheduled control daemon, alerting, multi-zone, hot-reload.

## 3. Non-goals

- No change to the Arduino's JSON output contract for sensors.
- No web UI; JSON endpoints only.
- No cloud dependency required to operate (offline-first; see §8).

## 4. Guiding principles

- **SOLID + dependency injection**: every collaborator is passed in via
  constructor; no module reaches for a global. Each file has one job.
- **The LLM only proposes; deterministic code disposes.** Nothing reaches
  hardware without passing the safety guard. Fail-safe = do nothing / turn off.
- **Add/remove a sensor or actuator = one class + one config line.** Same
  registry+factory pattern for both (DRY).
- **Everything runs without hardware** via simulation + fakes.

## 5. Shared core

### 5.1 Value objects (`models.py`) — all immutable dataclasses

- **`Reading`**: `sensor_id, name, value, unit, timestamp, ok, error`.
- **`Command`**: `actuator_id, action` (`"on"|"off"|"set"`), `duration_s|None`,
  `params: dict`, `source` (`"local_rules"|"llm"|"manual"`), `timestamp`.
- **`ActuatorResult`**: `actuator_id, accepted: bool, applied: Command|None,
  reason: str|None` (why rejected/clamped), `timestamp`.
- **`Deviation`**: `sensor_id, metric, value, target_low, target_high,
  direction` (`"low"|"high"`).
- **`Event`**: `type` (`"reading"|"deviation"|"decision"|"actuation"`),
  `timestamp`, `payload: dict`. The audit record.

### 5.2 Registry (`registry.py`)

One generic `Registry` class reused for both sensors and actuators. Maps a type
key → class with a `register(key)` decorator; raises a clear error on duplicate
registration and on unknown-type lookup (naming the available types). Two
instances: `sensor_registry`, `actuator_registry`.

## 6. Sensor framework (`sensors/`)

- **`Sensor`** (ABC, `base.py`): props `id, name, kind`; `read() -> Reading`.
- **`SerialSensor`** (abstract): holds a `SerialTransport`; `read()` pulls the
  shared latest JSON frame (`transport.current_frame()`) and calls subclass hook
  `extract(frame) -> Reading`. Subclass declares JSON field + valid range + unit.
  Applies **calibration offset** from wiring config.
  - `SoilMoistureSensor` — `soil_raw`, `0..1023`, unit `raw`.
  - `TemperatureSensor` — `temperature_c`, `-55..125`, unit `°C`.
- **`DirectSensor`** (abstract): reads hardware in `read()`; hardware imports
  guarded (`try/except ImportError`) so the package imports without Adafruit
  libs. Covered by fakes/sim.
  - `Ads1115SoilSensor` — I2C channel/address.
  - `Ds18b20Sensor` — 1-Wire device id.
- **`SensorHub`** (`hub.py`): `read_all()` (reads one serial frame, shared by
  all serial sensors), `read_one(id)` (KeyError → 404), `list_sensors()`.

`transport.py` holds **`SerialTransport`**: owns the pyserial connection,
thread-safe (lock), reconnect/retry (moved verbatim from today's globals), and
`current_frame(max_age)` returning a cached-or-fresh decoded JSON dict so the
port is read once per cycle.

## 7. Actuator framework (`actuators/`)

- **`Actuator`** (ABC, `base.py`): props `id, name, kind`; `apply(cmd: Command)
  -> ActuatorResult` (performs the raw action), `state() -> dict` (current
  on/off, since-when), `safe_off()` (force off).
  - `RelayActuator` — drives a GPIO relay pin (guarded import); a water pump is
    a relay actuator. Config declares the pin/port.
  - `SerialActuator` — sends a command line to the Arduino over the shared
    `SerialTransport` (for actuators wired to the Arduino).
  - `FakeActuator` — records commands; used in simulation/tests.

Actuators are **never called directly by the web or decision layers** — only
through the `ActuatorController` (§8), so the guard + watchdog + event log always
run.

## 8. Safety spine

### 8.1 Safety guard (`safety/`)

- **`SafetyLimits`** (`limits.py`) from policy config, per actuator:
  `max_runtime_s`, `cooldown_s`, `max_activations_per_day`,
  `mutually_exclusive_with: [actuator_id, ...]`.
- **`SafetyGuard`** (`guard.py`): deterministic, no LLM. Given a proposed
  `Command` + current actuator states + today's activation history, it:
  - **clamps** `duration_s` to `max_runtime_s`,
  - **rejects** if still in cooldown, over daily cap, or a mutually-exclusive
    actuator is active,
  - returns an allowed (possibly clamped) `Command` or a rejection with reason.
  The guard is the single chokepoint; the decision layer cannot bypass it.

### 8.2 Auto-off watchdog (`safety/watchdog.py`)

- When an actuator turns **on** with a duration, the watchdog schedules a
  guaranteed **off** (`threading.Timer`), recorded as an event.
- On **startup**, `safe_init()` forces every actuator to `safe_off()` — the
  system never boots into an unknown "on" state.

### 8.3 Actuator controller (`control/controller.py`)

`ActuatorController.execute(command) -> ActuatorResult`: guard-check → (unless
dry-run) `actuator.apply` → schedule auto-off → record an `actuation` event →
return result. Tracks live actuator state. **Honours dry-run** (logs the
would-apply command without firing).

## 9. Decision layer (`control/`)

- **`assess.py`**: `find_deviations(readings, policy) -> list[Deviation]` —
  compares each reading to its target range from policy config.
- **`DecisionStrategy`** (ABC, `strategy.py`): `decide(readings, deviations,
  history) -> list[Command]`.
  - **`LocalRulesStrategy`** (implemented): maps each deviation to a `Command`
    via rules in policy config (e.g. `soil` `direction=low` → pump `on`,
    `duration_s=180`). Deterministic; the offline fallback.
  - **`LlmStrategy`** (stub): implements the interface, documented as the §5
    sub-project seam. For now returns no commands and records a `decision` event
    noting "LLM strategy not yet wired". Future: assemble `readings + policy +
    recent history` → call Claude API → schema-validate structured commands.
- Strategy is selected by policy config (`"strategy": "local_rules"`), so
  swapping in the LLM later is a config change, not a code change (OCP).

## 10. Control cycle (`control/cycle.py`)

Minimal orchestration spine (full scheduler deferred):

`ControlCycle.run_once()`:
1. `readings = hub.read_all()` → record `reading` events.
2. `deviations = find_deviations(readings, policy)` → record `deviation` events.
3. `commands = strategy.decide(readings, deviations, history)` → record
   `decision` event.
4. For each command: `controller.execute(command)` (guard + apply + watchdog +
   `actuation` event).
5. Return a summary.

Exposed via `POST /control/tick`. A background scheduler calling `run_once` on an
interval is sub-project #6.

## 11. Event store (`events/`)

- **`EventStore`** (ABC): `record(event)`, `recent(n)`.
- **`InMemoryEventStore`** (ring buffer) — default.
- **`JsonlEventStore`** — appends events to a JSONL file (path from config) for
  a durable audit trail and the "previous events" context. Durable queryable
  backend is sub-project #4.

## 12. Config — two separate concerns (`config/`)

- **Wiring config** (`wiring.py`, env `WIRING_CONFIG` → JSON, else defaults):
  which sensors/actuators exist and the **port** each is on (serial field, I2C
  channel/address, GPIO pin, 1-Wire id) + calibration offsets.
- **Policy config** (`policy.py`, env `POLICY_CONFIG` → JSON, else defaults):
  target ranges per sensor, decision rules, safety limits, selected strategy,
  event-store settings.
- Both validated on load with clear, specific errors; sane defaults so the app
  runs out of the box in simulation.

## 13. Runtime modes

- **`SIMULATE=true`** — use `FakeSerialTransport` + fake buses + `FakeActuator`
  everywhere (default on a dev machine / CI). No hardware needed.
- **`DRY_RUN=true`** — full assess + decide + guard + event logging, but the
  controller does **not** fire actuators (logs would-apply). Safe on real
  hardware.
- Real mode — real transport + real actuators (needs hardware + Adafruit libs).

## 14. HTTP API (`web/`)

`create_app(hub, controller, cycle, event_store, policy, auth)` — Flask app
factory (DIP). `auth.py` provides a `@require_token` decorator checking
`Authorization` against `API_TOKEN` (env); **applied to every mutating /
actuator / control route**. Read routes open by default (configurable). This is
a starter seam, documented as needing hardening.

| Route | Auth | Behaviour |
|-------|------|-----------|
| `GET /` | no | Service info |
| `GET /health` | no | `{"status":"healthy"}` |
| `GET /sensor` | no | **Back-compat**: combined `soil_raw`+`temperature_c`; 503 if transport fully down |
| `GET /sensors` | no | All sensors + readings (200 even if some `ok=false`) |
| `GET /sensors/<id>` | no | One sensor; 404 unknown |
| `GET /actuators` | no | All actuators + current state |
| `GET /actuators/<id>` | no | One actuator; 404 unknown |
| `POST /actuators/<id>/command` | **yes** | Manual command → through guard+controller; 403 no token, 404 unknown, 422 rejected (with reason) |
| `POST /control/tick` | **yes** | Run one `run_once` cycle; returns summary |
| `GET /control/status` | no | Loop + actuator + strategy status |
| `GET /events?n=` | no | Recent events |

`app.py` stays a thin entrypoint wiring config → transport/buses → registries →
factory → hub/controller/cycle/store → `create_app`; `app.run(...)` unchanged so
Docker `CMD ["python","app.py"]` is unchanged.

## 15. Error handling

- Per-sensor failure → `Reading(ok=False, error=...)`; batch stays 200.
- Transport-open failure → serial sensors `ok=False`; `/sensor` → 503 (contract).
- Guard rejection → `ActuatorResult(accepted=False, reason=...)`; `POST
  …/command` → 422 with the reason; nothing fires.
- LLM/decision errors (future) → fall back to `LocalRulesStrategy`; never leave
  an actuator in an unknown state.

## 16. Testing (pytest, no hardware)

Fakes: `FakeSerialTransport` (scripted frames / raises), fake I2C + 1-Wire,
`FakeActuator`, a controllable clock for cooldown/watchdog tests.

- Sensors: valid / out-of-range / missing / malformed, per sensor; calibration.
- Registry: register, duplicate error, unknown-type error.
- Actuators: `apply`, `state`, `safe_off`.
- **Guard**: clamp to max runtime, reject in cooldown, reject over daily cap,
  reject on mutual exclusion.
- **Watchdog**: auto-off fires after duration; `safe_init` forces off.
- **LocalRulesStrategy**: deviation → expected command; no deviation → none.
- **ControlCycle.run_once**: end-to-end in simulation; dry-run fires nothing but
  logs; events recorded in order.
- Web: every route via test client, incl. 403 (no token), 404, 422, 503.

## 17. Documentation (`docs/`)

Human-readable, organised by **level** (architecture → modules → guides →
reference) and **type** (concept / how-to / reference). One step-by-step doc per
module/feature, each following **What it does → How to use it → What it depends
on → Example**.

```
docs/
  README.md                       Start here — map of all docs
  architecture/
    overview.md                   The full-system loop + the layers + diagram
    design-decisions.md           Why hybrid, registry, "LLM proposes/guard disposes", SOLID map
    safety-model.md               How nothing reaches hardware unguarded; fail-safe behaviour
  modules/
    models.md                     Reading / Command / ActuatorResult / Deviation / Event
    transport.md                  SerialTransport: connect, reconnect, frame cache
    registry.md                   Registration + factory pattern (shared)
    sensors.md                    Sensor / SerialSensor / DirectSensor
    actuators.md                  Actuator / Relay / Serial / Fake
    safety-guard.md               SafetyLimits + SafetyGuard (clamp/reject rules)
    watchdog.md                   Auto-off + safe startup
    decision.md                   assess + DecisionStrategy + LocalRules + LLM stub
    controller.md                 ActuatorController
    control-cycle.md              run_once spine
    events.md                     EventStore (in-memory + JSONL)
    config.md                     Wiring vs policy config
    web-api.md                    Flask layer, auth, routes
  guides/
    getting-started.md            Run in simulation, then Docker
    adding-a-sensor.md            End-to-end tutorial
    adding-an-actuator.md         End-to-end tutorial
    removing-a-device.md          Remove a sensor/actuator cleanly
    configuring-rules.md          Set target ranges + rules + safety limits
    simulation-and-dry-run.md     Test safely without a farm
  reference/
    api-endpoints.md              Every endpoint, request/response, auth, status codes
    sensor-types.md               Built-in sensors + their ports
    actuator-types.md             Built-in actuators + their ports
    config-schema.md              Wiring + policy schema reference
```

## 18. Final layout

```
farm_agent/
  __init__.py
  models.py
  registry.py
  transport.py
  sensors/{__init__,base,hub,soil_moisture,temperature,ads1115_soil,ds18b20}.py
  actuators/{__init__,base,relay,serial_actuator,fake}.py
  safety/{__init__,limits,guard,watchdog}.py
  control/{__init__,assess,strategy,controller,cycle}.py
  events/{__init__,store}.py
  config/{__init__,wiring,policy,defaults}.py
  web/{__init__,app,auth}.py
app.py                    thin entrypoint (Docker CMD unchanged)
tests/
  conftest.py  fakes.py
  test_sensors.py  test_actuators.py  test_registry.py
  test_guard.py  test_watchdog.py  test_strategy.py
  test_cycle.py  test_events.py  test_config.py  test_web.py
docs/                     (see §17)
requirements.txt          + pytest
Dockerfile                copy package + requirements
```
