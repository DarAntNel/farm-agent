# System Overview

This document is the big picture. Read it first. It explains **what the
farm-agent framework does**, the **layers** it is built from, how a single
request or control tick **flows from end to end**, and the two **runtime modes**
(`SIMULATE` and `DRY_RUN`) that let you run the whole thing safely without a
farm.

If you are brand new, read this top to bottom. For *why* it is built this way,
see [design-decisions.md](design-decisions.md). For how hardware is kept safe,
see [safety-model.md](safety-model.md).

---

## 1. What the system does: sense -> decide -> act

farm-agent is a **smart-farm control loop**. In plain terms it repeats three
steps:

1. **Sense** — read the environment (soil moisture, temperature, ...).
2. **Decide** — compare each reading against the target range in config; where a
   reading has drifted out of range, decide what corrective action to take
   (for example: "soil too dry -> run the water pump for 3 minutes").
3. **Act** — drive physical actuators (relays, pumps) to apply those decisions.

Everything the system observes and does is recorded as an **Event**, so the
history can later answer "why did the pump run at 3am?" and feed a future LLM
decision agent as context.

```
 [Sensors] --readings--> [Control cycle] --deviation?--> [Decision strategy]
    ^                          |   ^                       (LocalRules now,
    |                          |   +-- policy config +        LLM later)
    |                          v        recent history            |
    |                   [Safety guard] <---- proposed commands ---+
    |                          |  (validate / clamp / reject)
    |                          v
    +---------------- [Actuators + watchdog] --> turns pump on, auto-off
                               |
                               v
                        [Event store]  (feeds "previous events" back in)
```

The key idea to hold onto: **the decision layer only proposes; a deterministic
safety guard disposes.** Nothing reaches hardware without passing the guard, and
the fail-safe is always "do nothing / turn off".

---

## 2. The layers (inward-pointing dependencies)

The package is organised in layers. **Outer layers depend on inner layers, never
the reverse.** The shared core at the bottom knows nothing about the web.

```
+-----------------------------------------------------------+
|  web/            HTTP layer (Flask app factory, auth)     |  <- outermost
+-----------------------------------------------------------+
|  control/        orchestration:                            |
|                  ControlCycle, ActuatorController,         |
|                  DecisionStrategy, assess                  |
+-----------------------------------------------------------+
|  sensors/   actuators/   safety/   events/   config/       |
|  (building blocks: read, act, guard, record, load config) |
+-----------------------------------------------------------+
|  models/    registry/    transport/                        |  <- shared core
|  (value objects, type registry, serial I/O)               |
+-----------------------------------------------------------+
```

What lives where:

- **`models.py`** — immutable value objects everyone speaks in: `Reading`,
  `Command`, `ActuatorResult`, `Deviation`, `Event`. See
  [models module docs](../modules/models.md).
- **`registry.py`** — a tiny generic `Registry` that maps a string type-key to a
  class. Reused for both sensors and actuators so adding a device is "one class +
  one config line".
- **`transport.py`** — `SerialTransport`, the shared serial connection to the
  Arduino; hands out the latest decoded JSON frame.
- **`sensors/`** — the `Sensor` interface plus `SerialSensor` / `DirectSensor`
  and a `SensorHub` that reads them all.
- **`actuators/`** — the `Actuator` interface plus `RelayActuator`,
  `SerialActuator`, `FakeActuator`.
- **`safety/`** — the `SafetyGuard` (clamp/reject rules) and the auto-off
  `Watchdog`.
- **`events/`** — the `EventStore` (in-memory ring buffer or JSONL file).
- **`config/`** — two separate config loaders: **wiring** (what hardware exists
  and on which port) and **policy** (target ranges, rules, safety limits, which
  strategy to use).
- **`control/`** — the orchestration: `ActuatorController` (the one chokepoint to
  hardware), `DecisionStrategy` (local rules now, LLM later), `assess`
  (readings -> deviations) and `ControlCycle` (one full pass).
- **`web/`** — a thin Flask app factory that shapes JSON and maps outcomes to
  HTTP status codes.

Two files hold the system together:

- **`bootstrap.py`** — the *composition root*. It reads the environment, decides
  which concrete collaborators to build (real vs simulated), wires them together,
  and returns the Flask `app`.
- **`app.py`** — a thin entrypoint that just calls `build_system()` and runs the
  app (so the Docker `CMD ["python", "app.py"]` never changes).

---

## 3. How a request flows end to end

There are two ways work enters the system: an **HTTP request** and a **control
tick**. They converge on the same safety-guarded path to hardware.

### 3.1 A manual command: `POST /actuators/<id>/command`

```
HTTP request
   |
   v
web/app.py  --- @require_token checks the Authorization header (403 if missing)
   |          builds a Command(source="manual")
   v
ActuatorController.execute(command)      <-- the single chokepoint
   |
   +--> SafetyGuard.review(command, actuators)
   |        clamp duration? in cooldown? daily cap? mutual exclusion?
   |        -> ActuatorResult(accepted=False, reason=...)  --> 422 to caller
   |
   +--> (if accepted and NOT dry-run) actuator.apply(approved)
   |        on success + action "on": record activation, schedule auto-off
   |
   +--> record an "actuation" Event
   |
   v
ActuatorResult  -->  200 (accepted) or 422 (rejected, with reason)
```

The web layer never touches an actuator directly. It only ever calls
`controller.execute(...)`, so the guard, watchdog, dry-run handling, and event
logging always run.

### 3.2 One control tick: `POST /control/tick` -> `ControlCycle.run_once()`

`run_once()` is the "sense -> decide -> act" loop in code
(`farm_agent/control/cycle.py`):

```
ControlCycle.run_once()
  1. SENSE    readings = hub.read_all()
              record a "reading" Event per reading
  2. ASSESS   deviations = find_deviations(readings, policy)
              record a "deviation" Event per deviation
  3. DECIDE   history  = event_store.recent(50)
              commands = strategy.decide(readings, deviations, history)
              record one "decision" Event (strategy name + commands)
  4. ACT      for each command: controller.execute(command)
              (each goes through guard + watchdog + "actuation" Event)
  -> return a summary dict (readings, deviations, commands, results)
```

Step 3's `strategy` only **proposes** `Command`s. Step 4 routes every one of
them through the same `ActuatorController.execute` chokepoint shown in 3.1, so a
proposal from the decision layer gets exactly the same safety treatment as a
manual command.

A background scheduler that calls `run_once()` on a timer is a planned later
sub-project; for now the cycle runs on demand (via the HTTP route) and in tests.

---

## 4. Runtime modes

The composition root (`bootstrap.build_system`) picks concrete collaborators
based on two environment variables. This is the only place that decision is made;
everything downstream just uses the objects it is given.

### `SIMULATE=true` — no hardware at all

- Substitutes a `SimulatedTransport` and simulated buses for the real serial
  connection, and `FakeActuator`s (preserving each actuator's id and name) for
  the real relays.
- The entire sense -> decide -> act loop runs end to end on a laptop or in CI,
  with no Arduino, no Raspberry Pi, and no Adafruit libraries installed.
- This is the default for development and testing.

### `DRY_RUN=true` — real sensing, no firing

- Everything runs for real: sensors are read, deviations are found, the strategy
  decides, the guard reviews, and events are logged.
- **But the controller does not fire the actuators.** When `dry_run` is set,
  `ActuatorController.execute` returns an accepted result annotated
  `"dry-run: not applied"` and records the event, without calling
  `actuator.apply`.
- This is the safe way to watch what the system *would* do on real hardware
  before letting it actually move anything.

### Real mode (neither flag set)

- Uses the real `SerialTransport` and real actuators. Requires the hardware and
  the hardware libraries to be present.

The two flags are independent: you can run simulated-and-dry, simulated-and-live,
or real-and-dry. At startup, regardless of mode, the controller runs
`safe_init()` to force every actuator off, so the system never boots into an
unknown "on" state (see [safety-model.md](safety-model.md)).

---

## 5. Where to go next

- **Why is it built this way?** -> [design-decisions.md](design-decisions.md)
- **How is hardware kept safe?** -> [safety-model.md](safety-model.md)
- **Map of all documentation** -> [../README.md](../README.md)
